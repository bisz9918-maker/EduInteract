"""
API 中转代理服务器 - 增强版 v2
改进超时和重试策略
"""
import json
import asyncio
import time
import uuid
import os
import random
from datetime import datetime
from typing import Optional, Any, Dict
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse


# ============ 配置 ============
# 默认后端（未匹配 MODEL_ROUTES 时使用）
CUSTOM_API_BASE="https://dbabckehahbochapkqjba599o8g895cj.openapi-qb-ai.sii.edu.cn/v1"
CUSTOM_API_KEY="PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU="

# 模型名映射：自定义短名 → {api_base, api_key, model}
# 客户端请求 model="custom" 时，自动替换为真实模型名并路由到对应后端
MODEL_ROUTES = {
    "Kimi-K2.6": {
        "api_base": "https://dbabckehahbochapkqjba599o8g895cj.openapi-qb-ai.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "/inspire/qb-ilm/project/ai4education/public/models/Kimi-K2.6",
    },
    "Qwen3.5-122B-A10B":{
        "api_base": "https://59hdgpc8c8aec9hokpha5o5bdqegbhb5.openapi-qb.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "/inspire/qb-ilm/project/ai4education/public/models/Qwen/Qwen3.5-122B-A10B",
        },
    "Qwen3.6-27B":{
        "api_base": "https://ea5maamppajpchmpmqk5obbpemep5p5k.openapi-qb-ai.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "/inspire/qb-ilm/project/ai4education/public/models/Qwen3.6-27B",
        },
    "Qwen3.5-397B-A17B-FP8":{
        "api_base": "https://cge8kkjh9jgqcmjqkgpdedqqaog8gbkb.openapi-qb-ai.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "qwen3.5-397b",
        },
    "Ministral-3-14B-Instruct-2512":{
        "api_base": "https://mapeggppkq8hcqpqjphobbda889qagbo.openapi-qb.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "ministral-3b",
        },
    "Mistral-Small-4-119B-2603":{
        "api_base": "https://p9pgoh9ecmpcckghmd999jeae9pbpmbm.openapi-qb.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "mistral-small-4",
        },
    "Mistral-Large-3-675B-Instruct-2512":{
        "api_base": "https://8hhoh5p5999cccpjjh5jghjcmcpoa5me.openapi-qb.sii.edu.cn/v1",
        "api_key": "PoECFccxeKiR2xJzaPZmY9GmAoNjIXEF5Wcd3JrMMVU=",
        "model": "/inspire/qb-ilm/project/ai4education/public/models/Mistral-Large-3-675B-Instruct-2512",
        },
    "Gemini-3.1-Pro":{
        "api_base": "https://api.innospark.cn/v1",
        "api_key": "sk-chGbcRbWRfGH1r8FmbJzd1mRpfE4G7MkKA4OToH16KdV2J8v",
        "model": "gemini-3.1-pro-preview",
        },
    "Claude-Sonnet-4-6":{
        "api_base": "https://api.innospark.cn/v1",
        "api_key": "sk-chGbcRbWRfGH1r8FmbJzd1mRpfE4G7MkKA4OToH16KdV2J8v",
        "model": "claude-sonnet-4-6",
        },
    "GPT-5.4-Pro":{
        "api_base": "https://api.innospark.cn/v1",
        "api_key": "sk-chGbcRbWRfGH1r8FmbJzd1mRpfE4G7MkKA4OToH16KdV2J8v",
        "model": "gpt-5.4-pro",
        },

}
PROXY_HOST = "0.0.0.0"
PROXY_PORT = 8008
LOG_DIR = "logs"
LOG_FILE = "api_logs.jsonl"


# ============ 超时和重试配置 ============
class RetryConfig:
    """重试配置"""
    MAX_RETRIES = 3
    BASE_DELAY = 40
    MAX_DELAY = 160.0
    EXPONENTIAL_BASE = 2
    JITTER = True
    RETRYABLE_STATUS_CODES = {502, 503, 504, 429}
    RETRYABLE_EXCEPTIONS = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        ConnectionResetError,
    )


