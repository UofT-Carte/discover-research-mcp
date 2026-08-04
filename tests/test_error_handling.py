"""Portal failures must reach the client as failed tool calls, not successes.

The defect these cover — an error arriving as a *successful* result whose text
happens to read like an error message — is invisible below the MCP boundary, so
these tests observe `is_error` on the result a client receives.
"""

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock


def result_text(result) -> str:
    """The text block a client receives for a tool result."""
    return result.content[0].text if result.content else ""


SCHOLAR_PARAMS = {"scholar_id": "17964"}
SEARCH_PARAMS = {"query": "climate"}

HEALTHY_SEARCH_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 0},
    "resource": [],
    "filters": [],
}


@pytest.mark.asyncio
async def test_not_found_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """A 404 must fail the call, not return prose the model reads as data."""
    httpx_mock.add_response(status_code=404)

    result = await call_tool("discover_get_scholar", SCHOLAR_PARAMS)

    assert result.is_error is True
    assert "not found" in result_text(result).lower()


@pytest.mark.asyncio
async def test_bad_request_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """A 400 must fail the call."""
    httpx_mock.add_response(status_code=400, text="malformed filter")

    result = await call_tool("discover_search_scholars", SEARCH_PARAMS)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_rate_limit_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """A 429 must fail the call so the caller can back off, rather than
    concluding the scholar has no results."""
    httpx_mock.add_response(status_code=429)

    result = await call_tool("discover_search_scholars", SEARCH_PARAMS)

    assert result.is_error is True
    assert "rate limit" in result_text(result).lower()


@pytest.mark.asyncio
async def test_timeout_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """A timeout must fail the call, not present as an empty result set."""
    httpx_mock.add_exception(httpx.TimeoutException("timed out"))

    result = await call_tool("discover_search_scholars", SEARCH_PARAMS)

    assert result.is_error is True
    assert "timed out" in result_text(result).lower()


@pytest.mark.asyncio
async def test_publications_failure_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=500)

    result = await call_tool("discover_get_scholar_publications", SCHOLAR_PARAMS)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_grants_failure_is_a_failed_call(call_tool, httpx_mock: HTTPXMock):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=503)

    result = await call_tool("discover_get_scholar_grants", SCHOLAR_PARAMS)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_filter_options_failure_is_a_failed_call(
    call_tool, httpx_mock: HTTPXMock
):
    """Every tool maps portal failures the same way, not just search."""
    httpx_mock.add_response(status_code=500)

    result = await call_tool("discover_get_filter_options", {"filter_type": "tags"})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_success_is_still_a_successful_call(call_tool, httpx_mock: HTTPXMock):
    """The failure mapping must not turn healthy responses into errors."""
    httpx_mock.add_response(json=HEALTHY_SEARCH_RESPONSE)

    result = await call_tool("discover_search_scholars", SEARCH_PARAMS)

    assert result.is_error is False
    assert json.loads(result_text(result))["total"] == 0


@pytest.mark.asyncio
async def test_failure_raises_when_the_client_asks_it_to(
    call_tool, httpx_mock: HTTPXMock
):
    """A client using the raising style sees an exception, not a value."""
    from fastmcp.exceptions import ToolError

    httpx_mock.add_response(status_code=404)

    with pytest.raises(ToolError, match="not found"):
        await call_tool("discover_get_scholar", SCHOLAR_PARAMS, raise_on_error=True)
