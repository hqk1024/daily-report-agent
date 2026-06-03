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
        """Read JSON-RPC requests from stdin, write responses to stdout.
        Auto-detects Content-Length framing vs newline-delimited JSON
        on the first message, so the server works with both Cursor's
        standard MCP stdio transport and our agent's framed transport."""
        framed_mode: bool | None = None

        while True:
            if framed_mode is None:
                msg = _detect_and_read(sys.stdin.buffer)
                if msg is None:
                    break
                framed_mode = msg.pop("__framed_mode__", False)
            elif framed_mode:
                msg = _read_message(sys.stdin.buffer)
                if msg is None:
                    break
            else:
                line = sys.stdin.buffer.readline()
                if not line:
                    break
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                msg = json.loads(line_str)

            try:
                response = await self._handle_request(msg)
                if response is not None:
                    if framed_mode:
                        _write_message(sys.stdout.buffer, response)
                    else:
                        _write_line(sys.stdout, response)
            except Exception:
                error_resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": traceback.format_exc()},
                }
                if framed_mode:
                    _write_message(sys.stdout.buffer, error_resp)
                else:
                    _write_line(sys.stdout, error_resp)


def _read_message(buffer) -> dict | None:
    """Read one Content-Length framed JSON message from a binary buffer.
    Returns None on EOF."""
    header = buffer.readline()
    if not header:
        return None
    header = header.decode("ascii").strip()
    if not header:
        return None
    if not header.startswith("Content-Length:"):
        raise ValueError(f"Expected Content-Length header, got: {header}")
    content_length = int(header.split(":", 1)[1].strip())
    buffer.readline()  # consume blank separator line
    body = buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def _write_message(buffer, data: dict) -> None:
    """Write one JSON message with Content-Length framing to a binary buffer."""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    buffer.write(header + body)
    buffer.flush()


def _write_line(buffer, data: dict) -> None:
    """Write one JSON message as a single newline-delimited line."""
    body = json.dumps(data, ensure_ascii=False) + "\n"
    buffer.write(body)
    buffer.flush()


def _detect_and_read(buffer) -> dict | None:
    """Read the first message and detect framing mode.
    Returns a dict with __framed_mode__ key indicating the detected mode.
    Returns None on EOF."""
    first_line = buffer.readline()
    if not first_line:
        return None
    first_line_str = first_line.decode("ascii").strip()

    if first_line_str.startswith("Content-Length:"):
        content_length = int(first_line_str.split(":", 1)[1].strip())
        buffer.readline()  # consume blank separator line
        body = buffer.read(content_length)
        msg = json.loads(body.decode("utf-8"))
        msg["__framed_mode__"] = True
        return msg

    # Newline-delimited mode: the first line IS the message
    if not first_line_str:
        return None
    msg = json.loads(first_line_str)
    msg["__framed_mode__"] = False
    return msg
