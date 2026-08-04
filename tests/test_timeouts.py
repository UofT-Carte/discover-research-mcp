"""Execution is bounded, and the bounds compose sanely with retry.

FastMCP applies a tool timeout per attempt, not per call, so a retried tool can
consume its timeout once per attempt. These tests pin the relationships that
keep the worst case bounded rather than restating the constants.
"""

import httpx
import pytest

import portal
import server

TOOL_NAMES = [
    "discover_search_scholars",
    "discover_get_scholar",
    "discover_get_scholar_publications",
    "discover_get_scholar_grants",
    "discover_get_filter_options",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_every_tool_has_an_execution_timeout(tool_name):
    """An unbounded tool can stall a session indefinitely."""
    tool = await server.mcp.get_tool(tool_name)

    assert tool.timeout is not None, f"{tool_name} has no execution ceiling"
    assert tool.timeout == server.TOOL_TIMEOUT_SECONDS


def test_connect_timeout_stays_cheap_to_retry():
    """Retry re-pays the connect timeout on every attempt.

    Connection faults are the retried class, so the connect timeout is
    multiplied by the attempt count. Keeping it well below the read timeout is
    what stops a dead host from stalling a caller for minutes.
    """
    connect = portal.PORTAL_TIMEOUT.connect
    attempts = portal.RETRY_ATTEMPTS + 1

    assert connect is not None
    assert connect * attempts <= 20, (
        f"worst-case connect retry exposure is {connect * attempts}s"
    )


def test_read_timeout_is_not_multiplied_by_retry():
    """Read timeouts are excluded from retry, so they are paid at most once."""
    read = portal.PORTAL_TIMEOUT.read

    assert read is not None
    assert not issubclass(httpx.ReadTimeout, portal.RETRY_EXCEPTIONS)


def test_tool_timeout_is_a_backstop_not_the_primary_bound():
    """The HTTP timeout should fire first and give a specific message.

    A tool timeout that undercuts the read timeout would mask portal
    diagnostics behind a generic 'execution timed out'.
    """
    assert server.TOOL_TIMEOUT_SECONDS > portal.PORTAL_TIMEOUT.read
