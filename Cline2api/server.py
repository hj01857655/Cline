# -*- coding: utf-8 -*-
"""Cline2api：OpenAI 兼容反代 → api.cline.bot（ClinePass 通道，锁免费模型）。

上游协议（cline 源码 sdk/packages/llms）：
- chat 上游: POST {API_BASE}/api/v1/chat/completions（LiteLLM 形态，OpenAI 兼容）
- 免费清单: GET  {API_BASE}/api/v1/ai/cline/recommended-models
  → 免费 id：`cline-free/*`、`*:free`、catalog pricing 三项全 0
- 认证: Bearer accessToken（oauth.py 产出，credential.py 刷新）
"""
import json
import logging
import os
import sys
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request

import credential

load_dotenv()

API_BASE = "https://api.cline.bot"
CHAT_PATH = "/api/v1/chat/completions"
MODELS_PATH = "/api/v1/ai/cline/recommended-models"
UA = "Cline2api/0.1"
API_KEY = os.environ.get("API_KEY", "").strip()
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.getenv("PORT", "8381"))

# ── 日志（qoder2api 同一标准：request.log 轮转 + rid + in:/done: 双行 + ua=）────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "request.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("werkzeug").disabled = True

# ── 请求/响应原文落盘（默认 dumps/，DUMP_DIR 改路径，DUMP=0 关闭）─────────────
# 只落 body 原文，绝不落 HTTP header：Authorization 里是明文网关 key，且 body 需可直接重放
DUMP_DIR = os.environ.get("DUMP_DIR", "") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dumps")
DUMP_ON = os.environ.get("DUMP", "1").strip() != "0"
DUMP_MAX_BYTES = 512 * 1024   # 单方向落盘上限，防超大响应撑爆磁盘
DUMP_MAX_FILES = int(os.environ.get("DUMP_MAX_FILES", "200"))  # ≤0 表示不轮转


def _dump_trim():
    """dump 数量超过 DUMP_MAX_FILES 时按 mtime 删最旧（明文提示词会无限增长）。"""
    if DUMP_MAX_FILES <= 0:
        return
    try:
        entries = sorted((e for e in os.scandir(DUMP_DIR) if e.is_file()),
                         key=lambda e: e.stat().st_mtime)
    except OSError:
        return
    for stale in entries[:len(entries) - DUMP_MAX_FILES]:
        try:
            os.remove(stale.path)
        except OSError:
            pass


def _dump_save(rid, kind, data):
    """把请求/响应原文落盘到 dumps/<rid>.<kind>.txt（DUMP=0 时跳过）。"""
    if not DUMP_ON or not data:
        return
    try:
        os.makedirs(DUMP_DIR, exist_ok=True)
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        truncated = len(text) > DUMP_MAX_BYTES
        path = os.path.join(DUMP_DIR, "%s.%s.txt%s" % (rid, kind, ".truncated" if truncated else ""))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text[:DUMP_MAX_BYTES])
        _dump_trim()
    except OSError as e:
        logger.warning("[%s] 落盘失败: %s", rid, e)

# ── rid 单调计数器（替代 time-based 生成：旧式 time.time()*10%10000 每 1000 秒循环
# 撞名，r9983 曾在 09:43 与 09:59 各出现一次，导致按 rid 做的配对统计与 dump 落盘不可信）
_seq_lock = threading.Lock()
_req_seq = 0


def _next_req_id():
    global _req_seq
    with _seq_lock:
        _req_seq += 1
        return "r%04d" % _req_seq


app = Flask(__name__)

# ── 免费模型清单（启动拉一次，后台 10 分钟刷新）────────────────────────────────
_free_models = {"ids": [], "models": {}}


def _fetch_free_models() -> None:
    """拉 recommended-models：免费面 = body.free 数组（cline-free/* 前缀，无订阅可用）。
    clinePass/* 是订阅内含面（无 ClinePass 订阅一律 403 ENTITLEMENT），不放行。"""
    try:
        r = requests.get(API_BASE + MODELS_PATH,
                         headers={"User-Agent": UA}, timeout=20)
        body = r.json() if r.content else {}
        models = body.get("free") or []
        free_ids, catalog = [], {}
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = m.get("id") or ""
            if mid and (mid.startswith("cline-free/") or mid.endswith(":free")):
                free_ids.append(mid)
                catalog[mid] = m
        if free_ids:
            _free_models["ids"], _free_models["models"] = free_ids, catalog
            logger.info("[models] 免费模型 %d 个: %s", len(free_ids), ", ".join(free_ids))
        else:
            logger.warning("[models] free 列表为空（HTTP %s，顶层键=%s）",
                           r.status_code, list(body.keys())[:6])
    except Exception as e:
        logger.warning("[models] 拉取失败: %s", e)


