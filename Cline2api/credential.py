# -*- coding: utf-8 -*-
"""Cline2api 凭证模块：读反代目录 credentials.json（唯一凭证来源）+ refreshToken 自动刷新。

- 凭据文件: 本目录 credentials.json（oauth.py 产出后迁入，不碰官方 CLI 的 providers.json）
- 刷新: POST {API_BASE}/api/v1/auth/refresh body {refreshToken, grantType:"refresh_token"}
  （端点与请求体同 cline 源码 DEFAULT_AUTH_ENDPOINTS.refresh / refreshClineToken）
- 刷新结果原子写回凭据文件 + 内存缓存（按 token 真实 exp 判定，临期即失效）
- chat 端点的 Authorization 必须带 `workos:` 前缀（见 server.py `_upstream_headers`）；
  带前缀后 register/refresh 产物均可正常调用，无需重新 oauth。
"""
import base64
import json
import os
import threading
import time

import requests

# 唯一凭证来源：反代目录（与 qoder2api credentials.json 同款约定）
AUTH_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
API_BASE = "https://api.cline.bot"
REFRESH_PATH = "/api/v1/auth/refresh"
UA = "Cline2api/0.1"
# accessToken 实测 TTL 仅 60 分钟（JWT iat/exp），故缓存不能按固定时长拍脑袋，
# 一律以真实 exp 为准；_FRESH_MARGIN 为提前量，临期即视为需刷新。
FRESH_MARGIN = 120

_lock = threading.RLock()
_CACHE = {"token": None, "at": 0.0, "exp": 0.0}


def _jwt_exp(tok: str) -> float:
    """从 JWT payload 取 exp；非 JWT 或解析失败返回 0.0（交由 expiresAt 兜底）。"""
    parts = (tok or "").split(".")
    if len(parts) != 3:
        return 0.0
    seg = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return float(json.loads(base64.urlsafe_b64decode(seg))["exp"])
    except Exception:
        return 0.0


def _expiry_of(data: dict, tok: str = "") -> float:
    """token 真实过期时刻：expiresAt 优先，其次 JWT exp，都没有则 0（视为永不过期）。"""
    try:
        exp = float(data.get("expiresAt") or 0)
    except (TypeError, ValueError):
        exp = 0.0
    return exp or _jwt_exp(tok or data.get("accessToken") or "")


def _is_fresh(exp: float) -> bool:
    """距过期还够用（留 _FRESH_MARGIN 提前量）。exp=0 表示上游未给有效期，从不主动刷。"""
    return exp <= 0 or exp - time.time() > FRESH_MARGIN



def _read_file() -> dict:
    if not os.path.isfile(AUTH_STORE):
        raise RuntimeError("未找到 %s，请先登录：python oauth.py" % AUTH_STORE)
    try:
        with open(AUTH_STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise RuntimeError("凭据文件无法解析：%s" % e)
    if not data.get("accessToken"):
        raise RuntimeError("凭据缺少 accessToken，请重新登录：python oauth.py")
    return data


def _write_file(data: dict) -> None:
    tmp = AUTH_STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, AUTH_STORE)


def token(force: bool = False) -> str:
    """当前可用 Bearer（源码 formatClineApiKey 口径：不带 workos: 前缀的补上）。

    缓存有效性按 token 真实 exp 判定（留 FRESH_MARGIN 提前量），不再用固定 TTL：
    accessToken 实测只活 60 分钟，固定 25 分钟缓存会在临期时把过期 token 发给上游。
    """
    with _lock:
        if not force and _CACHE["token"] and _is_fresh(_CACHE["exp"]):
            return _CACHE["token"]
        data = _read_file()
        tok = data["accessToken"].strip()
        exp = _expiry_of(data, tok)
        if not tok.lower().startswith("workos:"):
            tok = "workos:" + tok
        _CACHE.update(token=tok, at=time.time(), exp=exp)
        return tok


def ensure_fresh() -> bool:
    """磁盘上的 token 临期则先刷新，返回是否发生了刷新。

    供启动预检用：磁盘 token 还新鲜则完全不碰上游（消除"每次启动必刷新"，
    也避免把刷新打在用户第一个请求上）。已过期或临期才调 refresh()。
    """
    with _lock:
        cached_fresh = bool(_CACHE["token"]) and _is_fresh(_CACHE["exp"])
    if cached_fresh:
        return False
    data = _read_file()
    if _is_fresh(_expiry_of(data)):
        return False
    refresh()
    return True


def refresh() -> str:
    """refreshToken 换新 accessToken；成功则原子写回并更新缓存。

    换出的 accessToken 带 `workos:` 前缀调用 chat 即可用（前缀见 server.py
    `_upstream_headers`）；401 自愈依赖本方法正常工作。
    """
    data = _read_file()
    rt = data.get("refreshToken") or ""
    if not rt:
        raise RuntimeError("凭据无 refreshToken，请重新登录：python oauth.py")
    try:
        resp = requests.post(API_BASE + REFRESH_PATH,
                             json={"refreshToken": rt, "grantType": "refresh_token"},
                             headers={"Content-Type": "application/json", "User-Agent": UA},
                             timeout=30)
    except requests.RequestException as e:
        raise RuntimeError("刷新请求失败：%s" % e)
    body = resp.json() if resp.content else {}
    data_inner = body.get("data") or body
    new_at = data_inner.get("accessToken") or data_inner.get("access_token")
    if resp.status_code != 200 or not new_at:
        raise RuntimeError("刷新失败 HTTP %s: %s" % (resp.status_code, str(body)[:200]))
    data["accessToken"] = new_at
    if data_inner.get("refreshToken") or data_inner.get("refresh_token"):
        data["refreshToken"] = data_inner.get("refreshToken") or data_inner.get("refresh_token")
    # 新 token 的真实过期时刻：JWT exp 优先；上游没返 expiresIn 时磁盘 expiresAt 会残留
    # 旧 token 的过期值，必须用 JWT exp 覆盖，否则刷新完立刻被判临期。
    jwt_exp = _jwt_exp(new_at)
    if jwt_exp:
        data["expiresAt"] = int(jwt_exp)
    elif data_inner.get("expiresIn"):
        data["expiresAt"] = int(time.time()) + int(data_inner["expiresIn"])
    _write_file(data)
    with _lock:
        _CACHE.update(token=new_at, at=time.time(), exp=_expiry_of(data, new_at))
    print("[credential] 令牌已刷新并写回 credentials.json（有效期至 %s）"
          % (time.strftime("%H:%M:%S", time.localtime(_CACHE["exp"])) if _CACHE["exp"] else "未知"),
          flush=True)
    return new_at


def load() -> dict:
    """账号快照（不含 token）。"""
    data = _read_file()
    return {"provider": data.get("provider") or "cline-pass",
            "expiresAt": data.get("expiresAt") or 0}
