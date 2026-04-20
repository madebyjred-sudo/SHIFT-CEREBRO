"""OpenRouter Universal Proxy — /v1/chat/completions and /v1/models

Production-grade OpenAI-compatible proxy that:
1. Accepts ANY model name from LobeChat
2. Maps it to OpenRouter model ID via MODEL_MAP (or passes through)
3. Calls OpenRouter API directly (streaming + non-streaming)
4. Fire-and-forget: triggers Peaje auto-ingest for the flywheel
5. Special case: 'cerebro-core' runs full Cerebro multi-agent orchestration

Mounts at prefix /v1 on the main FastAPI app (standard OpenAI SDK path).
"""
import os
import json
import time
import uuid
import asyncio
import httpx
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from config.models import MODEL_MAP
from peaje.ingest import process_auto_ingest
from graph.state import ChatMessage as PeajeChatMessage

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"
SITE_URL = "https://shiftpn.com"
SITE_NAME = "Shift Chat"

v1_router = APIRouter(prefix="/v1", tags=["openai-compat-v1"])


# ═══════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "cerebro-core"
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    n: Optional[int] = None
    stop: Optional[Any] = None
    # Shift-specific
    tenant_id: Optional[str] = "shift"


# ═══════════════════════════════════════════════════════════════
# MODEL CATALOG
# ═══════════════════════════════════════════════════════════════

# Build a clean model list from MODEL_MAP for the /v1/models endpoint
_MODEL_CATALOG = []
_seen = set()
for display_name, openrouter_id in MODEL_MAP.items():
    if openrouter_id not in _seen:
        _seen.add(openrouter_id)
        # Use the display_name as the model ID (what LobeChat sends)
        _MODEL_CATALOG.append({
            "id": display_name,
            "object": "model",
            "created": 1700000000,
            "owned_by": "shift-via-openrouter",
            "permission": [],
            "root": openrouter_id,
            "parent": None,
        })
# Always include cerebro-core as the flagship model
_MODEL_CATALOG.insert(0, {
    "id": "cerebro-core",
    "object": "model",
    "created": 1700000000,
    "owned_by": "shift-lab",
    "permission": [],
    "root": "cerebro-core",
    "parent": None,
})


# ═══════════════════════════════════════════════════════════════
# GET /v1/models
# ═══════════════════════════════════════════════════════════════

@v1_router.get("/models")
async def list_models():
    """Return available models in OpenAI /v1/models shape."""
    return {"object": "list", "data": _MODEL_CATALOG}


# ═══════════════════════════════════════════════════════════════
# POST /v1/chat/completions
# ═══════════════════════════════════════════════════════════════

