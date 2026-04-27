"""
Agent invocation HTTP surface.

Two endpoints, both designed to be product-agnostic so future
verticals (Sentinel, Studio, etc.) drop their agents into
`agents/skills/` and get a working HTTP handle for free:

    POST /v1/agents/{agent_id}/invoke
        Calls a registered agent (skill_prompt as system) with the
        caller's `input` payload as the user message. Returns the
        parsed JSON output (most agents emit JSON) or raw text.

    POST /v1/llm/invoke
        Generic LLM call — no agent persona attached. Used by
        callers that have their own system prompt (e.g. Eco's
        sentiment scorer, Sentinel's content generator).

Both endpoints accept a `tenant` field that gets stamped onto the
trace label so cost telemetry can split by product. Agents that
need tenant-aware behavior can read it from the prompt body.

Forward-compat note for the Sentinel roster: when Sentinel adds
e.g. `social-listener.yaml`, `news-extractor.yaml`,
`content-drafter.yaml` to `agents/skills/`, they auto-register and
become callable via this same endpoint. No router changes needed.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.registry import AGENTS
from config.models import get_llm

router = APIRouter()


class InvokeAgentBody(BaseModel):
    # Most callers (Eco worker, future Sentinel jobs) pass a
    # structured object the agent's skill_prompt knows how to read.
    # We don't validate the shape — that's the agent's responsibility.
    input: Any = Field(..., description="Agent-specific input payload")
    tenant: Optional[str] = Field(default=None, description="Product tag for telemetry (eco, cl2, sentinel, ...)")
    model_override: Optional[str] = Field(default=None, description="OpenRouter model id; falls back to agent default")
    max_tokens: Optional[int] = Field(default=None, description="Per-call cap; defaults to 1500")
    temperature: Optional[float] = Field(default=None, description="0..1; defaults to 0.1 for extractors")
    trace_label: Optional[str] = Field(default=None, description="Free-form telemetry tag")


class InvokeLLMBody(BaseModel):
    # Generic LLM call — caller supplies their own system + prompt.
    # Used when there's no registered agent (one-off scoring, etc.).
    model: str = Field(..., description="OpenRouter model id e.g. 'openai/gpt-4o'")
    prompt: str = Field(..., description="User message")
    system: Optional[str] = Field(default=None, description="System prompt")
    tenant: Optional[str] = Field(default=None)
    max_tokens: Optional[int] = Field(default=None)
    temperature: Optional[float] = Field(default=None)
    trace_label: Optional[str] = Field(default=None)


class InvokeResponse(BaseModel):
    # Loose shape — agents can return JSON-parseable output, plain
    # text, or a list. The caller decides what to do.
    output: Any
    text: str
    usage: Dict[str, Any]
    latency_ms: int
    call_id: str
    model: str
    agent_id: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────────────


# Default model picks. Agent calls use a cheap floor (extraction is
# structured + short); generic LLM calls require explicit model in body.
_DEFAULT_AGENT_MODEL = os.getenv(
    "CEREBRO_AGENT_DEFAULT_MODEL",
    "google/gemini-3.1-flash-lite-preview",
)


def _stringify_input(payload: Any) -> str:
    """Convert the caller's input into a single user-message string."""
    if isinstance(payload, str):
        return payload
    # Agents that consume JSON inputs (geo-classifier, future Sentinel
    # extractors) parse the user message back as JSON. Pretty-print so
    # the model has cleaner tokens.
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _try_parse_json(text: str) -> Any:
    """Best-effort: if the model returned JSON, parse it. Strip code
    fences first since some models wrap JSON in ```json ... ```."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (with optional language tag) and
        # everything after the trailing fence.
        first_nl = cleaned.find("\n")
        if first_nl >= 0:
            cleaned = cleaned[first_nl + 1 :]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def _build_messages(system: Optional[str], user: str) -> list:
    """LangChain-compatible message list (works with ChatOpenAI)."""
    from langchain_core.messages import SystemMessage, HumanMessage

    msgs = []
    if system:
        msgs.append(SystemMessage(content=system))
    msgs.append(HumanMessage(content=user))
    return msgs


def _usage_from_result(result: Any) -> Dict[str, Any]:
    """ChatOpenAI returns AIMessage with .response_metadata holding
    token usage. Shape varies by adapter; pull what we can."""
    meta = getattr(result, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return {
        "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
        "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens") or 0,
        "total_tokens": usage.get("total_tokens") or 0,
    }


# ─── Routes ─────────────────────────────────────────────────────────


@router.post("/v1/agents/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke_agent(agent_id: str, body: InvokeAgentBody) -> InvokeResponse:
    """Invoke a registered agent. The agent's `skill_prompt` is the
    system message; the caller's `input` is the user message."""
    info = AGENTS.get(agent_id)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "agent_not_found",
                "agent_id": agent_id,
                "available": sorted(AGENTS.keys()),
            },
        )

    system_prompt: str = info.get("skill", "") or ""
    user_message = _stringify_input(body.input)

    model_name = body.model_override or _DEFAULT_AGENT_MODEL
    llm = get_llm(model_name)
    if body.max_tokens is not None:
        llm.max_tokens = int(body.max_tokens)
    if body.temperature is not None:
        llm.temperature = float(body.temperature)

    t0 = time.time()
    msgs = _build_messages(system_prompt, user_message)
    try:
        result = await llm.ainvoke(msgs)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "upstream_failed", "message": str(e)[:500]},
        ) from e
    latency_ms = int((time.time() - t0) * 1000)

    text = getattr(result, "content", "") or ""
    parsed = _try_parse_json(text)

    return InvokeResponse(
        output=parsed if parsed is not None else text,
        text=text,
        usage=_usage_from_result(result),
        latency_ms=latency_ms,
        call_id=str(uuid.uuid4()),
        model=model_name,
        agent_id=agent_id,
    )


@router.post("/v1/llm/invoke", response_model=InvokeResponse)
async def invoke_llm(body: InvokeLLMBody) -> InvokeResponse:
    """Generic LLM call. No agent persona — caller owns the system
    prompt. Used by Eco's sentiment scorer, Sentinel content drafts,
    one-off classification jobs, etc."""
    llm = get_llm(body.model)
    if body.max_tokens is not None:
        llm.max_tokens = int(body.max_tokens)
    if body.temperature is not None:
        llm.temperature = float(body.temperature)

    t0 = time.time()
    msgs = _build_messages(body.system, body.prompt)
    try:
        result = await llm.ainvoke(msgs)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "upstream_failed", "message": str(e)[:500]},
        ) from e
    latency_ms = int((time.time() - t0) * 1000)

    text = getattr(result, "content", "") or ""
    parsed = _try_parse_json(text)

    return InvokeResponse(
        output=parsed if parsed is not None else text,
        text=text,
        usage=_usage_from_result(result),
        latency_ms=latency_ms,
        call_id=str(uuid.uuid4()),
        model=body.model,
        agent_id=None,
    )


@router.get("/v1/agents")
async def list_agents() -> Dict[str, Any]:
    """List of registered agents — for debugging + future Sentinel
    discovery UI ("which agents does this Cerebro know about?")."""
    return {
        "ok": True,
        "agents": [
            {
                "id": aid,
                "name": info.get("name"),
                "role": info.get("role"),
                "version": info.get("version"),
                "pod": info.get("pod"),
                "pod_name": info.get("pod_name"),
                "keywords": info.get("keywords", []),
            }
            for aid, info in sorted(AGENTS.items())
        ],
        "count": len(AGENTS),
    }
