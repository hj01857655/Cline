# Cline2api

> Cline 免费模型 → OpenAI / Anthropic 兼容 API 网关

把 Cline 的免费模型（免费通道 `cline-free/*`，当前 4 个）暴露为三协议兼容接口，供任意客户端调用。

## 功能特性

- **三协议兼容**：OpenAI Chat Completions · OpenAI Responses · Anthropic Messages
- **凭证自愈**：后台每 30 分钟检查，仅临期续 refreshToken；401 自动刷新重发
- **流式 / 非流式双模式**

## 快速开始

```bash
pip install -r requirements.txt
python server.py
```

```
Base URL : http://127.0.0.1:8381/v1
API Key  : .env 的 API_KEY
Model    : /v1/models 返回的 id
```

### 首次登录

正常情况下不需要重新授权——后台自动续期。凭证整链失效时才重跑：

```bash
python oauth.py
# 浏览器打开 authkit.cline.bot/device?user_code=XXXX-XXXX 并授权
```

## 免费模型清单

| 模型 id | 名称 | 说明 |
| --- | --- | --- |
| `cline-free/nemotron-3.5-super-vl` | cline-free/nemotron-3.5-super-vl | NVIDIA’s latest model with 120B and fast output |
| `cline-free/mimo-v2.6-flash` | Mimo V2.6 Flash | Mixture-of-Experts architecture with 309B total parameters |
| `cline-free/muse-spark-1.3-contributor` | Muse Spark 1.3 Contributor | Meta’s multimodal reasoning model for experimentation, learning, and early-stage agentic, multi-agent, and coding workflows. |
| `cline-free/solar-mini4` | Solar Mini 4 | Compact 35-billion parameter mixture-of-experts |

## API 接口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI Chat Completions（流式/非流式） |
| `/v1/responses` | POST | OpenAI Responses API（请求翻 Chat 调上游，响应由桥重放原生事件流） |
| `/v1/messages` | POST | Anthropic Messages API（翻译层 ⇄ Chat） |
| `/v1/models` | GET | 可用模型列表（仅 free 模型） |
| `/health` | GET | 存活探针 |

### 协议翻译架构

```
客户端                 proxy 翻译层              上游（仅 Chat）
─────────            ─────────────            ─────────────
Chat Completions ──→  直通                 ──→  api.cline.bot/chat/completions
Responses        ──→  responses_bridge     ──→  api.cline.bot/chat/completions
                      （请求翻 Chat；响应重放 Responses 事件流——sequence_number
                        递增、终帧携带聚合全文与 usage）
Anthropic        ──→  anthropic_bridge     ──→  api.cline.bot/chat/completions
                      （双向翻译；401 时走同一免费清单门 + 自愈重试）
```

Chat 是上游母语；Responses / Anthropic 均为「方言 ⇄ 母语」双向翻译层。`cache_control` 与 Anthropic 入站 `thinking` 配置无 Chat 对应项，翻译时丢弃。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `API_KEY` | `sk-cline-local` | 本地鉴权 Bearer token |
| `PORT` | `8381` | 监听端口 |

## 认证要点

Cline 2025-09 起认证后端为 WorkOS（v3.32.6+）。chat 端点要求：

```
Authorization: Bearer workos:<token>   ← 必须带 workos: 前缀
User-Agent: Cline/<ver>
X-CLIENT-TYPE / X-CLIENT-VERSION / X-PLATFORM
```

**缺前缀的统一症状**：任何 token 一律 `401 Unauthorized`，看起来像要重新登录，实际只是头不对。遇到 401 先检查前缀，不要重跑 oauth.py。

## 已知限制

- **stream ended prematurely**：上游长流偶发掐断（非反代超时），断流时补 `upstream_error` 错误帧 + `[DONE]`，避免客户端把半截回答当完整结果
- **配额**：free 面按 per-IP 限流，密集测试会 429，冷却自恢复，反代不做退避重试
- **模型会变**：免费清单以服务端活清单为准，见「免费模型清单」
- **cache_control / Anthropic thinking 配置丢弃**：Chat 协议无对应项（上游亦无 Anthropic 式 prompt cache）
- **凭证隔离**：只读本目录 `credentials.json`，绝不碰 Cline 客户端本体凭证
