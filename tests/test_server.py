"""Tests for discover_search_scholars filter serialization."""
import json
import pytest
from pytest_httpx import HTTPXMock
from server import discover_search_scholars, SearchScholarsInput

FAKE_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 1, "totalIsLowerBound": False},
    "sort": "relevance",
    "resource": [],
    "filters": [],
}


def _last_request_body(httpx_mock: HTTPXMock) -> dict:
    requests = httpx_mock.get_requests()
    assert requests, "No requests were made"
    return json.loads(requests[-1].content)


@pytest.mark.asyncio
async def test_tag_filter_uses_values_key(httpx_mock: HTTPXMock):
    """tag_filter must send values: {tags: [value]}, not selectedValues."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await discover_search_scholars(
        SearchScholarsInput(query="AI", tag_filter="Machine learning")
    )

    body = _last_request_body(httpx_mock)
    tags_filter = next(f for f in body["filters"] if f["name"] == "tags")

    assert "selectedValues" not in tags_filter, "selectedValues must not be sent"
    assert tags_filter["values"] == {"tags": ["Machine learning"]}
    assert tags_filter["useValuesToFilter"] is True
    assert tags_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_department_filter_uses_values_key(httpx_mock: HTTPXMock):
    """department_filter must send values: {department: [value]}, not selectedValues."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await discover_search_scholars(
        SearchScholarsInput(query="AI", department_filter="Faculty of Arts and Science, Department of Chemistry")
    )

    body = _last_request_body(httpx_mock)
    dept_filter = next(f for f in body["filters"] if f["name"] == "department")

    assert "selectedValues" not in dept_filter, "selectedValues must not be sent"
    assert dept_filter["values"] == {"department": ["Faculty of Arts and Science, Department of Chemistry"]}
    assert dept_filter["useValuesToFilter"] is True
    assert dept_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_availability_filter_uses_values_key(httpx_mock: HTTPXMock):
    """availability_filter must send values: {customFilterThree: [value]}."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await discover_search_scholars(
        SearchScholarsInput(query="AI", availability_filter="Media enquiries")
    )

    body = _last_request_body(httpx_mock)
    avail_filter = next(f for f in body["filters"] if f["name"] == "customFilterThree")

    assert "selectedValues" not in avail_filter, "selectedValues must not be sent"
    assert avail_filter["values"] == {"customFilterThree": ["Media enquiries"]}
    assert avail_filter["useValuesToFilter"] is True
    assert avail_filter["matchDocsWithMissingValues"] is False


@pytest.mark.asyncio
async def test_unfiltered_search_sends_no_values(httpx_mock: HTTPXMock):
    """A search with no optional filters must not send any values or selectedValues keys."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    await discover_search_scholars(SearchScholarsInput(query="climate"))

    body = _last_request_body(httpx_mock)
    for f in body["filters"]:
        assert "values" not in f
        assert "selectedValues" not in f
        assert f["useValuesToFilter"] is False
