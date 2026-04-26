"""
Anthropic-via-OpenRouter adapter for LightRAG.

LightRAG accepts an async callable for the LLM: given a prompt string +
optional system message, return the LLM's text. We wrap the existing
Cerebro `get_llm()` which already routes through OpenRouter (so model
swaps in MODEL_MAP propagate without changes here).

Two distinct LLM uses inside LightRAG:
  - Build-time:  entity + relation extraction per chunk. Volume-heavy
                 (one call per chunk × ~1.5M chunks). Use Haiku 4.5 —
                 cheap, fast, JSON-strict enough.
  - Query-time:  graph traversal + answer synthesis. Quality-sensitive,
                 lower volume. Use Sonnet 4.6 (or Opus when the user
                 enables `deep_insight`). Selected via env var
                 LIGHTRAG_QUERY_MODEL.

Both share the same adapter — just different `model` parameter at the
call site. LightRAG's `gpt_4o_mini_complete`-style helpers expect a
specific signature; we mirror it.
"""
import os
from typing import Optional


BUILD_MODEL = os.getenv(
    "LIGHTRAG_BUILD_MODEL",
    "anthropic/claude-haiku-4.5",
)
QUERY_MODEL = os.getenv(
    "LIGHTRAG_QUERY_MODEL",
    "anthropic/claude-sonnet-4.6",
)


def _select_model(deep_insight: bool, override: Optional[str]) -> str:
    if override:
        return override
    if deep_insight:
        return os.getenv("LIGHTRAG_DEEP_MODEL", "anthropic/claude-opus-4.7")
    return QUERY_MODEL


async def lightrag_complete(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[list[dict]] = None,
    *,
    mode: str = "query",            # "build" | "query"
    deep_insight: bool = False,
    model_override: Optional[str] = None,
    **kwargs,
) -> str:
    """LightRAG-compatible async completion function.

    Mirrors the upstream `*_complete` helpers' signature so LightRAG's
    internals can call us without adapters on top.
    """
    # Lazy import — keeps the package optional at import time.
    from langchain_core.messages import (  # type: ignore
        HumanMessage,
        SystemMessage,
        AIMessage,
    )
    from config.models import get_llm

    chosen = (
        BUILD_MODEL
        if mode == "build"
        else _select_model(deep_insight, model_override)
    )
    llm = get_llm(chosen)

    messages: list = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    for h in history_messages or []:
        role = h.get("role")
        content = h.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
    messages.append(HumanMessage(content=prompt))

    response = await llm.ainvoke(messages)
    return getattr(response, "content", str(response))


# LightRAG sometimes calls a `*_mini_complete` for cheap extractions and
# a `*_complete` for full responses. We expose both names mapped to the
# same adapter, with mode pre-bound so callers don't have to thread it.
async def lightrag_build_complete(prompt: str, system_prompt: Optional[str] = None, **kw) -> str:
    return await lightrag_complete(prompt, system_prompt=system_prompt, mode="build", **kw)


async def lightrag_query_complete(prompt: str, system_prompt: Optional[str] = None, **kw) -> str:
    return await lightrag_complete(prompt, system_prompt=system_prompt, mode="query", **kw)
