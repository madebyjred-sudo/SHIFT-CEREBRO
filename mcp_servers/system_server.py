"""cerebro-mcp-system — MCP Server for system-level tools (file ops, commands, code search).
Tools: write_file_tool, read_file_tool, execute_command_tool, search_code_tool

SECURITY: This server is ONLY available in Shifty Studio (full DAG mode).
Never exposed in embed/copilot deployments.

Run standalone: python -m mcp_servers.system_server
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("cerebro-mcp-system")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="write_file_tool",
            description="Write content to a file in the repository. Returns a write request for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write to"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        ),
        Tool(
            name="read_file_tool",
            description="Read the content of a file in the repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="execute_command_tool",
            description="Execute a system command. Returns a command request for approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"}
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="search_code_tool",
            description="Search code in the repository using regex patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query/regex pattern"},
                    "file_pattern": {"type": "string", "description": "File glob pattern to search", "default": "*"}
                },
                "required": ["query"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """System tools return request tokens — actual execution requires approval."""
    
    results = {
        "write_file_tool": lambda args: f"SOLICITUD_ESCRITURA: {args.get('path', 'unknown')}",
        "read_file_tool": lambda args: f"SOLICITUD_LECTURA: {args.get('path', 'unknown')}",
        "execute_command_tool": lambda args: f"SOLICITUD_COMANDO: {args.get('command', 'unknown')}",
        "search_code_tool": lambda args: f"SOLICITUD_BUSQUEDA: {args.get('query', 'unknown')} en archivos {args.get('file_pattern', '*')}",
    }
    
    if name not in results:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    try:
        result = results[name](arguments)
        return [TextContent(type="text", text=result)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    
    asyncio.run(main())
