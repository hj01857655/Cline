# Cline2api 使用说明

> 目录：`E:\VSCodeSpace\Agent\Cline\Cline2api\`（端口 **8381**）
> 上游：`https://api.cline.bot`（ClinePass 通道，仅锁免费模型）
> 建成时间：2026-10-11

## 1. 它是什么

把 Cline 的**免费模型**暴露成标准 OpenAI 兼容接口（只锁 free 面，4 个模型），
供任意 OpenAI 客户端调用。

## 2. 启动

```bash
python server.py
# OpenAI Base URL: http://127.0.0.1:8381/v1（key 见 .env 的 API_KEY）
```

- 后台线程每 30 分钟续 refreshToken 链（保凭证常新）；
- 401 时自动刷新重发一次（自愈）。

## 3. 登录 / 重新授权

正常情况下**不需要**重新授权：后台每 30 分钟自动续 refreshToken 链，401 自愈也会
先刷新重发。凭证整链彻底失效（refresh 也失败）时才重跑：

```bash
python oauth.py
# 浏览器打开输出的 authkit.cline.bot/device?user_code=XXXX-XXXX 链接并授权
```

## 4. 关键：`Authorization` 必须带 `workos:` 前缀

Cline 2025-09 起认证后端为 WorkOS（cline/cline#6683，v3.32.6 起）。
chat 端点要求：

```
Authorization: Bearer workos:<token>   ← 必须带 workos: 前缀
User-Agent: Cline/<ver>
X-CLIENT-TYPE / X-CLIENT-VERSION / X-PLATFORM …
```

**缺前缀的统一症状**：任何 token（新旧都一样）一律
`401 Unauthorized: Please make sure you're using the latest version of Cline and
re-authenticate your Cline account.` ——看起来像要重新登录，实际只是头不对。
遇到 401 先检查前缀，不要重跑 oauth.py。
（社区同款案例：OmniRoute #3321，补前缀+身份头后解决。）

## 5. 其他踩坑

- **register 响应包裹层**：上游 2026-10 起把 oauth register 响应包了一层
  `{"data": {...}}`，`oauth.py` 已兼容两种形态（顶层与 data 内层都读）。
- **配额**：free 面 per-IP 限流，密集测试会 429，冷却自恢复。
- 凭证隔离：只读本目录 `credentials.json`，绝不碰 Cline 客户端本体的凭证存储；
  dumps 只落 body，不落 header。

## 6. 相关文件

- `server.py` —— 反代主体（身份头在 `_upstream_headers()`）
- `oauth.py` —— 设备流登录（`python oauth.py`）
- `credential.py` —— 凭证读写 + refreshToken 续期
- `credentials.json` —— accessToken/refreshToken（gitignore）
- `.env` —— `API_KEY`（本地鉴权，当前为 `sk-cline-local`）
