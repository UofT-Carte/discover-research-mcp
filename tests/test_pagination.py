"""The has_more flag must tell a caller whether to fetch another page.

Written before the paging arithmetic moves behind the portal seam. Until now no
test asserted `has_more is True` anywhere: every fixture had an empty resource
list or a total no larger than the page. So the one invariant being relocated
was the one the suite did not pin — and it has been wrong before, when the
requested page size never reached the portal and offsets were computed from a
size the portal never used.
"""

import pytest
from pytest_httpx import HTTPXMock

TOTAL = 30
PER_PAGE = 10


def linked_response(count: int, total: int = TOTAL) -> dict:
    """A /<kind>/linkedTo envelope carrying `count` records."""
    return {
        "pagination": {"perPage": PER_PAGE, "total": total},
        "resource": [
            {"discoveryId": f"r{i}", "title": f"Record {i}"} for i in range(count)
        ],
    }


def search_response(count: int, total: int = TOTAL) -> dict:
    return {
        "pagination": {"perPage": PER_PAGE, "total": total},
        "resource": [
            {"discoveryId": f"s{i}", "firstNameLastName": f"Scholar {i}"}
            for i in range(count)
        ],
        "filters": [],
    }


LINKED_TOOLS = ["discover_get_scholar_publications", "discover_get_scholar_grants"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", LINKED_TOOLS)
async def test_has_more_is_true_when_records_remain(
    call_tool, httpx_mock: HTTPXMock, tool_name
):
    """30 records, first page of 10 — 20 are still unfetched."""
    httpx_mock.add_response(json=linked_response(PER_PAGE))

    result = await call_tool(
        tool_name, {"scholar_id": "17964", "page": 1, "per_page": PER_PAGE}
    )

    assert result.data.total == TOTAL
    assert result.data.has_more is True


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", LINKED_TOOLS)
async def test_has_more_is_false_on_the_final_page(
    call_tool, httpx_mock: HTTPXMock, tool_name
):
    """30 records, third page of 10 — the caller has now seen all of them."""
    httpx_mock.add_response(json=linked_response(PER_PAGE))

    result = await call_tool(
        tool_name, {"scholar_id": "17964", "page": 3, "per_page": PER_PAGE}
    )

    assert result.data.has_more is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", LINKED_TOOLS)
async def test_has_more_is_false_when_a_page_comes_back_short(
    call_tool, httpx_mock: HTTPXMock, tool_name
):
    """A page returning fewer records than asked for is the last one."""
    httpx_mock.add_response(json=linked_response(4, total=14))

    result = await call_tool(
        tool_name, {"scholar_id": "17964", "page": 2, "per_page": PER_PAGE}
    )

    assert result.data.has_more is False


@pytest.mark.asyncio
async def test_search_has_more_is_true_when_records_remain(
    call_tool, httpx_mock: HTTPXMock
):
    """Search keeps its own copy of this arithmetic; pin it too."""
    httpx_mock.add_response(json=search_response(PER_PAGE))

    result = await call_tool(
        "discover_search_scholars", {"query": "x", "page": 1, "per_page": PER_PAGE}
    )

    assert result.data.total == TOTAL
    assert result.data.has_more is True


@pytest.mark.asyncio
async def test_search_has_more_is_false_on_the_final_page(
    call_tool, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=search_response(PER_PAGE))

    result = await call_tool(
        "discover_search_scholars", {"query": "x", "page": 3, "per_page": PER_PAGE}
    )

    assert result.data.has_more is False