class TimeoutConfig:
    """超时配置"""
    DEFAULT = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
    LONG_REQUEST = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0)
    SHORT_REQUEST = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)

    @classmethod
    def get_timeout(cls, request_body: Any) -> httpx.Timeout:
        if not isinstance(request_body, dict):
            return cls.DEFAULT
        messages = request_body.get("messages", [])
        total_content_length = sum(
            len(str(m.get("content", "")))
            for m in messages if isinstance(m, dict)
        )
        max_tokens = request_body.get("max_tokens", 0)
        if total_content_length > 10000 or max_tokens > 4000:
            return cls.LONG_REQUEST
        elif total_content_length < 500 and max_tokens < 500:
            return cls.SHORT_REQUEST
        return cls.DEFAULT


# ============ 日志模块 ============
os.makedirs(LOG_DIR, exist_ok=True)


def save_log(log_entry: Dict[str, Any]):
    log_path = os.path.join(LOG_DIR, LOG_FILE)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    result = dict(headers)
    for key in list(result.keys()):
        if key.lower() in ["authorization", "api-key", "x-api-key"]:
            val = result[key]
            if len(val) > 15:
                result[key] = val[:8] + "..." + val[-4:]
    return result


# ============ 重试逻辑 ============
def calculate_retry_delay(attempt: int) -> float:
    """计算重试延迟（指数退避 + 抖动）"""
    delay = min(
        RetryConfig.BASE_DELAY * (RetryConfig.EXPONENTIAL_BASE ** attempt),
        RetryConfig.MAX_DELAY
    )
    if RetryConfig.JITTER:
        # 添加 ±25% 的随机抖动
        jitter = delay * 0.25 * (2 * random.random() - 1)
        delay += jitter
    return max(delay, 1.0)


def should_retry(response: Optional[httpx.Response], exception: Optional[Exception], attempt: int) -> bool:
    """判断是否应该重试"""
    if attempt >= RetryConfig.MAX_RETRIES:
        return False
    if exception:
        return isinstance(exception, RetryConfig.RETRYABLE_EXCEPTIONS)
    if response:
        return response.status_code in RetryConfig.RETRYABLE_STATUS_CODES
    return False


# ============ 请求上下文 ============
class RequestContext:
    def __init__(self, request_id: str, method: str, path: str, request_body: Any):
        self.request_id = request_id
        self.method = method
        self.path = path
        self.request_body = request_body
        self.start_time = time.time()
        self.attempt = 0
        self.errors = []
        self.timeout_config = TimeoutConfig.get_timeout(request_body)
        self.requested_model = ""
        self.routed_model = ""

    def record_error(self, error: str, error_type: str):
        self.errors.append({
            "attempt": self.attempt,
            "error": error,
            "type": error_type,
            "timestamp": datetime.utcnow().isoformat()
        })

    @property
    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000


# ============ FastAPI 应用 ============
app = FastAPI(title="API Proxy v2")


class ProxyStats:
    total_requests = 0
    successful_requests = 0
    failed_requests = 0
    retried_requests = 0
    total_retries = 0


stats = ProxyStats()


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_v1(request: Request, path: str):
    return await proxy_request(request, f"/v1/{path}")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_root(request: Request, path: str):
    if path.startswith("v1/"):
        return await proxy_request(request, f"/{path}")
    return await proxy_request(request, f"/v1/{path}" if path else "/v1")