def _model_refresh_loop() -> None:
    while True:
        time.sleep(600)
        _fetch_free_models()


def _token_refresh_loop() -> None:
    """后台 token 续期：每 30 分钟查一次，**临期才刷**。

    原先固定每 30 分钟无脑 refresh()，而 accessToken 实测只活 60 分钟
    （JWT iat/exp 10:40:59 → 11:40:59），于是每轮都可能白刷一次；而磁盘 token 一旦
    临期，真正触发刷新的反而是 401 自愈那条路径，刷新被砸在用户第一个请求上
    （表现成"每次启动必刷新"）。现改为 ensure_fresh()：token 还新鲜就不碰上游。
    刷新失败只记日志，绝不打断服务（下次循环再试）。
    """
    while True:
        time.sleep(30 * 60)
        try:
            credential.ensure_fresh()
        except Exception as e:
            logger.warning("[token] 后台刷新失败（下次循环再试）: %s", e)


@app.before_request
def _auth_and_rid():
    g.rid = _next_req_id()
    g.t0 = time.time()
    if API_KEY and request.path != "/health":
        if request.headers.get("Authorization") != "Bearer " + API_KEY:
            return jsonify(error="unauthorized"), 401
    ua = (request.headers.get("User-Agent") or "-").replace("\r", " ").replace("\n", " ")
    body_len = request.content_length or 0
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    g.payload = payload
    logger.info("[%s] in: %s %s | model=%s msgs=%s tools=%s stream=%s | ua=%s | body=%dB",
                g.rid, request.method, request.path,
                payload.get("model"), len(payload.get("messages") or []),
                len(payload.get("tools") or []), payload.get("stream"), ua, body_len)
    # 只对 chat 请求落盘 req 原文（可直接重放的纯 body，绝不落 header）
    if request.path == "/v1/chat/completions":
        _dump_save(g.rid, "req", request.get_data(cache=True, as_text=True))


def _upstream_headers() -> dict:
    """身份头全套：上游 2025-09 起 Firebase→WorkOS 迁移后，Authorization 必须带
    `workos:` 前缀（社区实锤，OmniRoute #3321 同款问题），否则 401 要求重登录。"""
    return {"Authorization": "Bearer workos:" + credential.token(),
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cline.bot", "X-Title": "Cline",
            "X-CLIENT-TYPE": "cline-sdk", "User-Agent": "Cline/2.6.9",
            "X-CLIENT-VERSION": "2.6.9", "X-PLATFORM": "cline-sdk",
            "X-PLATFORM-VERSION": "2.6.9", "X-IS-MULTIROOT": "false"}


@app.route("/health")
def health():
    return jsonify(ok=True, service="Cline2api")


@app.route("/v1/models")
def models():
    if not _free_models["ids"]:
        _fetch_free_models()
    now = int(time.time())
    return jsonify(data=[{"id": mid, "object": "model", "created": now, "owned_by": "cline-free"}
                         for mid in _free_models["ids"]])


def _model_free(model_id: str) -> bool:
    """免费面判定：仅 cline-free/*（或 *:free）。cline-pass/* 是订阅面，一律拒。"""
    if not _free_models["ids"]:
        _fetch_free_models()
    if not _free_models["ids"]:
        return False  # 清单拉不到时宁拒不放，防误打订阅面扣费
    return (model_id in _free_models["ids"]
            or model_id.startswith("cline-free/")
            or model_id.endswith(":free"))


