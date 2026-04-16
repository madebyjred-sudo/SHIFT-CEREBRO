"""cerebro-mcp-creative — MCP Server for creative tools (DALL-E images, QR codes).
Tools: generate_marketing_image, generate_campaign_qr

Run standalone: python -m mcp_servers.creative_server
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.types import Tool, TextContent

app = Server("cerebro-mcp-creative")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="generate_marketing_image",
            description="Generate a marketing image using DALL-E 3 via OpenAI API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed description of the image to generate"},
                    "size": {"type": "string", "enum": ["1024x1024", "1024x1792", "1792x1024"], "default": "1024x1024"},
                    "quality": {"type": "string", "enum": ["standard", "hd"], "default": "standard"},
                    "style": {"type": "string", "enum": ["vivid", "natural"], "default": "vivid"},
                    "filename": {"type": "string"}
                },
                "required": ["prompt"]
            }
        ),
        Tool(
            name="generate_campaign_qr",
            description="Generate a QR code for campaigns (URL, text, vcard, email).",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Data to encode (URL, text, etc.)"},
                    "qr_type": {"type": "string", "enum": ["url", "text", "vcard", "email"], "default": "url"},
                    "size": {"type": "integer", "description": "QR code box size in pixels", "default": 10},
                    "filename": {"type": "string"}
                },
                "required": ["data"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    from tools.extended_tools import generate_marketing_image, generate_campaign_qr
    
    tool_map = {
        "generate_marketing_image": generate_marketing_image,
        "generate_campaign_qr": generate_campaign_qr,
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