async def proxy_request(request: Request, path: str):
    """核心代理逻辑"""
    stats.total_requests += 1
    request_id = uuid.uuid4().hex[:8]

    body_bytes = await request.body()
    request_body = None
    if body_bytes:
        try:
            request_body = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            request_body = body_bytes.decode("utf-8", errors="replace")

    ctx = RequestContext(request_id, request.method, path, request_body)

    # 模型路由：如果请求中的 model 匹配 MODEL_ROUTES，替换为真实模型名和后端
    route_api_base = CUSTOM_API_BASE
    route_api_key = CUSTOM_API_KEY
    if isinstance(request_body, dict):
        # Ensure stream_options.include_usage=true for streaming requests
        # so vLLM returns usage in the final chunk and OAH can read usage.total
        if request_body.get("stream", False):
            if "stream_options" not in request_body:
                request_body["stream_options"] = {}
            request_body["stream_options"]["include_usage"] = True

        requested_model = request_body.get("model", "")
        ctx.requested_model = requested_model
        if requested_model in MODEL_ROUTES:
            route = MODEL_ROUTES[requested_model]
            request_body["model"] = route["model"]
            ctx.routed_model = route["model"]
            route_api_base = route["api_base"]
            route_api_key = route["api_key"]
            print(f"[{request_id}] 🔄 Model route: '{requested_model}' -> '{route['model']}' @ {route['api_base']}")

    base = route_api_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    target_url = f"{base}{path}"

    forward_headers = {
        "Authorization": f"Bearer {route_api_key}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": request.headers.get("user-agent", "API-Proxy/2.0"),
    }

    timeout_seconds = ctx.timeout_config.read
    print(f"[{request_id}] {request.method} {path} -> {target_url} (timeout: {timeout_seconds}s)")

    is_stream = isinstance(request_body, dict) and request_body.get("stream", False)

    try:
        if is_stream:
            return await handle_stream_with_retry(ctx, target_url, forward_headers, dict(request.headers))
        else:
            return await handle_normal_with_retry(ctx, target_url, forward_headers, dict(request.headers))
    except Exception as e:
        stats.failed_requests += 1
        error_msg = str(e)
        error_type = type(e).__name__

        print(f"[{request_id}] ❌ FINAL ERROR after {ctx.attempt} attempts [{error_type}]: {error_msg}")

        save_log({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "duration_ms": round(ctx.elapsed_ms, 2),
            "attempts": ctx.attempt + 1,
            "model": ctx.routed_model or ctx.requested_model,
            "requested_model": ctx.requested_model,
            "routed_model": ctx.routed_model,
            "path": path,
            "error": error_msg,
            "error_type": error_type,
            "all_errors": ctx.errors,
            "request_body": request_body
        })

        status_code = 502
        if "timeout" in error_msg.lower() or error_type == "ReadTimeout":
            status_code = 504
        elif "429" in error_msg or "rate" in error_msg.lower():
            status_code = 429

        return Response(
            content=json.dumps({
                "error": {
                    "message": f"Proxy error after {ctx.attempt + 1} attempts: {error_msg}",
                    "type": error_type,
                    "request_id": request_id,
                    "attempts": ctx.attempt + 1
                }
            }, ensure_ascii=False),
            status_code=status_code,
            media_type="application/json"
        )


