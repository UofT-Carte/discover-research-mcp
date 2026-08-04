"""Tools must publish real output schemas and return structured content.

While tools return hand-serialised JSON strings, every tool advertises
`{"result": {"type": "string"}}` — a client is told the tool returns a string
and cannot see which fields exist without calling it and parsing prose.
"""

import json

import pytest
from pytest_httpx import HTTPXMock

SEARCH_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 1},
    "resource": [
        {
            "discoveryId": "17964",
            "discoveryUrlId": "17964-michael-guerzhoy",
            "firstNameLastName": "Michael Guerzhoy",
            "positions": [{"department": "Computer Science", "position": "Professor"}],
            "tags": {"explicit": [{"value": "Machine learning"}]},
            "tabSummaryAbout": {"value": "<p>Works on ML.</p>"},
            "customFilterThree": ["Media enquiries"],
        }
    ],
    "filters": [],
}

PUBLICATIONS_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 25, "total": 1},
    "resource": [
        {
            "discoveryId": "p1",
            "title": "A paper about things",
            "objectTypeDisplayName": "Journal article",
            "date1": {"year": 2020},
            "authors": [{"displayName": "Michael Guerzhoy"}],
            "journal": "Journal of Things",
            "abstract": "<p>An abstract.</p>",
            "doi": "10.1000/xyz",
            "url": "https://example.org/p1",
        }
    ],
}

PROFILE_RESPONSE = {
    "discoveryId": "17964",
    "discoveryUrlId": "17964-michael-guerzhoy",
    "firstNameLastName": "Michael Guerzhoy",
    "tabSummaryAbout": {"value": "<p>Works on ML.</p>"},
    "emailAddress": "m@example.org",
    "linkedObjectIds": {"publications": ["a", "b"], "grants": ["c"]},
    "tags": {"explicit": [{"value": "Machine learning"}]},
}

EXPECTED_FIELDS = [
    ("discover_search_scholars", ["total", "page", "per_page", "has_more", "scholars"]),
    ("discover_get_scholar", ["id", "name", "profile_url", "publication_count"]),
    (
        "discover_get_scholar_publications",
        ["scholar_id", "total", "has_more", "publications"],
    ),
    ("discover_get_scholar_grants", ["scholar_id", "total", "has_more", "grants"]),
    ("discover_get_filter_options", ["filter_type", "query", "options"]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "fields"), EXPECTED_FIELDS)
async def test_tool_advertises_its_result_fields(list_tools, tool_name, fields):
    """The output schema must describe the result, not say 'a string'."""
    tools = {t.name: t for t in await list_tools()}
    schema = tools[tool_name].outputSchema or {}
    properties = schema.get("properties", {})

    assert "result" not in properties, "result is still wrapped as an opaque string"
    for field in fields:
        assert field in properties, f"{tool_name} does not advertise {field!r}"


@pytest.mark.asyncio
async def test_search_returns_structured_content(call_tool, httpx_mock: HTTPXMock):
    """Structured content must carry the fields directly, not a JSON blob."""
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    result = await call_tool("discover_search_scholars", {"query": "ML"})

    structured = result.structured_content
    assert structured["total"] == 1
    assert structured["has_more"] is False
    scholar = structured["scholars"][0]
    assert scholar["id"] == "17964"
    assert scholar["name"] == "Michael Guerzhoy"
    assert scholar["tags"] == ["Machine learning"]


@pytest.mark.asyncio
async def test_search_result_is_typed(call_tool, httpx_mock: HTTPXMock):
    """`.data` must give typed access rather than a string needing json.loads."""
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    result = await call_tool("discover_search_scholars", {"query": "ML"})

    assert not isinstance(result.data, str), "result is still an unparsed string"
    assert result.data.total == 1
    assert result.data.scholars[0].name == "Michael Guerzhoy"


@pytest.mark.asyncio
async def test_publications_return_structured_content(call_tool, httpx_mock: HTTPXMock):
    """Nested records must survive as structured data, including nulls."""
    httpx_mock.add_response(json=PUBLICATIONS_RESPONSE)

    result = await call_tool(
        "discover_get_scholar_publications", {"scholar_id": "17964"}
    )

    publication = result.structured_content["publications"][0]
    assert publication["title"] == "A paper about things"
    assert publication["year"] == 2020
    assert publication["doi"] == "10.1000/xyz"


@pytest.mark.asyncio
async def test_profile_returns_structured_content(call_tool, httpx_mock: HTTPXMock):
    """The profile tool exposes its counts as numbers, not text."""
    httpx_mock.add_response(json=PROFILE_RESPONSE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "17964"})

    structured = result.structured_content
    assert structured["name"] == "Michael Guerzhoy"
    assert structured["publication_count"] == 2
    assert structured["grant_count"] == 1


@pytest.mark.asyncio
async def test_text_block_still_present_for_text_only_clients(
    call_tool, httpx_mock: HTTPXMock
):
    """Structured output must not remove the text rendering clients may rely on."""
    httpx_mock.add_response(json=SEARCH_RESPONSE)

    result = await call_tool("discover_search_scholars", {"query": "ML"})

    assert result.content, "no content blocks returned"
    assert json.loads(result.content[0].text)["total"] == 1
