"""
Lightweight MCP protocol implementation (JSON-RPC over stdio).
Replaces the `mcp` SDK package for environments where it's unavailable.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable


class Tool:
    def __init__(self, name: str, description: str, inputSchema: dict):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


class TextContent:
    def __init__(self, type: str = "text", text: str = ""):
        self.type = type
        self.text = text


class Server:
    """Minimal MCP server using JSON-RPC 2.0 over stdio."""

    def __init__(self, name: str):
        self.name = name
        self._tool_list: list[Tool] = []
        self._tool_handlers: dict[str, Callable] = {}

    def list_tools(self) -> list[Tool]:
        return self._tool_list

    def tool(self, name: str, description: str, inputSchema: dict):
        """Decorator to register a tool handler."""
        def decorator(fn: Callable):
            self._tool_list.append(Tool(name, description, inputSchema))
            self._tool_handlers[name] = fn
            return fn
        return decorator

    async def _handle_request(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            params = msg.get("params", {})
            protocol_version = params.get("protocolVersion", "2024-11-05")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "serverInfo": {"name": self.name, "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                        for t in self._tool_list
                    ]
                },
            }

        if method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            handler = self._tool_handlers.get(tool_name)
            if not handler:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
                }
            try:
                result = await handler(**arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": result}]},
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)},
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def run(self):
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                response = await self._handle_request(msg)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(
                    json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}) + "\n"
                )
                sys.stdout.flush()
            except Exception:
                sys.stdout.write(
                    json.dumps({"jsonrpc": "2.0", "error": {"code": -32000, "message": traceback.format_exc()}}) + "\n"
                )
                sys.stdout.flush()
