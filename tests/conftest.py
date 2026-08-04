"""The single test seam: drive tools the way a real MCP client does.

Every test invokes tools through FastMCP's in-memory client rather than by
calling the decorated functions directly. Two things are observable there and
nowhere below it: whether a call succeeded or failed, and the schemas and
content a client actually receives. The outbound portal request is observed at
the same seam via `pytest_httpx`.
"""

import pytest
from fastmcp import Client

from server import mcp


@pytest.fixture
def call_tool():
    """Return a coroutine that invokes a tool by name through the MCP boundary.

    Errors are returned as results rather than raised, so tests can assert on
    `is_error` — the flag a calling model actually sees.
    """

    async def _call(name: str, params: dict, *, raise_on_error: bool = False):
        async with Client(mcp) as client:
            return await client.call_tool(
                name, {"params": params}, raise_on_error=raise_on_error
            )

    return _call


@pytest.fixture
def list_tools():
    """Return a coroutine yielding the tool definitions a client is offered."""

    async def _list():
        async with Client(mcp) as client:
            return await client.list_tools()

    return _list
