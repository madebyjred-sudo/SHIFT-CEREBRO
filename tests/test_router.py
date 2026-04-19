import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from graph.router import arouter_node

# Group 1 — Happy path por pod (4 tests)
@pytest.mark.asyncio
async def test_router_happy_ventas_query():
    # Simulate LLM returning 'roberto'
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "roberto",
            "execution_plan": ["roberto"],
            "confidence": 0.9,
            "reasoning": "Ventas/Finanzas pod"
        }
        
        state = {"messages": [type('Msg', (), {'content': "¿Cuánto vendimos este mes?"})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "roberto"

@pytest.mark.asyncio
async def test_router_happy_operaciones_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "patricia",
            "execution_plan": ["patricia"],
            "confidence": 0.9,
            "reasoning": "Operaciones pod"
        }
        
        state = {"messages": [type('Msg', (), {'content': "Necesito agendar una cita"})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "patricia"

@pytest.mark.asyncio
async def test_router_happy_finanzas_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "roberto",
            "execution_plan": ["roberto"],
            "confidence": 0.9,
            "reasoning": "Finanzas pod"
        }
        
        state = {"messages": [type('Msg', (), {'content': "Pasame el reporte financiero de Q1"})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "roberto"

@pytest.mark.asyncio
async def test_router_happy_culturalider_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "carmen",
            "execution_plan": ["carmen"],
            "confidence": 0.9,
            "reasoning": "Cultura y Liderazgo"
        }
        
        state = {"messages": [type('Msg', (), {'content': "Cómo manejo un conflicto con mi equipo?"})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "carmen"

# Group 2 — Edge cases (8 tests)
@pytest.mark.asyncio
async def test_router_edge_empty_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["shiftai"],
            "confidence": 0.2,
            "reasoning": "Empty"
        }
        
        state = {"messages": [type('Msg', (), {'content': ""})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "shiftai"

@pytest.mark.asyncio
async def test_router_edge_ambiguous_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["roberto", "patricia"],
            "confidence": 0.6,
            "reasoning": "Ambiguous cross domain"
        }
        
        state = {"messages": [type('Msg', (), {'content': "Hacer plan de marketing y revisar legalidad"})()]}
        result = await arouter_node(state)
        
        assert result["active_agent"] == "shiftai"
        assert result["execution_plan"] == ["roberto", "patricia"]

@pytest.mark.asyncio
async def test_router_edge_english_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "roberto",
            "execution_plan": ["roberto"],
            "confidence": 0.9,
            "reasoning": "English query"
        }
        state = {"messages": [type('Msg', (), {'content': "Give me the ROI"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "roberto"

@pytest.mark.asyncio
async def test_router_edge_pii_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "patricia",
            "execution_plan": ["patricia"],
            "confidence": 0.9,
            "reasoning": "PII query"
        }
        state = {"messages": [type('Msg', (), {'content': "Llama a 555-1234"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "patricia"

@pytest.mark.asyncio
async def test_router_edge_long_query():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["shiftai"],
            "confidence": 0.5,
            "reasoning": "Long query"
        }
        state = {"messages": [type('Msg', (), {'content': "a" * 3000})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "shiftai"

@pytest.mark.asyncio
async def test_router_edge_special_chars():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["shiftai"],
            "confidence": 0.8,
            "reasoning": "Special chars"
        }
        state = {"messages": [type('Msg', (), {'content': "🚀🎉!!"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "shiftai"

@pytest.mark.asyncio
async def test_router_edge_history():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "roberto",
            "execution_plan": ["roberto"],
            "confidence": 0.9,
            "reasoning": "History query"
        }
        state = {
            "messages": [
                type('Msg', (), {'content': "Hola"})(),
                type('Msg', (), {'content': "Ventas del mes"})()
            ]
        }
        result = await arouter_node(state)
        assert result["active_agent"] == "roberto"

@pytest.mark.asyncio
async def test_router_edge_no_messages():
    # If no messages, it defaults to empty string or throws
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["shiftai"],
            "confidence": 0.1,
            "reasoning": "No messages"
        }
        state = {"messages": []}
        result = await arouter_node(state)
        assert result["active_agent"] == "shiftai"

# Group 3 — Agent-specific routing (6 tests)
@pytest.mark.asyncio
async def test_router_agent_shiftai():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "shiftai", "execution_plan": ["shiftai"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "Soy nuevo ayúdame"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "shiftai"

@pytest.mark.asyncio
async def test_router_agent_roberto():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "roberto", "execution_plan": ["roberto"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "Finanzas"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "roberto"

@pytest.mark.asyncio
async def test_router_agent_patricia():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "patricia", "execution_plan": ["patricia"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "Legal"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "patricia"

@pytest.mark.asyncio
async def test_router_agent_carmen():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "carmen", "execution_plan": ["carmen"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "Estrategia"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "carmen"

@pytest.mark.asyncio
async def test_router_agent_andres():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "andres", "execution_plan": ["andres"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "Datos y analytics"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "andres"

@pytest.mark.asyncio
async def test_router_agent_lucia():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"agent_id": "lucia", "execution_plan": ["lucia"], "confidence": 1.0, "reasoning": ""}
        state = {"messages": [type('Msg', (), {'content': "SEO"})()]}
        result = await arouter_node(state)
        assert result["active_agent"] == "lucia"

# Group 4 — No-crash smoke (2 tests)
def test_router_importable():
    # We already imported it at the top, just a dummy check
    assert arouter_node is not None

@pytest.mark.asyncio
async def test_router_returns_expected_keys():
    with patch('graph.router.route_with_llm', new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {
            "agent_id": "shiftai",
            "execution_plan": ["shiftai"],
            "confidence": 0.5,
            "reasoning": "Smoke"
        }
        state = {"messages": [type('Msg', (), {'content': "Test keys"})()]}
        result = await arouter_node(state)
        assert "execution_plan" in result
        assert "active_agent" in result
        assert "router_reasoning" in result
        assert "router_confidence" in result
