"""Portal failures must reach the client as failed tool calls, not successes.

These tests observe the MCP boundary rather than calling tool functions
directly, because the defect they cover — an error arriving as a *successful*
result whose text happens to start with "Error:" — is invisible below it.

The session is opened inside each call rather than in a fixture: the helper
uses anyio cancel scopes, which must be entered and exited in the same task,
and pytest-asyncio finalises async fixtures in a different one.

The private `_mcp_server` handle is a bridge: once the server moves to the
standalone FastMCP distribution, this becomes its public in-memory `Client`.
"""

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pytest_httpx import HTTPXMock

from server import mcp

SCHOLAR_ARGS = {"params": {"scholar_id": "17964"}}
SEARCH_ARGS = {"params": {"query": "climate"}}

HEALTHY_SEARCH_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 0},
    "resource": [],
    "filters": [],
}


async def _call(tool: str, args: dict):
    """Invoke a tool through the MCP boundary and return the raw result."""
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        return await session.call_tool(tool, args)


def _text(result) -> str:
    return result.content[0].text if result.content else ""


@pytest.mark.asyncio
async def test_not_found_is_a_failed_call(httpx_mock: HTTPXMock):
    """A 404 must fail the call, not return prose the model reads as data."""
    httpx_mock.add_response(status_code=404)

    result = await _call("discover_get_scholar", SCHOLAR_ARGS)

    assert result.isError is True
    assert "not found" in _text(result).lower()


@pytest.mark.asyncio
async def test_bad_request_is_a_failed_call(httpx_mock: HTTPXMock):
    """A 400 must fail the call."""
    httpx_mock.add_response(status_code=400, text="malformed filter")

    result = await _call("discover_search_scholars", SEARCH_ARGS)

    assert result.isError is True


@pytest.mark.asyncio
async def test_rate_limit_is_a_failed_call(httpx_mock: HTTPXMock):
    """A 429 must fail the call so the caller can back off, rather than
    concluding the scholar has no results."""
    httpx_mock.add_response(status_code=429)

    result = await _call("discover_search_scholars", SEARCH_ARGS)

    assert result.isError is True
    assert "rate limit" in _text(result).lower()


@pytest.mark.asyncio
async def test_timeout_is_a_failed_call(httpx_mock: HTTPXMock):
    """A timeout must fail the call, not present as an empty result set."""
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))

    result = await _call("discover_search_scholars", SEARCH_ARGS)

    assert result.isError is True
    assert "timed out" in _text(result).lower()


@pytest.mark.asyncio
async def test_publications_failure_is_a_failed_call(httpx_mock: HTTPXMock):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=500)

    result = await _call("discover_get_scholar_publications", SCHOLAR_ARGS)

    assert result.isError is True


@pytest.mark.asyncio
async def test_grants_failure_is_a_failed_call(httpx_mock: HTTPXMock):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=503)

    result = await _call("discover_get_scholar_grants", SCHOLAR_ARGS)

    assert result.isError is True


@pytest.mark.asyncio
async def test_filter_options_failure_is_a_failed_call(httpx_mock: HTTPXMock):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=500)

    result = await _call(
        "discover_get_filter_options", {"params": {"filter_type": "tags"}}
    )

    assert result.isError is True


@pytest.mark.asyncio
async def test_success_is_still_a_successful_call(httpx_mock: HTTPXMock):
    """The failure mapping must not turn healthy responses into errors."""
    httpx_mock.add_response(json=HEALTHY_SEARCH_RESPONSE)

    result = await _call("discover_search_scholars", SEARCH_ARGS)

    assert result.isError is False
    # Assert on the payload rather than the absence of an "Error:" prefix:
    # that prefix no longer exists, so its absence would guard nothing.
    assert json.loads(_text(result))["total"] == 0
