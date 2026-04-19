"""Pod-based tool filtering for Cerebro agents.

Pods (fuente: agents/skills/*.yaml field `pod`):
  1 = C-Suite & Estrategia
  2 = Marketing & Contenido
  3 = Data & Inteligencia
  4 = Operaciones & Governance

Los tools se identifican por referencia a la función decorada con @tool,
no por string. Esta módulo importa desde graph.nodes (para system tools)
y desde tools (para ALL_TOOLS) y arma el mapping.
"""
from typing import Dict, List, Any, Optional


# Mapping por pod ID (int). Valores son listas de NOMBRES de tools (strings) —
# la resolución a objetos @tool la hace get_tools_for_agent() usando el
# catálogo importado. Si el pod no está en el dict, el agente recibe solo
# READ_ONLY_TOOLS.
POD_TOOL_MAP: Dict[int, List[str]] = {
    1: [  # C-Suite & Estrategia — lectura + escritura + análisis
        "read_file_tool",
        "write_file_tool",
        "search_code_tool",
        "generate_structured_document",
        "create_presentation",
    ],
    2: [  # Marketing & Contenido — generación docs + lectura
        "read_file_tool",
        "write_file_tool",
        "search_code_tool",
        "create_word_document",
        "create_brief_document",
        "generate_pdf_report",
        "generate_marketing_image",
        "analyze_content_sentiment",
        "generate_campaign_qr",
        "generate_keyword_cloud",
    ],
    3: [  # Data & Inteligencia — lectura + análisis (NO escritura directa)
        "read_file_tool",
        "search_code_tool",
        "analyze_data_table",
        "create_chart_visualization",
    ],
    4: [  # Operaciones & Governance — lectura + ejecución controlada
        "read_file_tool",
        "search_code_tool",
        "execute_command_tool",
        "create_meeting_minutes",
    ],
}

# Tools que TODO agente puede usar sin importar pod. Son los "seguros" por default.
READ_ONLY_TOOLS: List[str] = [
    "read_file_tool",
    "search_code_tool",
]


def get_tools_for_agent(
    agent_id: str,
    agent_info: Dict[str, Any],
    read_only: bool = False,
    tool_catalog: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    """Retorna lista de tools (objetos @tool) para el agente dado.

    Args:
        agent_id: id del agente (para logging / telemetría).
        agent_info: dict del registry — debe tener key "pod" (int).
        read_only: si True, retorna solo READ_ONLY_TOOLS (tenant constitution override).
        tool_catalog: dict {tool_name: tool_object} para resolver. Si None,
            el caller debe proveerlo (en nodes.py se arma inline).

    Returns:
        List de objetos tool. Nunca None. Si el agente no tiene pod válido,
        retorna [] y loggea warning.
    """
    if tool_catalog is None:
        raise ValueError(f"[TOOL_MAP] tool_catalog required to resolve tools for {agent_id}")

    if read_only:
        return [tool_catalog[name] for name in READ_ONLY_TOOLS if name in tool_catalog]

    pod = agent_info.get("pod")
    if pod not in POD_TOOL_MAP:
        print(f"[TOOL_MAP] WARN: agent {agent_id} has invalid pod={pod!r}, defaulting to read-only")
        return [tool_catalog[name] for name in READ_ONLY_TOOLS if name in tool_catalog]

    tool_names = POD_TOOL_MAP[pod]
    resolved = []
    for name in tool_names:
        if name in tool_catalog:
            resolved.append(tool_catalog[name])
        else:
            # Warn pero no falla — permite que tool_map tenga nombres aspiracionales
            print(f"[TOOL_MAP] WARN: tool {name!r} not found in catalog for pod {pod}")
    return resolved
