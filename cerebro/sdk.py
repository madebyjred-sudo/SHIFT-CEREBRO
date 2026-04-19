"""Cerebro SDK — In-process Python interface to the CEREBRO multi-agent graph.

Runs the full LangGraph StateGraph in-process (no HTTP, no FastAPI, no server).
Designed to be demo-ready in 3 lines:

    from cerebro import Cerebro
    c = Cerebro(tenant="shift")
    response = c.run("¿Cuánto vendimos este mes?")
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from agents.registry import AGENTS
from graph.builder import build_cerebro_graph
from graph.router import route_with_llm, determine_agent_from_message
from graph.state import SwarmState


# ═══════════════════════════════════════════════════════════════
# CerebroResponse (B14)
# ═══════════════════════════════════════════════════════════════

@dataclass
class CerebroResponse:
    """Structured response from a Cerebro.run() invocation.

    Attributes:
        text:       Final assistant text (post-synthesis if multi-agent).
        agent_used: ID of the primary agent that answered.
        tool_calls: List of tool call dicts (empty until tool-call tracking is wired).
        citations:  List of citation dicts (empty until citation tracking is wired).
        session_id: Session identifier used for this invocation.
        metadata:   Dict with routing details, execution plan, timing, etc.
    """
    text: str
    agent_used: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Cerebro (B12)
# ═══════════════════════════════════════════════════════════════

class Cerebro:
    """In-process SDK for the CEREBRO multi-agent system.

    Args:
        tenant:       Tenant slug (e.g. "shift", "garnier").
        agents:       Optional list of agent IDs to activate. None = all 15.
        tool_domains: Optional list forwarded for future pod-based tool filtering.
        model:        LLM model name passed to the graph dispatchers.
        **kwargs:     Reserved for future options (logging, callbacks, etc.).
    """

    def __init__(
        self,
        tenant: str,
        agents: Optional[List[str]] = None,
        tool_domains: Optional[List[str]] = None,
        model: str = "Claude 3.5 Sonnet",
        **kwargs: Any,
    ) -> None:
        self._tenant = tenant
        self._model = model
        self._tool_domains = tool_domains or []
        self._observers: List[Callable] = []
        self._extra = kwargs

        # Validate and resolve agent list
        if agents is not None:
            valid = [a for a in agents if a in AGENTS]
            if not valid:
                print(f"[CEREBRO SDK] WARN: none of {agents} found in registry, falling back to all agents")
                valid = list(AGENTS.keys())
            self._agents = valid
        else:
            self._agents = list(AGENTS.keys())

        # Compile the graph once at init time
        self._graph = build_cerebro_graph(
            active_agents=self._agents,
            include_synthesizer=True,
        )

    # ───────────────────────────────────────────────────────────
    # Public API
    # ───────────────────────────────────────────────────────────

    @property
    def available_agents(self) -> List[str]:
        """List of agent IDs enabled for this Cerebro instance."""
        return list(self._agents)

    def run(
        self,
        query: str,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> CerebroResponse:
        """Execute a query through the full CEREBRO graph (sync wrapper).

        Args:
            query:      Natural-language user query.
            session_id: Optional session ID for peaje tracking. Auto-generated if omitted.
            **kwargs:   Forwarded to the graph invocation.

        Returns:
            CerebroResponse with the final text, agent used, and metadata.

        Raises:
            Exception: If the LLM provider is unreachable or misconfigured.
                       This is expected in environments without API keys.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an async context (e.g. Jupyter, FastAPI)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._arun(query, session_id, **kwargs))
                return future.result()
        else:
            return asyncio.run(self._arun(query, session_id, **kwargs))

    def configure(self, **kwargs: Any) -> None:
        """Update SDK parameters post-init without recreating the instance.

        Supported keys:
            tool_domains: List[str] — update pod-based tool filtering
            model: str — change the LLM model for subsequent runs
        """
        if "tool_domains" in kwargs:
            self._tool_domains = kwargs["tool_domains"]
        if "model" in kwargs:
            self._model = kwargs["model"]

    def observe(self, callback: Callable) -> None:
        """Register an observer callback for graph events (nice-to-have).

        The callback will receive event dicts as the graph executes.
        Currently a no-op placeholder; will be wired when streaming is added.
        """
        self._observers.append(callback)

    # ───────────────────────────────────────────────────────────
    # Internal
    # ───────────────────────────────────────────────────────────

    async def _arun(
        self,
        query: str,
        session_id: Optional[str] = None,
        **kwargs: Any,
    ) -> CerebroResponse:
        """Async core of run(). Routes, builds state, invokes graph."""
        t0 = time.time()
        safe_session_id = session_id or f"sdk_{int(t0)}"

        # ── Route ──
        try:
            route_result = await route_with_llm(query)
            agent_id = route_result["agent_id"]
            # Constrain to available agents
            if agent_id not in self._agents:
                agent_id = self._agents[0]
            plan = [a for a in route_result["execution_plan"] if a in self._agents]
            if not plan:
                plan = [agent_id]
            router_reasoning = route_result["reasoning"]
            router_confidence = route_result["confidence"]
        except Exception:
            agent_id = determine_agent_from_message(query)
            if agent_id not in self._agents:
                agent_id = self._agents[0]
            plan = [agent_id]
            router_reasoning = f"Keyword fallback: {agent_id}"
            router_confidence = 0.3

        # ── Build initial state ──
        initial_state: SwarmState = {
            "messages": [HumanMessage(content=query)],
            "context": "",
            "active_agent": agent_id,
            "agent_outputs": {},
            "execution_plan": plan,
            "current_step": 0,
            "model_name": self._model,
            "tenant_id": self._tenant,
            "user_metadata": kwargs.get("user_metadata"),
            "router_reasoning": router_reasoning,
            "router_confidence": router_confidence,
            "session_id": safe_session_id,
        }

        # ── Invoke graph ──
        result_state = await self._graph.ainvoke(initial_state)

        # ── Map result → CerebroResponse ──
        final_messages = result_state.get("messages", [])
        text = ""
        if final_messages:
            last = final_messages[-1]
            text = last.content if hasattr(last, "content") else str(last)

        final_agent = result_state.get("active_agent", agent_id)
        elapsed = round(time.time() - t0, 2)

        return CerebroResponse(
            text=text,
            agent_used=final_agent,
            tool_calls=[],       # TODO: wire tool call tracking from agent nodes
            citations=[],        # TODO: wire citation extraction
            session_id=safe_session_id,
            metadata={
                "router_reasoning": result_state.get("router_reasoning", router_reasoning),
                "router_confidence": result_state.get("router_confidence", router_confidence),
                "execution_plan": result_state.get("execution_plan", plan),
                "elapsed_seconds": elapsed,
                "model": self._model,
                "tenant": self._tenant,
            },
        )

    def __repr__(self) -> str:
        return (
            f"Cerebro(tenant={self._tenant!r}, "
            f"agents={len(self._agents)}, "
            f"model={self._model!r})"
        )