async def handle_normal_with_retry(
    ctx: RequestContext,
    url: str,
    headers: dict,
    original_headers: dict,
):
    """处理普通请求（带智能重试）"""
    last_error: Optional[Exception] = None

    while True:
        try:
            if ctx.attempt > 0:
                delay = calculate_retry_delay(ctx.attempt - 1)
                print(f"[{ctx.request_id}] ⏳ Retry {ctx.attempt}/{RetryConfig.MAX_RETRIES} after {delay:.1f}s delay...")
                await asyncio.sleep(delay)
                stats.total_retries += 1

            async with httpx.AsyncClient(timeout=ctx.timeout_config) as client:
                if isinstance(ctx.request_body, dict):
                    response = await client.request(
                        method=ctx.method,
                        url=url,
                        headers=headers,
                        json=ctx.request_body
                    )
                else:
                    response = await client.request(
                        method=ctx.method,
                        url=url,
                        headers=headers,
                        content=ctx.request_body.encode("utf-8") if ctx.request_body else None
                    )

                response_body = None
                try:
                    response_body = response.json()
                except:
                    response_body = response.text

                # Normalize usage: OAH reads usage.total but some APIs return total_tokens
                if isinstance(response_body, dict):
                    usage = response_body.get("usage")
                    if isinstance(usage, dict) and "total" not in usage:
                        if "total_tokens" in usage:
                            usage["total"] = usage["total_tokens"]
                        if "prompt_tokens" in usage and "total" not in usage:
                            usage["total"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)

                status_emoji = "✅" if response.status_code == 200 else "⚠️"
                print(f"[{ctx.request_id}] {status_emoji} Response: {response.status_code} ({ctx.elapsed_ms:.0f}ms)")

                if should_retry(response, None, ctx.attempt):
                    error_msg = f"Server returned {response.status_code}"
                    ctx.record_error(error_msg, "HTTPError")
                    print(f"[{ctx.request_id}] ⚠️ {error_msg}, will retry...")
                    ctx.attempt += 1
                    stats.retried_requests += 1
                    continue

                if response.status_code == 200:
                    stats.successful_requests += 1
                else:
                    stats.failed_requests += 1

                save_log({
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "request_id": ctx.request_id,
                    "duration_ms": round(ctx.elapsed_ms, 2),
                    "attempts": ctx.attempt + 1,
                    "model": ctx.routed_model or ctx.requested_model,
                    "requested_model": ctx.requested_model,
                    "routed_model": ctx.routed_model,
                    "request": {
                        "method": ctx.method,
                        "path": ctx.path,
                        "headers": sanitize_headers(original_headers),
                        "body": ctx.request_body
                    },
                    "response": {
                        "status": response.status_code,
                        "body": response_body
                    },
                    "errors": ctx.errors if ctx.errors else None
                })

                # Return normalized response body (with usage.total added)
                normalized_content = json.dumps(response_body, ensure_ascii=False).encode("utf-8") if isinstance(response_body, dict) else response.content
                return Response(
                    content=normalized_content,
                    status_code=response.status_code,
                    media_type=response.headers.get("content-type", "application/json")
                )

        except RetryConfig.RETRYABLE_EXCEPTIONS as e:
            last_error = e
            error_type = type(e).__name__
            error_msg = str(e)

            ctx.record_error(error_msg, error_type)
            print(f"[{ctx.request_id}] ❌ Attempt {ctx.attempt + 1} failed: {error_type}")

            if should_retry(None, e, ctx.attempt):
                ctx.attempt += 1
                stats.retried_requests += 1
                continue
            else:
                raise

        except Exception as e:
            print(f"[{ctx.request_id}] ❌ Unexpected error: {type(e).__name__}: {e}")
            raise


