"""Peaje Node — Close the insight flywheel from inside the LangGraph.

Fire-and-forget terminal node: invokes process_auto_ingest as async task,
returns state unchanged, does NOT block the response to the user.
"""
import asyncio
from typing import Any, Dict
from graph.state import SwarmState
from peaje.ingest import process_auto_ingest


async def peaje_node(state: SwarmState) -> Dict[str, Any]:
    """Terminal node that fires the Peaje flywheel asynchronously.

    Reads from state:
      - tenant_id (required, fallback "shift")
      - session_id (optional — skip if missing)
      - active_agent (required)
      - messages (required)
      - agent_outputs (dict — last value is the assistant response)

    Returns state unchanged. Any error is soft-logged and swallowed
    so the user response is never blocked or failed by the peaje.
    """
    try:
        tenant_id = state.get("tenant_id", "shift")
        session_id = state.get("session_id")
        agent_id = state.get("active_agent", "unknown")
        messages = state.get("messages", [])
        agent_outputs = state.get("agent_outputs", {}) or {}

        # Skip gracefully if no session_id or no response available
        if not session_id:
            print("[PEAJE_NODE] skip: session_id missing in state")
            return {}
        if not messages or not agent_outputs:
            print("[PEAJE_NODE] skip: messages or agent_outputs empty")
            return {}

        # Extract last assistant response from agent_outputs
        # agent_outputs is Dict[agent_id, output] — pick the most recent
        last_output = list(agent_outputs.values())[-1] if agent_outputs else ""
        response_text = last_output if isinstance(last_output, str) else str(last_output)

        if not response_text or len(response_text) < 20:
            return {}

        # Convert BaseMessage list to ChatMessage list expected by process_auto_ingest
        from graph.state import ChatMessage
        chat_messages = []
        for m in messages:
            role = getattr(m, "type", "user")
            # langchain BaseMessage.type is "human" / "ai" / "system"; map to our ChatMessage roles
            mapped_role = {"human": "user", "ai": "assistant", "system": "system"}.get(role, "user")
            content = getattr(m, "content", "") or ""
            chat_messages.append(ChatMessage(role=mapped_role, content=str(content)))

        # Fire and forget — do NOT await
        asyncio.create_task(process_auto_ingest(
            tenant_id=tenant_id,
            session_id=session_id,
            agent_id=agent_id,
            messages=chat_messages,
            response=response_text,
        ))
        print(f"[PEAJE_NODE] fired for tenant={tenant_id} agent={agent_id}")
    except Exception as e:
        print(f"[PEAJE_NODE] soft-fail: {e}")

    # Node does NOT mutate state
    return {}
