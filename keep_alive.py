"""
心跳脚本：每隔1分钟向指定API发送请求，保持模型在线
"""
import json
import time
import sys
import urllib.request
import urllib.error
import ssl
from datetime import datetime

API_URL = "https://oddb888oocgqce5cm5g9hhqqo5kgkckj.openapi-qb.sii.edu.cn/v1/chat/completions"
API_KEY = "ceCWmOjqfWkvUs4oXei6F9QubL0DbwtkdLZ46FG5j5Y="
MODEL = "/inspire/qb-ilm/project/ai4education/public/models/GLM-5.1-FP8"
INTERVAL = 60  # 秒

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def send_heartbeat():
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 200,
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        log("发送请求...")
        with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
            data = json.loads(resp.read())
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {}) or {}
            content = msg.get("content") or msg.get("reasoning_content", "")
            usage = data.get("usage", {})
            log(f"✅ OK | reply: {repr(content[:80])} | tokens: {usage.get('total_tokens', '?')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        log(f"❌ HTTP {e.code}: {body}")
    except Exception as e:
        log(f"❌ {type(e).__name__}: {e}")


if __name__ == "__main__":
    log(f"心跳启动 | 间隔 {INTERVAL}s | 模型 {MODEL}")
    while True:
        send_heartbeat()
        log(f"下次心跳 {INTERVAL}s 后")
        time.sleep(INTERVAL)
