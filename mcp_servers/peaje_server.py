"""cerebro-mcp-peaje — MCP Server exposing the data flywheel as portable tools.
Tools: ingest_insight, query_punto_medio, get_tenant_context

This server makes the Peaje/Punto Medio flywheel available to external MCP clients
(Claude Desktop, n8n, Slack bots, etc.) without coupling them to the FastAPI layer.

Run standalone: python -m mcp_servers.peaje_server
"""
import os
import sys
import json
import hashlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("cerebro-mcp-peaje")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="ingest_insight",
            description="Ingest an insight into the Peaje flywheel. Extracts actionable intelligence from a conversation snippet, scrubs PII, validates taxonomy, and stores in the knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "description": "Tenant ID for multi-tenant isolation"},
                    "conversation_text": {"type": "string", "description": "The conversation text to extract insights from"},
                    "agent_id": {"type": "string", "description": "ID of the agent that generated the content", "default": "external"},
                    "session_id": {"type": "string", "description": "Session identifier for grouping"},
                    "source": {"type": "string", "description": "Source of the insight (mcp_client, slack, n8n, etc.)", "default": "mcp_client"}
                },
                "required": ["tenant_id", "conversation_text"]
            }
        ),
        Tool(
            name="query_punto_medio",
            description="Query the Punto Medio knowledge base — returns the dynamic RAG context that gets injected into agent system prompts. Shows what the AI 'knows' about a tenant.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "description": "Tenant ID to query RAG for"},
                    "scope": {"type": "string", "enum": ["global", "tenant", "patterns", "combined"], "default": "combined"}
                },
                "required": ["tenant_id"]
            }
        ),
        Tool(
            name="get_tenant_context",
            description="Get the Tenant Constitution context — the corporate identity, mission, and operational rules for a specific tenant.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "description": "Tenant ID to get context for"}
                },
                "required": ["tenant_id"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    from config.database import get_db_connection
    
    if name == "ingest_insight":
        try:
            from peaje.extractor import extract_insight_data_async
            from pii_scrubber import full_scrub_pipeline
            from graph.state import ChatMessage
            
            tenant_id = arguments["tenant_id"]
            conversation_text = arguments["conversation_text"]
            agent_id = arguments.get("agent_id", "external")
            session_id = arguments.get("session_id", f"mcp_{int(datetime.now().timestamp())}")
            source = arguments.get("source", "mcp_client")
            
            # Create synthetic messages for the extractor
            messages = [ChatMessage(role="user", content=conversation_text)]
            
            # Extract insight
            insight_data = await extract_insight_data_async(messages, conversation_text, tenant_id)
            
            # PII scrub
            scrub_result = full_scrub_pipeline(
                insight_text=insight_data["insight_text"],
                raw_category=insight_data["category"],
                conversation_text=conversation_text,
            )
            
            # Store
            conn = get_db_connection()
            if conn:
                try:
                    anonymized_hash = hashlib.sha256(f"{tenant_id}:{session_id}:{datetime.now().isoformat()}".encode()).hexdigest()
                    conversation_hash = hashlib.sha256(conversation_text.encode()).hexdigest()
                    
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO peaje_insights 
                            (tenant_id, session_id, agent_id, insight_text, 
                             category, sub_category, industry_vertical,
                             sentiment, confidence_score, extraction_model, pii_scrubbed,
                             source_type, anonymized_hash, raw_conversation_hash)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            tenant_id, session_id, agent_id,
                            scrub_result["scrubbed_text"],
                            scrub_result["validated_category"],
                            scrub_result["sub_category"],
                            scrub_result["industry_vertical"],
                            insight_data["sentiment"],
                            insight_data["confidence_score"],
                            "moonshotai/kimi-k2.6",
                            scrub_result["pii_scrubbed"],
                            source,
                            anonymized_hash,
                            conversation_hash,
                        ))
                        insight_id = cursor.lastrowid
                    conn.commit()
                    
                    result = json.dumps({
                        "status": "ingested",
                        "insight_id": insight_id,
                        "category": scrub_result["validated_category"],
                        "sentiment": insight_data["sentiment"],
                        "pii_items_removed": scrub_result["total_pii_scrubbed"],
                    })
                    return [TextContent(type="text", text=result)]
                finally:
                    conn.close()
            else:
                return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Database not available"}))]
                
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": str(e)}))]
    
    elif name == "query_punto_medio":
        try:
            from punto_medio import get_dynamic_rag
            
            tenant_id = arguments["tenant_id"]
            scope = arguments.get("scope", "combined")
            
            conn = get_db_connection()
            rag = get_dynamic_rag(conn, tenant_id)
            if conn:
                conn.close()
            
            if scope == "combined":
                text = rag["combined_rag"]
            elif scope == "global":
                text = rag["global_rag"]
            elif scope == "tenant":
                text = rag["tenant_rag"]
            elif scope == "patterns":
                text = rag["patterns_rag"]
            else:
                text = rag["combined_rag"]
            
            result = json.dumps({
                "tenant_id": tenant_id,
                "scope": scope,
                "content_length": len(text),
                "content": text,
            })
            return [TextContent(type="text", text=result)]
            
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": str(e)}))]
    
    elif name == "get_tenant_context":
        try:
            from tenant_constitution import get_tenant_context_with_fallback
            
            tenant_id = arguments["tenant_id"]
            conn = get_db_connection()
            context = get_tenant_context_with_fallback(conn, tenant_id)
            if conn:
                conn.close()
            
            result = json.dumps({
                "tenant_id": tenant_id,
                "context_length": len(context),
                "context": context,
            })
            return [TextContent(type="text", text=result)]
            
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": str(e)}))]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    
    asyncio.run(main())
