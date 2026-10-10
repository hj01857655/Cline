# -*- coding: utf-8 -*-
"""ClinePass OAuth 登录（WorkOS 设备流），凭据落盘 ~/.cline/data/Cline2api_auth.json。

协议依据 cline 源码 sdk/packages/core/src/auth/cline.ts（useWorkOSDeviceAuth 路径）：

    POST https://api.workos.com/user_management/authorize/device
         client_id, grant_type=urn:ietf:params:oauth:grant-type:device_code
    → { verification_uri(_complete), user_code, device_code, expires_in, interval }
    （浏览器打开 verification_uri，输入 user_code 授权）
    POST https://api.workos.com/user_management/authenticate
         client_id, grant_type=urn:ietf:params:oauth:grant-type:device_code, device_code
    → 轮询至 access_token（authorization_pending / slow_down 处理）
    POST {api}/api/v1/auth/register  body {accessToken, refreshToken}
    → { accessToken, refreshToken }（Cline 自家 token，配额记在 cline-pass 身上）

用法：python oauth.py
"""
import json
import os
import sys
import time

import requests

WORKOS_CLIENT_ID = "client_01K3A541FN8TA3EPPHTD2325AR"  # production（cline-environment.ts）
WORKOS_DEVICE = "https://api.workos.com/user_management/authorize/device"
WORKOS_TOKEN = "https://api.workos.com/user_management/authenticate"
API_BASE = "https://api.cline.bot"
REGISTER = "/api/v1/auth/register"
# ClinePass 凭据独立落盘，不碰官方 CLI 的 secrets.json/provider settings
AUTH_STORE = os.path.join(os.path.expanduser("~"), ".cline", "data", "Cline2api_auth.json")
UA = "Cline2api/0.1"
PENDING = {"authorization_pending", "slow_down"}


def _post(url: str, data: dict) -> dict:
    r = requests.post(url, data=data, headers={"User-Agent": UA}, timeout=30)
    return r.json() if r.content else {}


def login() -> dict:
    """WorkOS 设备流 → Cline register，返回并落盘凭据。"""
    d = _post(WORKOS_DEVICE, {
        "client_id": WORKOS_CLIENT_ID,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    })
    if "device_code" not in d:
        raise RuntimeError("device 授权失败: %s" % str(d)[:200])
    print("[oauth] 浏览器打开并输入代码：%s" % (d.get("verification_uri_complete") or d["verification_uri"]), flush=True)
    print("[oauth] user_code = %s" % d.get("user_code"), flush=True)

    interval = max(int(d.get("interval") or 5), 2)
    deadline = time.time() + int(d.get("expires_in") or 600)
    tokens = {}
    while time.time() < deadline:
        time.sleep(interval)
        t = _post(WORKOS_TOKEN, {
            "client_id": WORKOS_CLIENT_ID,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": d["device_code"],
        })
        err = (t.get("error") or "")
        if "access_token" in t:
            tokens = t
            break
        if err in PENDING:
            if err == "slow_down":
                interval += 5
            continue
        raise RuntimeError("token 轮询失败: %s %s" % (err, str(t)[:200]))
    if not tokens:
        raise RuntimeError("设备授权超时")

    # 用 WorkOS token 换 Cline 自家凭据（register，与官方 CLI 同款）
    r = requests.post(API_BASE + REGISTER, json={
        "accessToken": tokens["access_token"],
        "refreshToken": tokens.get("refresh_token") or "",
    }, headers={"Content-Type": "application/json", "User-Agent": UA}, timeout=30)
    body = r.json() if r.content else {}
    # 上游 2026-10 起把 register 响应包了一层 {"data": {...}}，两种形态都兼容
    inner = body.get("data") if isinstance(body.get("data"), dict) else body
    access = inner.get("accessToken") or inner.get("access_token") or body.get("accessToken") or body.get("access_token")
    if r.status_code != 200 or not access:
        raise RuntimeError("register 失败 HTTP %s: %s" % (r.status_code, str(body)[:200]))

    creds = {
        "accessToken": access,
        "refreshToken": inner.get("refreshToken") or inner.get("refresh_token") or tokens.get("refresh_token") or "",
        "provider": "cline-pass",
        "expiresAt": int(time.time()) + int(inner.get("expiresIn") or body.get("expiresIn") or 0),
    }
    os.makedirs(os.path.dirname(AUTH_STORE), exist_ok=True)
    with open(AUTH_STORE, "w", encoding="utf-8") as fh:
        json.dump(creds, fh, ensure_ascii=False, indent=2)
    print("[oauth] ✅ 凭据已写入 %s" % AUTH_STORE, flush=True)
    return creds


if __name__ == "__main__":
    sys.exit(login() and 0 or 0)
