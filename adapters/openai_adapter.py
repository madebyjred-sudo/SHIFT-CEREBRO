"""OpenAI-Compatible Adapter — /adapter/v1/chat/completions and /adapter/v1/models

Wraps Cerebro.run() in the standard OpenAI ChatCompletion API shape so that
LobeChat (or any OpenAI-compatible client) can talk to Cerebro directly.

Mounts at prefix /adapter/v1 on the main FastAPI app.
"""
import json
import time
import uuid
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from agents.registry import AGENTS
from cerebro.sdk import Cerebro, CerebroResponse

openai_router = APIRouter(prefix="/adapter/v1", tags=["openai-compat"])

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
    stream: bool = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    tenant_id: Optional[str] = "shift"


# ═══════════════════════════════════════════════════════════════
# GET /adapter/v1/models
# ═══════════════════════════════════════════════════════════════

@openai_router.get("/models")
async def list_models():
    """Return available models in OpenAI /v1/models shape."""
    return {
        "object": "list",
        "data": [
            {
                "id": "cerebro-core",
                "object": "model",
                "created": 1700000000,
                "owned_by": "shift-lab",
                "permission": [],
                "root": "cerebro-core",
                "parent": None,
            }
        ],
    }


# ═══════════════════════════════════════════════════════════════
# POST /adapter/v1/chat/completions
# ═══════════════════════════════════════════════════════════════

@openai_router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint wrapping Cerebro.run().

    Supports both streaming (SSE) and non-streaming responses.
    """
    # Extract last user message
    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")

    last_user_msg = user_messages[-1].content
    tenant = request.tenant_id or "shift"
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if request.stream:
        return StreamingResponse(
            _stream_response(last_user_msg, tenant, completion_id, created),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _sync_response(last_user_msg, tenant, completion_id, created)


# ═══════════════════════════════════════════════════════════════
# NON-STREAMING RESPONSE
# ═══════════════════════════════════════════════════════════════

async def _sync_response(
    query: str, tenant: str, completion_id: str, created: int
) -> JSONResponse:
    """Run Cerebro synchronously and return a full ChatCompletion object."""
    try:
        cerebro = Cerebro(tenant=tenant)
        response: CerebroResponse = cerebro.run(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cerebro error: {str(e)}")

    agent_used = response.agent_used
    agent_name = AGENTS.get(agent_used, {}).get("name", agent_used)
    text = response.text

    return JSONResponse(content={
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": "cerebro-core",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(query.split()),
            "completion_tokens": len(text.split()),
            "total_tokens": len(query.split()) + len(text.split()),
        },
        "system_fingerprint": f"cerebro-{agent_used}",
    })


# ═══════════════════════════════════════════════════════════════
# STREAMING RESPONSE (SSE)
# ═══════════════════════════════════════════════════════════════

async def _stream_response(
    query: str, tenant: str, completion_id: str, created: int
):
    """Stream Cerebro response as OpenAI ChatCompletionChunks via SSE.

    Strategy:
    1. Emit tool_call chunks for each agent in the execution plan (shows
       "calling carmen / roberto / ..." in LobeChat UI)
    2. Run Cerebro.run() to get the final synthesis
    3. Stream the final text in ~200 char chunks with small delays
    4. Emit a final chunk with finish_reason="stop"
    """
    try:
        cerebro = Cerebro(tenant=tenant)

        # ── Phase 1: Emit tool_call chunks for visual feedback ──
        # Route first to get execution plan (reuse Cerebro's routing)
        from graph.router import route_with_llm, determine_agent_from_message
        try:
            route_result = await route_with_llm(query)
            plan = route_result.get("execution_plan", [route_result.get("agent_id", "shiftai")])
        except Exception:
            plan = [determine_agent_from_message(query)]

        for idx, agent_id in enumerate(plan):
            agent_name = AGENTS.get(agent_id, {}).get("name", agent_id)
            agent_role = AGENTS.get(agent_id, {}).get("role", "Specialist")
            tool_call_chunk = _make_chunk(
                completion_id, created,
                delta={
                    "role": "assistant",
                    "tool_calls": [
                        {
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
                        }
                    ],
                },
            )
            yield f"data: {json.dumps(tool_call_chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.3)

        # ── Phase 2: Run Cerebro (blocks until complete) ──
        response: CerebroResponse = cerebro.run(query)
        text = response.text
        agent_used = response.agent_used

        # ── Phase 3: Stream the final text in chunks ──
        CHUNK_SIZE = 200
        for i in range(0, len(text), CHUNK_SIZE):
            content_piece = text[i : i + CHUNK_SIZE]
            chunk = _make_chunk(
                completion_id, created,
                delta={"content": content_piece},
            )
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.05)

        # ── Phase 4: Final stop chunk ──
        stop_chunk = _make_chunk(
            completion_id, created,
            delta={},
            finish_reason="stop",
        )
        yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_chunk = _make_chunk(
            completion_id, created,
            delta={"content": f"\n\n[Error: {str(e)}]"},
            finish_reason="stop",
        )
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


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
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
        "system_fingerprint": "cerebro-core",
    }