async def handle_stream_with_retry(
    ctx: RequestContext,
    url: str,
    headers: dict,
    original_headers: dict,
):
    """处理流式请求（带重试）"""
    collected_chunks = []
    collected_content = ""
    response_status = 200
    stream_started = False
    last_valid_usage = None

    async def generate():
        nonlocal collected_content, response_status, stream_started, last_valid_usage

        while True:
            try:
                if ctx.attempt > 0 and not stream_started:
                    delay = calculate_retry_delay(ctx.attempt - 1)
                    print(f"[{ctx.request_id}] ⏳ Stream retry {ctx.attempt}/{RetryConfig.MAX_RETRIES} after {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    stats.total_retries += 1

                async with httpx.AsyncClient(timeout=ctx.timeout_config) as client:
                    async with client.stream(
                        method=ctx.method,
                        url=url,
                        headers=headers,
                        json=ctx.request_body if isinstance(ctx.request_body, dict) else None
                    ) as response:
                        response_status = response.status_code

                        if response.status_code in RetryConfig.RETRYABLE_STATUS_CODES:
                            if not stream_started and should_retry(response, None, ctx.attempt):
                                error_msg = f"Stream returned {response.status_code}"
                                ctx.record_error(error_msg, "HTTPError")
                                print(f"[{ctx.request_id}] ⚠️ {error_msg}, will retry stream...")
                                ctx.attempt += 1
                                stats.retried_requests += 1
                                continue

                        stream_started = True
                        print(f"[{ctx.request_id}] 🌊 Stream started: {response.status_code}")

                        if response.status_code != 200:
                            error_content = await response.aread()
                            yield error_content
                            return

                        async for raw_chunk in response.aiter_bytes():
                            collected_chunks.append(raw_chunk)
                            chunk_str = raw_chunk.decode("utf-8", errors="replace")

                            # Normalize usage in stream chunks: OAH reads usage.total
                            modified = False
                            lines_out = []
                            for line in chunk_str.split("\n"):
                                line_stripped = line.strip()
                                if line_stripped.startswith("data: ") and line_stripped[6:] != "[DONE]":
                                    try:
                                        data = json.loads(line_stripped[6:])
                                        delta = data.get("choices", [{}])[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            collected_content += content
                                        usage = data.get("usage")
                                        if isinstance(usage, dict):
                                            # Track the last valid usage for fallback
                                            if usage.get("total_tokens") is not None or usage.get("prompt_tokens") is not None:
                                                last_valid_usage = dict(usage)
                                            if "total" not in usage:
                                                if "total_tokens" in usage:
                                                    usage["total"] = usage["total_tokens"]
                                                elif "prompt_tokens" in usage:
                                                    usage["total"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                                            data["usage"] = usage
                                            modified = True
                                        if modified:
                                            lines_out.append(f"data: {json.dumps(data, ensure_ascii=False)}")
                                            continue
                                    except:
                                        pass
                                lines_out.append(line)

                            if modified:
                                yield "\n".join(lines_out).encode("utf-8")
                            else:
                                yield raw_chunk

                        stats.successful_requests += 1
                        # vLLM sometimes returns empty usage {} in the final stream chunk.
                        # If we have a previously seen valid usage, emit a corrected final chunk.
                        # This ensures OAH always gets accurate token counts.
                        if last_valid_usage:
                            if "total" not in last_valid_usage:
                                if "total_tokens" in last_valid_usage:
                                    last_valid_usage["total"] = last_valid_usage["total_tokens"]
                            if last_valid_usage.get("prompt_tokens") is not None:
                                fallback_chunk = json.dumps({
                                    "id": "usage-fallback",
                                    "object": "chat.completion.chunk",
                                    "choices": [],
                                    "usage": last_valid_usage
                                }, ensure_ascii=False)
                                yield f"data: {fallback_chunk}\n\n".encode()
                        break

            except RetryConfig.RETRYABLE_EXCEPTIONS as e:
                error_type = type(e).__name__
                ctx.record_error(str(e), error_type)

                if not stream_started and should_retry(None, e, ctx.attempt):
                    print(f"[{ctx.request_id}] ❌ Stream attempt {ctx.attempt + 1} failed: {error_type}")
                    ctx.attempt += 1
                    stats.retried_requests += 1
                    continue
                else:
                    error_msg = f"Stream error: {error_type}: {e}"
                    print(f"[{ctx.request_id}] ❌ {error_msg}")
                    stats.failed_requests += 1
                    yield f"data: {json.dumps({'error': error_msg})}\n\n".encode()
                    break

            except Exception as e:
                error_msg = f"Stream error: {type(e).__name__}: {e}"
                print(f"[{ctx.request_id}] ❌ {error_msg}")
                stats.failed_requests += 1
                yield f"data: {json.dumps({'error': error_msg})}\n\n".encode()
                break

        save_log({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "request_id": ctx.request_id,
            "duration_ms": round(ctx.elapsed_ms, 2),
            "attempts": ctx.attempt + 1,
            "is_stream": True,
            "model": ctx.routed_model or ctx.requested_model,
            "requested_model": ctx.requested_model,
            "routed_model": ctx.routed_model,
            "request": {
                "method": ctx.method,
                "path": ctx.path,
                "headers": sanitize_headers(original_headers),
                "body": ctx.request_body
            },
            "response": {
                "status": response_status,
                "content": collected_content[:1000] + "..." if len(collected_content) > 1000 else collected_content,
                "content_length": len(collected_content),
                "chunks_count": len(collected_chunks)
            },
            "errors": ctx.errors if ctx.errors else None
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


# ============ 端点 ============
@app.get("/")
async def health():
    key_status = "configured" if CUSTOM_API_KEY and CUSTOM_API_KEY != "your-api-key-here" else "NOT CONFIGURED"
    return {
        "status": "running",
        "version": "2.1",
        "target": CUSTOM_API_BASE,
        "api_key": key_status,
        "model_routes": list(MODEL_ROUTES.keys()),
        "stats": {
            "total_requests": stats.total_requests,
            "successful": stats.successful_requests,
            "failed": stats.failed_requests,
            "retried": stats.retried_requests,
        }
    }


@app.get("/v1/models")
async def list_models():
    """返回映射表中可用的自定义模型名"""
    models = []
    for alias, route in MODEL_ROUTES.items():
        models.append({
            "id": alias,
            "object": "model",
            "owned_by": "proxy",
            "real_model": route["model"],
        })
    return {"object": "list", "data": models}


@app.get("/_test")
async def test_upstream():
    """测试上游 API"""
    results = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            start = time.time()
            response = await client.get(
                f"{CUSTOM_API_BASE}/models",
                headers={"Authorization": f"Bearer {CUSTOM_API_KEY}"}
            )
            results["models"] = {
                "status": response.status_code,
                "latency_ms": round((time.time() - start) * 1000, 2)
            }
    except Exception as e:
        results["models"] = {"error": str(e)}

    return {"target": CUSTOM_API_BASE, "results": results}


@app.get("/_stats")
async def get_stats():
    success_rate = stats.successful_requests / max(stats.total_requests, 1) * 100
    return {
        "requests": {
            "total": stats.total_requests,
            "successful": stats.successful_requests,
            "failed": stats.failed_requests,
            "success_rate": f"{success_rate:.1f}%"
        },
        "retries": {
            "requests_retried": stats.retried_requests,
            "total_retries": stats.total_retries
        }
    }


@app.get("/_logs")
async def view_logs(limit: int = 50):
    log_path = os.path.join(LOG_DIR, LOG_FILE)
    if not os.path.exists(log_path):
        return {"logs": []}
    logs = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                logs.append(json.loads(line))
            except:
                pass
    return {"logs": logs[-limit:], "total": len(logs)}


if __name__ == "__main__":
    import uvicorn

    key_status = "✅ OK" if CUSTOM_API_KEY and CUSTOM_API_KEY != "your-api-key-here" else "❌ NOT SET"

    model_routes_str = "  ".join(
        f"'{alias}' → '{route['model']}'" for alias, route in MODEL_ROUTES.items()
    )

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║            API Proxy Server v2.1 (Model Routing)          ║
╠═══════════════════════════════════════════════════════════╣
║  Target:   {CUSTOM_API_BASE:<45} ║
║  API Key:  {key_status:<45} ║
╠═══════════════════════════════════════════════════════════╣
║  Model Routes:                                            ║
║  {model_routes_str:<55} ║
╠═══════════════════════════════════════════════════════════╣
║  Retry: max={RetryConfig.MAX_RETRIES}, delay={RetryConfig.BASE_DELAY}s-{RetryConfig.MAX_DELAY}s (exponential backoff)     ║
║  Timeout: {TimeoutConfig.DEFAULT.read}s default, {TimeoutConfig.LONG_REQUEST.read}s long requests            ║
╠═══════════════════════════════════════════════════════════╣
║  /v1/models - List routes  /_test  - Test upstream        ║
║  /_stats - Statistics      /_logs  - View logs            ║
╚═══════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)