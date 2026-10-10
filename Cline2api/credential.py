# -*- coding: utf-8 -*-
"""Cline2api 凭证模块：读反代目录 credentials.json（唯一凭证来源）+ refreshToken 自动刷新。

- 凭据文件: 本目录 credentials.json（oauth.py 产出后迁入，不碰官方 CLI 的 providers.json）
- 刷新: POST {API_BASE}/api/v1/auth/refresh body {refreshToken, grantType:"refresh_token"}
  （端点与请求体同 cline 源码 DEFAULT_AUTH_ENDPOINTS.refresh / refreshClineToken）
- 刷新结果原子写回凭据文件 + 内存缓存 25 分钟
- chat 端点的 Authorization 必须带 `workos:` 前缀（见 server.py `_upstream_headers`）；
  带前缀后 register/refresh 产物均可正常调用，无需重新 oauth。
"""
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
TOKEN_TTL = 25 * 60

_lock = threading.RLock()
_CACHE = {"token": None, "at": 0.0}


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
    """当前可用 Bearer（源码 formatClineApiKey 口径：不带 workos: 前缀的补上）；
    内存缓存命中直接返回。"""
    with _lock:
        if not force and _CACHE["token"] and time.time() - _CACHE["at"] < TOKEN_TTL:
            return _CACHE["token"]
        data = _read_file()
        tok = data["accessToken"].strip()
        if not tok.lower().startswith("workos:"):
            tok = "workos:" + tok
        _CACHE["token"], _CACHE["at"] = tok, time.time()
        return tok


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
    if data_inner.get("expiresIn"):
        data["expiresAt"] = int(time.time()) + int(data_inner["expiresIn"])
    _write_file(data)
    with _lock:
        _CACHE["token"], _CACHE["at"] = new_at, time.time()
    print("[credential] 令牌已刷新并写回 credentials.json", flush=True)
    return new_at


def load() -> dict:
    """账号快照（不含 token）。"""
    data = _read_file()
    return {"provider": data.get("provider") or "cline-pass",
            "expiresAt": data.get("expiresAt") or 0}
