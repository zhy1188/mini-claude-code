"""MCP transport layer: stdio and Streamable HTTP implementations."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path


class MCPTransport(ABC):
    """Abstract interface for MCP transport (stdio or HTTP)."""

    @abstractmethod
    async def connect(self) -> dict:
        """Establish connection and perform initialize handshake. Returns init result."""

    @abstractmethod
    async def send(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request and return response result."""

    @abstractmethod
    async def send_notification(self, method: str, params: dict) -> None:
        """Send fire-and-forget JSON-RPC notification."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connection."""


class StdioTransport(MCPTransport):
    """Transport via local subprocess stdio."""

    _JSONRPC_TIMEOUT = 30
    _STDIO_READ_TIMEOUT = 30

    def __init__(self, command: str):
        self.command = command
        self._proc: asyncio.subprocess.Process | None = None

    async def connect(self) -> dict:
        """Spawn subprocess and perform initialize handshake."""
        try:
            self._proc = await asyncio.create_subprocess_shell(
                self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start MCP subprocess: {e}") from e

        asyncio.create_task(self._drain_stderr(self._proc, "stdio"))

        init_result = await self._jsonrpc_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "NexusAgent", "version": "0.1.0"},
        })

        return init_result

    async def send(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request via stdin and read response from stdout."""
        return await self._jsonrpc_request(method, params)

    async def send_notification(self, method: str, params: dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        await self._jsonrpc_notify(method, params)

    async def disconnect(self) -> None:
        """Kill subprocess."""
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    async def _jsonrpc_request(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request and wait for matching response."""
        request_id = id(object())
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Not connected")

        data = json.dumps(request) + "\n"
        self._proc.stdin.write(data.encode())
        await self._proc.stdin.drain()

        if self._proc.stdout is None:
            raise RuntimeError("Not connected")

        while True:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(), timeout=self._STDIO_READ_TIMEOUT
            )
            if not line:
                raise RuntimeError("MCP server closed connection")
            try:
                response = json.loads(line.decode())
                if "id" in response and response["id"] != request_id:
                    continue
                if "error" in response:
                    raise RuntimeError(f"MCP error: {response['error']}")
                return response.get("result", {})
            except json.JSONDecodeError:
                continue

    async def _jsonrpc_notify(self, method: str, params: dict) -> None:
        """Send JSON-RPC notification."""
        if self._proc is None or self._proc.stdin is None:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        data = json.dumps(notification) + "\n"
        self._proc.stdin.write(data.encode())
        await self._proc.stdin.drain()

    async def _drain_stderr(self, proc, name: str) -> None:
        """Background read stderr for logging."""
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    print(f"MCP[{name}] stderr: {text}")
        except Exception:
                pass


class HTTPTransport(MCPTransport):
    """Transport via Streamable HTTP (MCP spec 2025-03-26)."""

    _HTTP_TIMEOUT = 30
    _HTTP_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
    }

    def __init__(self, url: str):
        self.url = url
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None

    async def connect(self) -> dict:
        """Create HTTP client and perform initialize handshake."""
        import httpx

        self._client = httpx.AsyncClient(timeout=self._HTTP_TIMEOUT)

        init_result = await self._jsonrpc_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "NexusAgent", "version": "0.1.0"},
        })

        return init_result

    async def send(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request via HTTP POST."""
        return await self._jsonrpc_request(method, params)

    async def send_notification(self, method: str, params: dict) -> None:
        """Send JSON-RPC notification via HTTP POST."""
        await self._jsonrpc_notify(method, params)

    async def disconnect(self) -> None:
        """Send termination notification and close client."""
        try:
            await self._jsonrpc_notify("notifications/initialized", {})
        except Exception:
            pass
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _jsonrpc_request(self, method: str, params: dict) -> dict:
        """Send JSON-RPC request via HTTP POST, handle direct JSON or SSE response."""
        if self._client is None:
            raise RuntimeError("Not connected")

        request_id = id(object())
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        headers = dict(self._HTTP_HEADERS)
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id

        response = await self._client.post(
            self.url, json=request, headers=headers
        )

        # Capture session ID from initialize response
        if session_id := response.headers.get("MCP-Session-Id"):
            self._session_id = session_id

        content_type = response.headers.get("Content-Type", "")

        if response.status_code == 202:
            # Accepted — notification or async processing, wait for SSE
            return await self._wait_for_sse_response(request_id)
        elif "text/event-stream" in content_type:
            # SSE stream
            return await self._parse_sse_response(response.text, request_id)
        else:
            # Direct JSON response
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict) and "error" in body:
                raise RuntimeError(f"MCP error: {body['error']}")
            if isinstance(body, dict):
                return body.get("result", {})
            raise RuntimeError(f"Unexpected JSON response: {body}")

    async def _jsonrpc_notify(self, method: str, params: dict) -> None:
        """Send JSON-RPC notification (fire-and-forget)."""
        if self._client is None:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        headers = dict(self._HTTP_HEADERS)
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        await self._client.post(self.url, json=notification, headers=headers)

    async def _wait_for_sse_response(self, request_id: int) -> dict:
        """Wait for SSE stream response after 202 Accepted."""
        if self._client is None:
            raise RuntimeError("Not connected")

        headers = dict(self._HTTP_HEADERS)
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id

        async with self._client.stream(
            "GET", self.url, headers=headers
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        try:
                            event = json.loads(data)
                            if (
                                isinstance(event, dict)
                                and event.get("id") == request_id
                                and ("result" in event or "error" in event)
                            ):
                                if "error" in event:
                                    raise RuntimeError(f"MCP error: {event['error']}")
                                return event.get("result", {})
                        except json.JSONDecodeError:
                            continue
            raise RuntimeError("SSE stream ended without matching response")

    async def _parse_sse_response(self, text: str, request_id: int) -> dict:
        """Parse SSE response body and find matching JSON-RPC response."""
        for block in text.split("\n\n"):
            for line in block.split("\n"):
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        try:
                            event = json.loads(data)
                            if (
                                isinstance(event, dict)
                                and event.get("id") == request_id
                                and ("result" in event or "error" in event)
                            ):
                                if "error" in event:
                                    raise RuntimeError(f"MCP error: {event['error']}")
                                return event.get("result", {})
                        except json.JSONDecodeError:
                            continue
        raise RuntimeError(f"No SSE event found for id={request_id}")
