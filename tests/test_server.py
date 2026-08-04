"""Tests for outbound Discover Research portal request construction.

These assert on the request the server sends upstream, captured at the same
seam the result assertions use. They exist because a real defect shipped in
filter serialisation, and because page size and identifier handling were both
silently wrong.
"""

import json

import pytest
from pytest_httpx import HTTPXMock

FAKE_RESPONSE = {
    "pagination": {
        "startFrom": 0,
        "perPage": 20,
        "total": 1,
        "totalIsLowerBound": False,
    },
    "sort": "relevance",
    "resource": [],
    "filters": [],
}

FAKE_PROFILE = {
    "discoveryId": "17964",
    "discoveryUrlId": "17964-michael-guerzhoy",
    "firstNameLastName": "Michael Guerzhoy",
}


def _last_request_body(httpx_mock: HTTPXMock) -> dict:
    requests = httpx_mock.get_requests()
    assert requests, "No requests were made"
    return json.loads(requests[-1].content)


def _requested_paging(body: dict) -> tuple[int | None, int | None]:
    """Return (per_page, start_from) as expressed in the outbound payload.

    Tolerant of where the offset is carried, so these tests constrain the
    behaviour without dictating the exact payload layout.
    """
    pagination = body.get("pagination", {})
    return pagination.get("perPage"), pagination.get("startFrom", body.get("startFrom"))


# ─── Filter serialisation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tag_filter_uses_values_key(call_tool, httpx_mock: HTTPXMock):
    """tag_filter must send values: {tags: [value]}, not selectedValues."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool(
        "discover_search_scholars", {"query": "AI", "tag_filter": "Machine learning"}
    )

    body = _last_request_body(httpx_mock)
    tags_filter = next(f for f in body["filters"] if f["name"] == "tags")

    assert "selectedValues" not in tags_filter, "selectedValues must not be sent"
    assert tags_filter["values"] == ["Machine learning"]
    assert tags_filter["useValuesToFilter"] is True
    assert tags_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_department_filter_uses_values_key(call_tool, httpx_mock: HTTPXMock):
    """department_filter must send values: {department: [value]}."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool(
        "discover_search_scholars",
        {
            "query": "AI",
            "department_filter": "Faculty of Arts and Science, Department of Chemistry",
        },
    )

    body = _last_request_body(httpx_mock)
    dept_filter = next(f for f in body["filters"] if f["name"] == "department")

    assert "selectedValues" not in dept_filter, "selectedValues must not be sent"
    assert dept_filter["values"] == [
        "Faculty of Arts and Science, Department of Chemistry"
    ]
    assert dept_filter["useValuesToFilter"] is True
    assert dept_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_availability_filter_uses_values_key(call_tool, httpx_mock: HTTPXMock):
    """availability_filter must send values: {customFilterThree: [value]}."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool(
        "discover_search_scholars",
        {"query": "AI", "availability_filter": "Media enquiries"},
    )

    body = _last_request_body(httpx_mock)
    avail_filter = next(f for f in body["filters"] if f["name"] == "customFilterThree")

    assert "selectedValues" not in avail_filter, "selectedValues must not be sent"
    assert avail_filter["values"] == ["Media enquiries"]
    assert avail_filter["useValuesToFilter"] is True
    assert avail_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_unfiltered_search_sends_no_values(call_tool, httpx_mock: HTTPXMock):
    """A search with no optional filters must send no values keys at all."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_search_scholars", {"query": "climate"})

    body = _last_request_body(httpx_mock)
    for f in body["filters"]:
        assert "values" not in f
        assert "selectedValues" not in f
        assert f["useValuesToFilter"] is False


# ─── Search page size ────────────────────────────────────────────────────────
#
# The portal returns 25 records when no page size is expressed (verified against
# the live API on 2026-08-04), while this server declares a default of 20. When
# the requested size never reached the portal, offsets were computed from a page
# size the portal never used, so consecutive pages overlapped.


@pytest.mark.asyncio
async def test_search_sends_requested_page_size(call_tool, httpx_mock: HTTPXMock):
    """per_page must reach the portal, not merely be echoed back to the caller."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_search_scholars", {"query": "AI", "per_page": 50})

    per_page, _ = _requested_paging(_last_request_body(httpx_mock))
    assert per_page == 50, "requested page size never reached the portal"


@pytest.mark.asyncio
async def test_search_default_page_size_reaches_portal(
    call_tool, httpx_mock: HTTPXMock
):
    """The declared default (20) must be sent, or the portal applies its own (25)."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_search_scholars", {"query": "AI"})

    per_page, _ = _requested_paging(_last_request_body(httpx_mock))
    assert per_page == 20, "portal will fall back to 25 and pages will overlap"


@pytest.mark.asyncio
async def test_search_pages_tile_without_overlap(call_tool, httpx_mock: HTTPXMock):
    """Offset and page size must agree, so pages do not re-fetch records."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool(
        "discover_search_scholars", {"query": "AI", "page": 3, "per_page": 10}
    )

    per_page, start_from = _requested_paging(_last_request_body(httpx_mock))
    assert per_page == 10
    assert start_from == 20, "offset must be a whole multiple of the page size sent"


# ─── Scholar identifier normalisation ────────────────────────────────────────
#
# Search results expose both a numeric `id` and a URL-style `url_id`. Either
# must work on every scholar-scoped tool.

URL_STYLE_ID = "17964-michael-guerzhoy"
NUMERIC_ID = "17964"


@pytest.mark.asyncio
async def test_profile_normalises_url_style_id(call_tool, httpx_mock: HTTPXMock):
    """The profile tool resolves the URL-style form to the numeric one."""
    httpx_mock.add_response(json=FAKE_PROFILE)

    await call_tool("discover_get_scholar", {"scholar_id": URL_STYLE_ID})

    requested = str(httpx_mock.get_requests()[-1].url)
    assert requested.endswith(f"/api/users/{NUMERIC_ID}")


@pytest.mark.asyncio
async def test_publications_normalise_url_style_id(call_tool, httpx_mock: HTTPXMock):
    """A url_id taken from search results must work on the publications tool."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_get_scholar_publications", {"scholar_id": URL_STYLE_ID})

    assert _last_request_body(httpx_mock)["objectId"] == NUMERIC_ID


@pytest.mark.asyncio
async def test_grants_normalise_url_style_id(call_tool, httpx_mock: HTTPXMock):
    """A url_id taken from search results must work on the grants tool."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_get_scholar_grants", {"scholar_id": URL_STYLE_ID})

    assert _last_request_body(httpx_mock)["objectId"] == NUMERIC_ID


@pytest.mark.asyncio
async def test_publications_accept_numeric_id(call_tool, httpx_mock: HTTPXMock):
    """Normalisation must leave an already-numeric identifier untouched."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_get_scholar_publications", {"scholar_id": NUMERIC_ID})

    assert _last_request_body(httpx_mock)["objectId"] == NUMERIC_ID


@pytest.mark.asyncio
async def test_grants_accept_numeric_id(call_tool, httpx_mock: HTTPXMock):
    """Normalisation must leave an already-numeric identifier untouched."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await call_tool("discover_get_scholar_grants", {"scholar_id": NUMERIC_ID})

    assert _last_request_body(httpx_mock)["objectId"] == NUMERIC_ID
