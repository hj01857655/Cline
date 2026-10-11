# Cline / cline2api

Cline 逆向调研成果，以及 LiteLLM 网关的免费层 OpenAI 兼容代理（`Cline2api`，端口 **8381**）。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`Cline2api/`](Cline2api/) | 主产物：OpenAI 兼容代理（详见其 README） |
| [`docs/`](docs/) | 桌面端前端布局与后端架构、逆向工具（Swagger/HEARTBEAT/gist/pastebin） |
| `cline/` | Cline 客户端源码（analysis = 官方 SWE-bench analysis） |
| `cline-plugins/` | 插件生态（core/Template），含 Internal (OSS) / Pro API 架构文档 |

## Cline2api 速览

```bash
cd Cline2api
python server.py
# OpenAI Base URL: http://127.0.0.1:8381/v1（key 见 .env 的 API_KEY）
```

上游 LiteLLM 原生就是 OpenAI 形态，所以反代**不需要协议翻译**，只做三件事：按 30 分钟周期刷新可用免费模型清单、在 Authorization 头加 `workos:` 前缀、非流式本地聚合。免签模型判定按免费 id 规则（`cline-free/*`、`*:free`、catalog pricing 三项全 0）动态判断，不硬编码。

## 踩坑记录

1. **`workos:` 前缀是 chat 401 的真因**。看到 401 先查前缀，不要重跑 oauth——旧票补前缀即 200，证明与票新旧无关。证据链：旧凭证+无前缀→401 / 旧凭证+workos:→200 / 新授权+workos:→200。
2. **register 接口有 `{"data":{...}}` 包裹层**。这个解析 bug 只坏"重新登录这条路"（新凭证不落盘），不会引起已有凭证的 401。
3. **免费模型清单每 30 分钟从 LiteLLM 自动刷新**，不写死。模型真值来自上游 pricing，不在清单就报 `model ... 不在免费清单`。

## 与 CodeArts / OpenCode 的关系

三个反代都是本地 OpenAI 兼容网关，各自独立。Cline2api 上游是 Cline 内部 LiteLLM 网关，非 zen/CodeArts 系统，不共享凭证或会话。
