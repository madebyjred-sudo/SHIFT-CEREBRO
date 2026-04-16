"""cerebro-mcp-data — MCP Server for data analytics, charts, sentiment, and keyword cloud.
Tools: analyze_data_table, create_chart_visualization, analyze_content_sentiment, generate_keyword_cloud

Run standalone: python -m mcp_servers.data_server
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("cerebro-mcp-data")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="analyze_data_table",
            description="Analyze tabular data (CSV/JSON/TSV) using Pandas — summary, stats, correlations, trends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Data content (CSV string or JSON)"},
                    "data_format": {"type": "string", "enum": ["csv", "json", "tsv"], "default": "csv"},
                    "analysis_type": {"type": "string", "enum": ["summary", "stats", "correlations", "trends"], "default": "summary"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "Optional columns to analyze"}
                },
                "required": ["data"]
            }
        ),
        Tool(
            name="create_chart_visualization",
            description="Create charts (bar, line, pie, scatter, histogram) using Matplotlib.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "scatter", "histogram"]},
                    "data": {"type": "string", "description": "JSON with 'labels' and 'values' arrays"},
                    "title": {"type": "string", "default": "Chart"},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "filename": {"type": "string"}
                },
                "required": ["chart_type", "data"]
            }
        ),
        Tool(
            name="analyze_content_sentiment",
            description="Analyze text sentiment, subjectivity, or noun phrases using TextBlob.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text content to analyze"},
                    "analysis_type": {"type": "string", "enum": ["sentiment", "subjectivity", "noun_phrases"], "default": "sentiment"}
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="generate_keyword_cloud",
            description="Generate a keyword/word cloud image from text content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "max_words": {"type": "integer", "default": 100},
                    "width": {"type": "integer", "default": 800},
                    "height": {"type": "integer", "default": 400},
                    "background_color": {"type": "string", "default": "white"},
                    "filename": {"type": "string"}
                },
                "required": ["text"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    from tools.extended_tools import (
        analyze_data_table, create_chart_visualization,
        analyze_content_sentiment, generate_keyword_cloud,
    )
    
    tool_map = {
        "analyze_data_table": analyze_data_table,
        "create_chart_visualization": create_chart_visualization,
        "analyze_content_sentiment": analyze_content_sentiment,
        "generate_keyword_cloud": generate_keyword_cloud,
    }
    
    if name not in tool_map:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    try:
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