@v1_router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions — Universal OpenRouter proxy.

    Routes:
    - model='cerebro-core' → Full Cerebro multi-agent orchestration
    - Any other model → Direct OpenRouter proxy with Peaje flywheel
    """
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    tenant = request.tenant_id or "shift"

    # Extract user message for Peaje
    user_messages = [m for m in request.messages if m.role == "user"]
    last_user_msg = user_messages[-1].content if user_messages else ""

    # ── Route: cerebro-core (multi-agent) ──
    if request.model == "cerebro-core":
        return await _handle_cerebro(request, completion_id, created, tenant, last_user_msg)

    # ── Route: Any other model → OpenRouter proxy ──
    if request.stream:
        return StreamingResponse(
            _stream_openrouter(request, completion_id, created, tenant, last_user_msg),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _sync_openrouter(request, completion_id, created, tenant, last_user_msg)


# ═══════════════════════════════════════════════════════════════
# CEREBRO MULTI-AGENT HANDLER
# ═══════════════════════════════════════════════════════════════

async def _handle_cerebro(
    request: ChatCompletionRequest,
    completion_id: str,
    created: int,
    tenant: str,
    last_user_msg: str,
):
    """Handle cerebro-core model: full multi-agent orchestration."""
    from cerebro.sdk import Cerebro, CerebroResponse
    from agents.registry import AGENTS

    if not last_user_msg:
        raise HTTPException(status_code=400, detail="No user message found")

    if request.stream:
        return StreamingResponse(
            _stream_cerebro(last_user_msg, tenant, completion_id, created),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        cerebro = Cerebro(tenant=tenant)
        response: CerebroResponse = cerebro.run(last_user_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cerebro error: {str(e)}")

    text = response.text
    agent_used = response.agent_used

    # Fire-and-forget Peaje
    _schedule_peaje(tenant, completion_id, agent_used, last_user_msg, text)

    return JSONResponse(content={
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": "cerebro-core",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(last_user_msg.split()),
            "completion_tokens": len(text.split()),
            "total_tokens": len(last_user_msg.split()) + len(text.split()),
        },
        "system_fingerprint": f"cerebro-{agent_used}",
    })


async def _stream_cerebro(
    query: str, tenant: str, completion_id: str, created: int
):
    """Stream Cerebro response as OpenAI ChatCompletionChunks via SSE."""
    from cerebro.sdk import Cerebro, CerebroResponse
    from agents.registry import AGENTS
    from graph.router import route_with_llm, determine_agent_from_message

    try:
        cerebro = Cerebro(tenant=tenant)

        # Phase 1: Emit tool_call chunks for visual feedback
        try:
            route_result = await route_with_llm(query)
            plan = route_result.get("execution_plan", [route_result.get("agent_id", "shiftai")])
        except Exception:
            plan = [determine_agent_from_message(query)]

        for idx, agent_id in enumerate(plan):
            agent_name = AGENTS.get(agent_id, {}).get("name", agent_id)
            agent_role = AGENTS.get(agent_id, {}).get("role", "Specialist")
            chunk = _make_chunk(completion_id, created, delta={
                "role": "assistant",
                "tool_calls": [{
                    "index": idx,
                    "id": f"call_{agent_id}_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": f"consult_{agent_id}",
                        "arguments": json.dumps({
                            "agent": agent_name,
                            "role": agent_role,
                            "task": "Analizando consulta...",
                        }, ensure_ascii=False),
                    },
                }],
            })
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.3)

        # Phase 2: Run Cerebro
        response: CerebroResponse = cerebro.run(query)
        text = response.text

        # Phase 3: Stream text in chunks
        CHUNK_SIZE = 200
        for i in range(0, len(text), CHUNK_SIZE):
            piece = text[i:i + CHUNK_SIZE]
            chunk = _make_chunk(completion_id, created, delta={"content": piece})
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

        # Phase 4: Stop
        yield f"data: {json.dumps(_make_chunk(completion_id, created, delta={}, finish_reason='stop'), ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

        # Fire-and-forget Peaje
        _schedule_peaje(tenant, completion_id, response.agent_used, query, text)

    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"data: {json.dumps(_make_chunk(completion_id, created, delta={'content': f'[Error: {str(e)}]'}, finish_reason='stop'), ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


# ═══════════════════════════════════════════════════════════════
# OPENROUTER DIRECT PROXY
# ═══════════════════════════════════════════════════════════════

def _resolve_model(model_name: str) -> str:
    """Resolve a model name to its OpenRouter ID."""
    # Direct match in MODEL_MAP
    if model_name in MODEL_MAP:
        return MODEL_MAP[model_name]
    # Already an OpenRouter-style ID (contains /)
    if "/" in model_name:
        return model_name
    # Fallback
    return DEFAULT_MODEL


async def _sync_openrouter(
    request: ChatCompletionRequest,
    completion_id: str,
    created: int,
    tenant: str,
    last_user_msg: str,
) -> JSONResponse:
    """Non-streaming call to OpenRouter."""
    openrouter_model = _resolve_model(request.model)

    payload = {
        "model": openrouter_model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": False,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "X-Title": SITE_NAME,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text, "type": "upstream_error", "code": resp.status_code}},
        )

    data = resp.json()

    # Extract response text for Peaje
    response_text = ""
    if data.get("choices"):
        response_text = data["choices"][0].get("message", {}).get("content", "")

    # Fire-and-forget Peaje
    _schedule_peaje(tenant, completion_id, f"direct:{request.model}", last_user_msg, response_text)

    # Re-wrap with our completion ID
    data["id"] = completion_id
    data["system_fingerprint"] = f"shift-proxy-{request.model}"

    return JSONResponse(content=data)


async def _stream_openrouter(
    request: ChatCompletionRequest,
    completion_id: str,
    created: int,
    tenant: str,
    last_user_msg: str,
):
    """Streaming proxy to OpenRouter via SSE."""
    openrouter_model = _resolve_model(request.model)

    payload = {
        "model": openrouter_model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": True,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "X-Title": SITE_NAME,
    }

    collected_text = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status_code != 200:
                error_body = await resp.aread()
                error_chunk = _make_chunk(
                    completion_id, created,
                    delta={"content": f"[OpenRouter Error {resp.status_code}: {error_body.decode()[:200]}]"},
                    finish_reason="stop",
                )
                yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Strip "data: "

                if data_str.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break

                try:
                    chunk_data = json.loads(data_str)
                    # Rewrite the ID to ours
                    chunk_data["id"] = completion_id
                    chunk_data["system_fingerprint"] = f"shift-proxy-{request.model}"

                    # Collect text for Peaje
                    if chunk_data.get("choices"):
                        delta = chunk_data["choices"][0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            collected_text.append(delta["content"])

                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                except json.JSONDecodeError:
                    continue

    # Fire-and-forget Peaje with collected text
    full_response = "".join(collected_text)
    if full_response and last_user_msg:
        _schedule_peaje(tenant, completion_id, f"direct:{request.model}", last_user_msg, full_response)


# ═══════════════════════════════════════════════════════════════
# PEAJE FLYWHEEL INTEGRATION
# ═══════════════════════════════════════════════════════════════

def _schedule_peaje(tenant: str, session_id: str, agent_id: str, user_msg: str, response: str):
    """Schedule Peaje auto-ingest as fire-and-forget background task."""
    try:
        # Only ingest meaningful conversations
        if len(user_msg) < 10 and len(response) < 30:
            return

        messages = [PeajeChatMessage(role="user", content=user_msg)]

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(
                process_auto_ingest(tenant, session_id, agent_id, messages, response)
            )
        else:
            asyncio.run(
                process_auto_ingest(tenant, session_id, agent_id, messages, response)
            )
        print(f"[PEAJE] Scheduled auto-ingest: tenant={tenant}, agent={agent_id}")
    except Exception as e:
        # Never let Peaje errors break the chat flow
        print(f"[PEAJE ERROR] Failed to schedule: {e}")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _make_chunk(
    completion_id: str,
    created: int,
    delta: Dict[str, Any],
    finish_reason: Optional[str] = None,
) -> dict:
    """Build a single ChatCompletionChunk object."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "cerebro-core",
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
        "system_fingerprint": "shift-proxy",
    }
