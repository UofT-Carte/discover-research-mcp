"""Retry and response caching behaviour.

Both are observed at the MCP boundary plus the count of upstream requests the
portal actually receives, which is what these middlewares exist to change.
"""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from discover_research_mcp.server import reset_response_cache

SEARCH_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 0},
    "resource": [],
    "filters": [],
}


@pytest.mark.asyncio
async def test_transient_transport_failure_is_retried(call_tool, httpx_mock: HTTPXMock):
    """A dropped connection must be retried rather than surfaced as a dead end."""
    httpx_mock.add_exception(httpx.ConnectError("connection reset"))
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    result = await call_tool("discover_search_scholars", {"query": "retry-me"})

    assert result.is_error is False, "transient failure was not retried"
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_not_found_is_not_retried(call_tool, httpx_mock: HTTPXMock):
    """A 404 is a real answer, not a transient fault — retrying it wastes calls."""
    httpx_mock.add_response(status_code=404)

    result = await call_tool("discover_get_scholar", {"scholar_id": "999999"})

    assert result.is_error is True
    assert len(httpx_mock.get_requests()) == 1, "a definitive error was retried"


@pytest.mark.asyncio
async def test_read_timeout_is_not_retried(call_tool, httpx_mock: HTTPXMock):
    """The portal accepted the request and is slow — retrying re-pays the full
    timeout and stalls the caller for a multiple of it before failing anyway."""
    httpx_mock.add_exception(httpx.ReadTimeout("too slow"))

    result = await call_tool("discover_search_scholars", {"query": "slow"})

    assert result.is_error is True
    assert len(httpx_mock.get_requests()) == 1, "a slow response was retried"


@pytest.mark.asyncio
async def test_identical_calls_hit_the_portal_once(call_tool, httpx_mock: HTTPXMock):
    """Repeating a lookup must be served from cache, not re-fetched."""
    httpx_mock.add_response(json=SEARCH_RESPONSE, is_reusable=True)

    first = await call_tool("discover_search_scholars", {"query": "cache-me"})
    second = await call_tool("discover_search_scholars", {"query": "cache-me"})

    assert first.is_error is False
    assert second.is_error is False
    assert len(httpx_mock.get_requests()) == 1, "identical call re-hit the portal"


@pytest.mark.asyncio
async def test_different_arguments_are_cached_separately(
    call_tool, httpx_mock: HTTPXMock
):
    """The cache must key on arguments, not just on the tool name."""
    httpx_mock.add_response(json=SEARCH_RESPONSE, is_reusable=True)

    await call_tool("discover_search_scholars", {"query": "alpha"})
    await call_tool("discover_search_scholars", {"query": "beta"})

    assert len(httpx_mock.get_requests()) == 2, "distinct queries shared a cache entry"


@pytest.mark.asyncio
async def test_failed_calls_are_not_cached(call_tool, httpx_mock: HTTPXMock):
    """A portal blip must not be memoised and replayed for the cache lifetime.

    This is why errors are raised rather than returned: a raised error
    propagates past the cache and is never stored.
    """
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    first = await call_tool("discover_search_scholars", {"query": "blip"})
    second = await call_tool("discover_search_scholars", {"query": "blip"})

    assert first.is_error is True
    assert second.is_error is False, "a cached error was replayed"


@pytest.mark.asyncio
async def test_resetting_the_cache_actually_empties_it(
    call_tool, httpx_mock: HTTPXMock
):
    """The isolation every other test depends on, exercised directly.

    Test isolation was previously enforced by a fixture that found its target
    with a `getattr` default and a class-name string, so it could stop working
    without anything failing. Nothing verified the reset itself.
    """
    httpx_mock.add_response(json=SEARCH_RESPONSE, is_reusable=True)
    args = {"query": "reset-me"}

    await call_tool("discover_search_scholars", args)
    await call_tool("discover_search_scholars", args)
    assert len(httpx_mock.get_requests()) == 1, "second call should have been cached"

    reset_response_cache()

    await call_tool("discover_search_scholars", args)
    assert len(httpx_mock.get_requests()) == 2, "cache was not emptied by the reset"