@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    p = g.payload
    model = p.get("model") or ""
    if model and not _model_free(model):
        logger.warning("[%s] 拒绝非免费模型: %s", g.rid, model)
        return jsonify(error={"message": "model %s 不在免费清单（Cline2api 只转发免费模型）" % model,
                              "type": "invalid_request_error"}), 400
    payload = {k: v for k, v in p.items() if k in (
        "model", "messages", "stream", "temperature", "top_p", "max_tokens",
        "tools", "tool_choice", "stop", "user", "stream_options")}
    payload["model"] = model  # 模型 id 原样转（cline-pass/ 前缀上游自认）

    want_stream = bool(p.get("stream"))
    try:
        upstream = requests.post(API_BASE + CHAT_PATH, json=payload,
                                 headers=_upstream_headers(), stream=want_stream, timeout=180)
    except requests.RequestException as e:
        logger.error("[%s] 上游连接失败: %s", g.rid, e)
        return jsonify(error={"message": str(e), "type": "upstream_error"}), 502

    if upstream.status_code == 401:
        # 401 自愈：刷新一次重发
        try:
            credential.refresh()
            upstream = requests.post(API_BASE + CHAT_PATH, json=payload,
                                     headers=_upstream_headers(), stream=want_stream, timeout=180)
        except Exception as e:
            logger.error("[%s] 401 刷新后仍失败: %s", g.rid, e)
            return jsonify(error={"message": "upstream 401 after refresh", "type": "upstream_error"}), 502
    if upstream.status_code >= 400:
        body = upstream.text[:400]
        logger.warning("[%s] 上游错误 HTTP %s: %s", g.rid, upstream.status_code, body)
        return Response(upstream.text, status=upstream.status_code,
                        content_type=upstream.headers.get("Content-Type", "application/json"))

    if not want_stream:
        body = upstream.content
        logger.info("[%s] done: status=200 %dB %.1fs", g.rid, len(body), time.time() - g.t0)
        _dump_save(g.rid, "resp", body)
        return Response(body, status=200, content_type="application/json")

    # 流式生成器在请求上下文销毁后才迭代，期间禁止访问 g.*，否则抛
    # Working outside of application context（异常再被下面的 except 吞掉），
    # 表现为日志只有 in: 没有 done:、客户端收到空内容。
    rid, t0 = g.rid, g.t0
    dump_on = DUMP_ON  # 流式攒帧于内存，流末一次性落盘（DUMP=0 时不攒）

    def generate():
        total = 0
        buf = []
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    total += len(chunk)
                    if dump_on and total <= DUMP_MAX_BYTES:
                        buf.append(chunk)
                    yield chunk
            logger.info("[%s] done: stream %dB %.1fs", rid, total, time.time() - t0)
            if dump_on and buf:
                _dump_save(rid, "resp", b"".join(buf))
        except GeneratorExit:
            # 客户端主动断开（长流常见）。GeneratorExit 继承 BaseException，
            # 不加这分支会被下面的 except 漏掉、也不留日志，排查时看不出是谁先走的。
            logger.warning("[%s] client 断开: stream %dB %.1fs", rid, total, time.time() - t0)
            raise
        except Exception as e:
            logger.error("[%s] stream 中断: %s (%dB %.1fs)", rid, e, total, time.time() - t0)
            # 断流时把已收到的部分落盘：正常路径只在流末 _dump_save，中途断了
            # 就只剩 .req，2.8MB 证据全丢，下一次同样故障无从比对。
            if dump_on and buf:
                _dump_save(rid, "resp_partial", b"".join(buf))
            # 裸掐断会让客户端把半截回答当完整结果。显式补错误帧 + [DONE]
            # （与 CodeArts2api 的流内错误帧转 OpenAI 错误帧同一套约定）。
            err = json.dumps({"error": {"message": "upstream stream ended prematurely: %s" % e,
                                        "type": "upstream_error"}},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            try:
                yield b"data: " + err + b"\n\n"
                yield b"data: [DONE]\n\n"
            except GeneratorExit:
                raise

    resp = Response(generate(), status=200, mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


if __name__ == "__main__":
    try:
        info = credential.load()
        print("Cline2api 已启动: http://%s:%s (provider=%s)" % (LISTEN_HOST, LISTEN_PORT, info["provider"]))
    except Exception as error:
        print("凭证不可用: %s" % error)
        print("请先登录：python oauth.py")
        sys.exit(1)
    # 启动预检：磁盘 token 已临期就先续上，别等用户第一个请求吃 401 才刷
    # （失败不阻断启动，交给 401 自愈路径兜底）
    try:
        if credential.ensure_fresh():
            print("启动预检：token 临期，已提前刷新")
        else:
            print("启动预检：token 仍新鲜，跳过刷新")
    except Exception as error:
        print("启动预检刷新失败（不阻断，将由 401 自愈兜底）: %s" % error)
    _fetch_free_models()
    threading.Thread(target=_model_refresh_loop, daemon=True).start()
    threading.Thread(target=_token_refresh_loop, daemon=True).start()
    print("OpenAI Base URL: http://%s:%s/v1（仅免费模型）" % (LISTEN_HOST, LISTEN_PORT))
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True)
