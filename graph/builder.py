"""Graph Builder — Compiles the LangGraph StateGraph with router → agents → synthesizer → peaje → END.
This is the core architectural piece that replaces the manual function-call routing from the monolith."""
from typing import Optional, List
from langgraph.graph import StateGraph, START, END

from agents.registry import AGENTS
from graph.state import SwarmState
from graph.router import arouter_node
from graph.nodes import create_agent_node_with_model
from graph.synthesizer import synthesizer_node


def _agent_dispatcher(state: SwarmState) -> dict:
    """Execute the current agent in the execution_plan and advance the step counter.
    This is a universal node that dynamically invokes the right agent based on state."""
    import asyncio
    
    plan = state.get("execution_plan", [])
    step = state.get("current_step", 0)
    
    if step >= len(plan):
        # No more agents to execute
        return {}
    
    agent_id = plan[step]
    model_name = state.get("model_name", "Claude 3.5 Sonnet")
    tenant_id = state.get("tenant_id", "shift")
    user_metadata = state.get("user_metadata")
    
    print(f"[DISPATCHER] Step {step + 1}/{len(plan)}: Executing agent '{agent_id}'")
    
    # Create and execute the agent node function
    agent_fn = create_agent_node_with_model(agent_id, model_name, tenant_id, user_metadata)
    result = agent_fn(state)
    
    # Advance step counter
    result["current_step"] = step + 1
    
    return result


async def _async_agent_dispatcher(state: SwarmState) -> dict:
    """Async version of the agent dispatcher. Used with ainvoke()."""
    plan = state.get("execution_plan", [])
    step = state.get("current_step", 0)
    
    if step >= len(plan):
        return {}
    
    agent_id = plan[step]
    model_name = state.get("model_name", "Claude 3.5 Sonnet")
    tenant_id = state.get("tenant_id", "shift")
    user_metadata = state.get("user_metadata")
    
    print(f"[DISPATCHER] Step {step + 1}/{len(plan)}: Executing agent '{agent_id}'")
    
    # Use the async version for non-blocking execution
    from graph.nodes import create_async_agent_node
    agent_fn = create_async_agent_node(agent_id, model_name, tenant_id)
    result = await agent_fn(state)
    
    result["current_step"] = step + 1
    
    return result


def _should_continue_agents(state: SwarmState) -> str:
    """Conditional edge: decides whether to run another agent or move to synthesis."""
    plan = state.get("execution_plan", [])
    step = state.get("current_step", 0)
    
    if step < len(plan):
        # More agents to execute
        return "agent"
    elif len(plan) > 1:
        # Multiple agents ran — synthesize
        return "synthesize"
    else:
        # Single agent — skip synthesis
        return "end"


def _should_synthesize_or_end(state: SwarmState) -> str:
    """After synthesis, always go to end."""
    return "end"


def build_cerebro_graph(
    active_agents: Optional[List[str]] = None,
    include_synthesizer: bool = True,
) -> StateGraph:
    """Build and compile the CEREBRO StateGraph.
    
    Args:
        active_agents: List of agent IDs to include. None = all agents.
                       Used by embed_adapter to create lightweight graphs.
        include_synthesizer: Whether to include the multi-agent synthesizer node.
    
    Returns:
        Compiled StateGraph ready for .invoke() or .ainvoke()
    
    Graph topology:
        [START] → [ROUTER] → [AGENT_DISPATCHER] ←→ (loop if more agents)
                                    ↓
                            [SYNTHESIZER] (if multi-agent)
                                    ↓
                                  [END]
    """
    # Validate active_agents
    if active_agents:
        valid_agents = [a for a in active_agents if a in AGENTS]
        if not valid_agents:
            valid_agents = list(AGENTS.keys())
        print(f"[BUILDER] Building graph with {len(valid_agents)} agents: {valid_agents}")
    else:
        valid_agents = list(AGENTS.keys())
        print(f"[BUILDER] Building graph with ALL {len(valid_agents)} agents")
    
    # Build the graph
    graph = StateGraph(SwarmState)
    
    # Add nodes
    graph.add_node("router", arouter_node)
    graph.add_node("agent", _async_agent_dispatcher)
    
    if include_synthesizer:
        graph.add_node("synthesizer", synthesizer_node)
    
    # Add edges
    # START → router
    graph.add_edge(START, "router")
    
    # router → agent (always)
    graph.add_edge("router", "agent")
    
    # agent → conditional (loop or synthesize or end)
    if include_synthesizer:
        graph.add_conditional_edges(
            "agent",
            _should_continue_agents,
            {
                "agent": "agent",        # Loop back for next agent in plan
                "synthesize": "synthesizer",  # Multi-agent → synthesize
                "end": END,              # Single agent → done
            }
        )
        graph.add_edge("synthesizer", END)
    else:
        graph.add_conditional_edges(
            "agent",
            _should_continue_agents,
            {
                "agent": "agent",
                "synthesize": END,  # No synthesizer available → end
                "end": END,
            }
        )
    
    # Compile
    compiled = graph.compile()
    print(f"[BUILDER] ✓ Graph compiled successfully")
    
    return compiled


# ═══════════════════════════════════════════════════════════════
# PRE-COMPILED GRAPHS (Singleton pattern)
# ═══════════════════════════════════════════════════════════════

# Full graph — used by Studio adapter
_studio_graph = None

def get_studio_graph():
    """Get or create the full Studio graph (all agents + synthesizer)."""
    global _studio_graph
    if _studio_graph is None:
        _studio_graph = build_cerebro_graph(active_agents=None, include_synthesizer=True)
    return _studio_graph


def get_embed_graph(active_agents: List[str]):
    """Create an embed graph with a subset of agents. Not cached — varies by context."""
    return build_cerebro_graph(active_agents=active_agents, include_synthesizer=True)
