"""Translating a portal profile into a published one.

Most of this mapper was previously unexercised: degrees, phone numbers,
addresses, appointments, personal websites, the linked-object counts and the
teaching and grants summaries had no test at all. Nor did the wrapped-field
case — the portal returns `orcid` and `emailAddress` as objects rather than
strings, and no fixture ever sent one, so the branch handling them ran only
against the live portal.
"""

import pytest
from pytest_httpx import HTTPXMock

# A profile with every field populated, in the shapes the portal really sends:
# `orcid` and `emailAddress` wrapped in objects, `elementsUserProfileUrl` bare.
FULL_PROFILE = {
    "discoveryId": "1545",
    "discoveryUrlId": "1545-jonathan-abbatt",
    "firstNameLastName": "Jonathan Abbatt",
    "tabSummaryAbout": {"value": "<p>Studies <b>atmospheric</b> chemistry.</p>"},
    "emailAddress": {"address": "j.abbatt@example.utoronto.ca"},
    "orcid": {
        "value": "0000-0002-3372-334X",
        "uri": "https://orcid.org/0000-0002-3372-334X",
    },
    "elementsUserProfileUrl": "https://elements.example.utoronto.ca/1545",
    "phoneNumbers": [{"number": "+1 416 555 0101"}, {"number": "+1 416 555 0202"}],
    "addresses": [{"singleLineFormat": "80 St George St, Toronto"}],
    "degrees": [
        {"name": "PhD", "institution": {"organisation": "MIT"}},
        {"name": "BSc", "institution": {"organisation": "Toronto"}},
    ],
    "tags": {"explicit": [{"value": "Atmospheric chemistry"}, {"value": "Aerosols"}]},
    "customFilterThree": ["Media enquiries"],
    "positions": [{"position": "Professor", "department": "Chemistry"}],
    "academicAppointments": [{"position": "Chair"}],
    "nonAcademicAppointments": [{"position": "Advisor"}],
    "personalWebsites": [
        {"type": "lab", "label": "Group", "url": "https://example.org"}
    ],
    "linkedObjectIds": {
        "publications": ["p1", "p2", "p3"],
        "grants": ["g1", "g2"],
        "professionalActivities": ["a1"],
    },
    "tabSummaryTeachingActivities": {"value": "<p>Teaches CHM123.</p>"},
    "tabSummaryGrants": {"value": "<p>Holds NSERC funding.</p>"},
}

# The portal omits fields freely and sends nulls for some collections.
SPARSE_PROFILE = {
    "discoveryId": "999",
    "firstNameLastName": "Minimal Scholar",
    "positions": None,
    "degrees": None,
    "linkedObjectIds": None,
    "phoneNumbers": [],
}


@pytest.mark.asyncio
async def test_wrapped_fields_are_reduced_to_scalars(call_tool, httpx_mock: HTTPXMock):
    """`orcid` and `emailAddress` arrive as objects and must publish as strings."""
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert result.data.orcid == "0000-0002-3372-334X"
    assert result.data.email == "j.abbatt@example.utoronto.ca"


@pytest.mark.asyncio
async def test_unwrapped_field_passes_through(call_tool, httpx_mock: HTTPXMock):
    """A field the portal sends bare must not be mangled by the same handling."""
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert (
        result.data.elements_profile_url == "https://elements.example.utoronto.ca/1545"
    )


@pytest.mark.asyncio
async def test_first_phone_and_address_are_taken(call_tool, httpx_mock: HTTPXMock):
    """Both are lists upstream but single values in the published profile."""
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert result.data.phone == "+1 416 555 0101"
    assert result.data.address == "80 St George St, Toronto"


@pytest.mark.asyncio
async def test_degrees_flatten_their_nested_institution(
    call_tool, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert [(d.name, d.institution) for d in result.data.degrees] == [
        ("PhD", "MIT"),
        ("BSc", "Toronto"),
    ]


@pytest.mark.asyncio
async def test_linked_object_counts_come_from_ids(call_tool, httpx_mock: HTTPXMock):
    """The counts are lengths of id lists, not fetched records."""
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert result.data.publication_count == 3
    assert result.data.grant_count == 2
    assert result.data.professional_activity_count == 1


@pytest.mark.asyncio
async def test_html_summaries_are_reduced_to_text(call_tool, httpx_mock: HTTPXMock):
    """Bio, teaching and grants summaries all arrive as HTML."""
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert "<b>" not in result.data.bio
    assert "atmospheric" in result.data.bio
    assert result.data.teaching_summary == "Teaches CHM123."
    assert result.data.grants_summary == "Holds NSERC funding."


@pytest.mark.asyncio
async def test_tags_and_availability_publish_as_lists(call_tool, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert result.data.research_topics == ["Atmospheric chemistry", "Aerosols"]
    assert result.data.availability == ["Media enquiries"]
    assert len(result.data.personal_websites) == 1


@pytest.mark.asyncio
async def test_profile_url_uses_the_url_style_id(call_tool, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=FULL_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "1545"})

    assert result.data.profile_url.endswith("/1545-jonathan-abbatt")


@pytest.mark.asyncio
async def test_null_and_missing_fields_publish_as_empty(
    call_tool, httpx_mock: HTTPXMock
):
    """Nulls and absent keys must both become empty rather than failing."""
    httpx_mock.add_response(json=SPARSE_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "999"})

    assert result.is_error is False
    assert result.data.name == "Minimal Scholar"
    assert result.data.positions == []
    assert result.data.degrees == []
    assert result.data.publication_count == 0
    assert result.data.phone == ""
    assert result.data.orcid is None


@pytest.mark.asyncio
async def test_profile_url_falls_back_to_the_numeric_id(
    call_tool, httpx_mock: HTTPXMock
):
    """With no url-style id upstream, the numeric one is used instead."""
    httpx_mock.add_response(json=SPARSE_PROFILE)

    result = await call_tool("discover_get_scholar", {"scholar_id": "999"})

    assert result.data.profile_url.endswith("/999")
