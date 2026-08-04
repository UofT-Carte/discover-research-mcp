"""The server owns one HTTP client for its lifetime, not one per tool call.

Constructing a client per call pays TCP and TLS setup on every request and
discards the connection pool immediately. This is the one place the tests reach
past the MCP boundary: connection reuse has no protocol-level signal, so the
contract is measured by whether client construction scales with call count.
"""

import httpx
import pytest
from fastmcp import Client
from pytest_httpx import HTTPXMock

from server import mcp

SEARCH_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 0},
    "resource": [],
    "filters": [],
}


@pytest.mark.asyncio
async def test_http_client_is_not_constructed_per_call(
    monkeypatch, httpx_mock: HTTPXMock
):
    """Client construction must not scale with the number of tool calls."""
    constructed = []
    real_init = httpx.AsyncClient.__init__

    def counting_init(self, *args, **kwargs):
        constructed.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", counting_init)
    httpx_mock.add_response(json=SEARCH_RESPONSE, is_reusable=True)

    async with Client(mcp) as client:
        await client.call_tool("discover_search_scholars", {"params": {"query": "a"}})
        after_first = len(constructed)

        for query in ("b", "c", "d"):
            await client.call_tool(
                "discover_search_scholars", {"params": {"query": query}}
            )

    assert len(constructed) == after_first, (
        f"{len(constructed) - after_first} extra HTTP clients built for 3 further "
        "calls — the client is being constructed per call"
    )


@pytest.mark.asyncio
async def test_shared_client_still_sends_portal_headers(
    call_tool, httpx_mock: HTTPXMock
):
    """Moving headers onto the shared client must not drop them."""
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    await call_tool("discover_search_scholars", {"query": "a"})

    headers = httpx_mock.get_requests()[-1].headers
    assert headers["Origin"] == "https://discover.research.utoronto.ca"
    assert headers["Referer"] == "https://discover.research.utoronto.ca"
    assert headers["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_tools_still_work_across_repeated_calls(call_tool, httpx_mock: HTTPXMock):
    """A shared client must stay usable after the first call completes."""
    httpx_mock.add_response(json=SEARCH_RESPONSE, is_reusable=True)

    first = await call_tool("discover_search_scholars", {"query": "a"})
    second = await call_tool("discover_search_scholars", {"query": "b"})

    assert first.is_error is False
    assert second.is_error is False
