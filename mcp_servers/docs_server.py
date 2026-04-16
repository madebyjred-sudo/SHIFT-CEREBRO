"""cerebro-mcp-docs — MCP Server for document generation (Word, PDF, PPTX).
Tools: create_word_document, create_brief_document, create_meeting_minutes,
       generate_structured_document, generate_pdf_report, create_presentation

Run standalone: python -m mcp_servers.docs_server
"""
import os
import sys

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.types import Tool, TextContent
import json

app = Server("cerebro-mcp-docs")


# ═══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
# ═══════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="create_word_document",
            description="Create a professional Word document (.docx) with formatted content, sections, and styling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Main title of the document"},
                    "content": {"type": "string", "description": "Main content text"},
                    "subtitle": {"type": "string", "description": "Optional subtitle"},
                    "author": {"type": "string", "description": "Document author", "default": "Shift AI"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        },
                        "description": "Optional list of sections"
                    },
                    "filename": {"type": "string", "description": "Optional custom filename (without extension)"}
                },
                "required": ["title", "content"]
            }
        ),
        Tool(
            name="create_brief_document",
            description="Create a structured marketing/creative brief document with predefined sections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"},
                    "objectives": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "key_messages": {"type": "string"},
                    "timeline": {"type": "string"},
                    "budget": {"type": "string"},
                    "author": {"type": "string", "default": "Shift AI"}
                },
                "required": ["project_name", "objectives", "target_audience", "key_messages", "timeline"]
            }
        ),
        Tool(
            name="create_meeting_minutes",
            description="Create professional meeting minutes document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_title": {"type": "string"},
                    "attendees": {"type": "string"},
                    "agenda": {"type": "string"},
                    "discussion_points": {"type": "string"},
                    "action_items": {"type": "string"},
                    "next_steps": {"type": "string"},
                    "author": {"type": "string", "default": "Shift AI"}
                },
                "required": ["meeting_title", "attendees", "agenda", "discussion_points", "action_items", "next_steps"]
            }
        ),
        Tool(
            name="generate_structured_document",
            description="Create a structured document using Unstructured.io processing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "document_type": {"type": "string", "enum": ["report", "memo", "contract", "proposal"], "default": "report"},
                    "title": {"type": "string", "default": "Documento Estructurado"},
                    "metadata": {"type": "object"}
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="generate_pdf_report",
            description="Create a professional PDF report using ReportLab.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "report_type": {"type": "string", "enum": ["general", "financial", "technical", "marketing"], "default": "general"},
                    "sections": {"type": "array", "items": {"type": "object"}},
                    "include_toc": {"type": "boolean", "default": False},
                    "filename": {"type": "string"}
                },
                "required": ["title", "content"]
            }
        ),
        Tool(
            name="create_presentation",
            description="Create a PowerPoint presentation using python-pptx.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "slides_content": {"type": "array", "items": {"type": "object"}},
                    "template": {"type": "string", "enum": ["default", "corporate", "minimal"], "default": "default"},
                    "filename": {"type": "string"}
                },
                "required": ["title"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """Dispatch tool calls to the underlying LangChain tool functions."""
    from tools.document_tools import create_word_document, create_brief_document, create_meeting_minutes
    from tools.extended_tools import generate_structured_document, generate_pdf_report, create_presentation
    
    tool_map = {
        "create_word_document": create_word_document,
        "create_brief_document": create_brief_document,
        "create_meeting_minutes": create_meeting_minutes,
        "generate_structured_document": generate_structured_document,
        "generate_pdf_report": generate_pdf_report,
        "create_presentation": create_presentation,
    }
    
    if name not in tool_map:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    try:
        # Call the LangChain tool's underlying function
        result = tool_map[name].func(**arguments)
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    
    asyncio.run(main())
