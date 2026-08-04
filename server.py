"""
MCP Server for University of Toronto Discover Research portal.

Provides tools to search for U of T scholars and retrieve their profiles,
publications, and research grants.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, field_validator

BASE_URL = "https://discover.research.utoronto.ca"
API_URL = f"{BASE_URL}/api"
TIMEOUT = 30.0

DEFAULT_FILTERS = [
    {
        "name": "department",
        "matchDocsWithMissingValues": True,
        "useValuesToFilter": False,
    },
    {
        "name": "customFilterThree",
        "matchDocsWithMissingValues": True,
        "useValuesToFilter": False,
    },
    {
        "name": "customFilterFour",
        "matchDocsWithMissingValues": True,
        "useValuesToFilter": False,
    },
    {
        "name": "customFilterFive",
        "matchDocsWithMissingValues": True,
        "useValuesToFilter": False,
    },
    {"name": "tags", "matchDocsWithMissingValues": True, "useValuesToFilter": False},
]

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": BASE_URL,
}


@dataclass
class PortalSession:
    """Resources shared by every tool for the server's lifetime."""

    http: httpx.AsyncClient


@asynccontextmanager
async def lifespan(_server: FastMCP):
    """Own one HTTP client for the server's lifetime.

    Building a client per tool call pays TCP and TLS setup on every request and
    throws the connection pool away immediately. Tools reach this through the
    request context; it is deliberately not per-request dependency injection,
    which would construct a client per call and defeat the purpose.
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as http:
        yield PortalSession(http=http)


mcp = FastMCP("discover_research_mcp", lifespan=lifespan)


def _http(ctx: Context) -> httpx.AsyncClient:
    """The shared HTTP client for this server."""
    return ctx.request_context.lifespan_context.http


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities from a string."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ").strip()


def _portal_error(e: httpx.HTTPError) -> ToolError:
    """Translate an upstream portal failure into a client-visible tool error.

    The result is raised, never returned. A returned string is delivered to the
    client as a *successful* tool result, leaving the caller unable to tell a
    portal outage from a genuine empty result set.
    """
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return ToolError(
                "Resource not found. Check that the scholar ID is correct."
            )
        if status == 400:
            return ToolError(f"Bad request — {e.response.text[:200]}")
        if status == 429:
            return ToolError("Rate limit exceeded. Please wait before retrying.")
        return ToolError(f"Portal returned status {status}")
    if isinstance(e, httpx.TimeoutException):
        return ToolError("Request timed out. Please try again.")
    return ToolError(f"Could not reach the portal — {type(e).__name__}: {e}")


def _unwrap(value: object, key: str) -> str | None:
    """Pull a scalar out of a field the portal may return wrapped.

    Some profile fields arrive as objects rather than strings — `orcid` as
    {"value", "uri"} and `emailAddress` as {"address"} (observed 2026-08-04).
    Returns the value as-is when it is already scalar.
    """
    if isinstance(value, dict):
        return value.get(key)
    return value


def _normalize_scholar_id(scholar_id: str) -> str:
    """Reduce a scholar identifier to the numeric form the portal expects.

    Search results expose both a numeric id ('17964') and a URL-style id
    ('17964-michael-guerzhoy'); either is accepted anywhere a scholar id is.
    """
    return scholar_id.split("-")[0]


def _format_scholar_summary(scholar: dict) -> dict:
    """Extract a compact summary of a scholar from a search result."""
    about = scholar.get("tabSummaryAbout", {})
    bio = _strip_html(about.get("value", "")) if about else ""
    if len(bio) > 300:
        bio = bio[:300].rsplit(" ", 1)[0] + "…"

    positions = [
        p.get("department", "") + " — " + p.get("position", "")
        for p in scholar.get("positions", [])
    ]
    tags = [t["value"] for t in scholar.get("tags", {}).get("explicit", [])]

    return {
        "id": scholar.get("discoveryId"),
        "url_id": scholar.get("discoveryUrlId"),
        "name": scholar.get("firstNameLastName"),
        "positions": positions,
        "tags": tags,
        "bio_excerpt": bio,
        "availability": scholar.get("customFilterThree", []),
        "profile_url": f"{BASE_URL}/{scholar.get('discoveryUrlId', '')}",
    }


# ─── Input models ───────────────────────────────────────────────────────────────


class SearchScholarsInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"
    )

    query: str = Field(
        ...,
        description="Search query — name, subject, discipline, or topic (e.g. 'climate change', 'Susan Abbey', 'machine learning')",
        min_length=1,
        max_length=200,
    )
    search_by: str = Field(
        default="text",
        description="How to interpret the query: 'text' for full-text keyword search, 'name' for scholar name search",
        pattern=r"^(text|name)$",
    )
    department_filter: str | None = Field(
        default=None,
        description="Filter results to a specific faculty/department (e.g. 'Faculty of Arts and Science, Department of Chemistry'). Use exact values returned by discover_get_filter_options.",
    )
    tag_filter: str | None = Field(
        default=None,
        description="Filter results by a research tag/topic (e.g. 'Machine learning', 'Cancer'). Use exact values from discover_get_filter_options.",
    )
    availability_filter: str | None = Field(
        default=None,
        description="Filter by availability type (e.g. 'Media enquiries', 'Industry Projects'). Use exact values from discover_get_filter_options.",
    )
    page: int = Field(default=1, description="Page number (1-indexed)", ge=1)
    per_page: int = Field(
        default=20, description="Results per page (max 100)", ge=1, le=100
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class GetScholarInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"
    )

    scholar_id: str = Field(
        ...,
        description="The numeric scholar ID from search results (e.g. '17964') or the full URL ID (e.g. '17964-michael-guerzhoy')",
        min_length=1,
    )


class GetPublicationsInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"
    )

    scholar_id: str = Field(
        ...,
        description="The numeric scholar ID (e.g. '17964'). Use the 'id' field from search results.",
        min_length=1,
    )
    page: int = Field(default=1, description="Page number (1-indexed)", ge=1)
    per_page: int = Field(
        default=25, description="Results per page (max 100)", ge=1, le=100
    )
    sort: str = Field(
        default="dateDesc",
        description="Sort order: 'dateDesc' (newest first), 'dateAsc' (oldest first)",
        pattern=r"^(dateDesc|dateAsc)$",
    )


class GetGrantsInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"
    )

    scholar_id: str = Field(
        ...,
        description="The numeric scholar ID (e.g. '1545'). Use the 'id' field from search results.",
        min_length=1,
    )
    page: int = Field(default=1, description="Page number (1-indexed)", ge=1)
    per_page: int = Field(
        default=25, description="Results per page (max 100)", ge=1, le=100
    )


class GetFilterOptionsInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True, validate_assignment=True, extra="forbid"
    )

    query: str = Field(
        default="",
        description="Optional search query to scope the filter options (leave empty for global options)",
        max_length=200,
    )
    filter_type: str = Field(
        default="tags",
        description="Which filter to retrieve options for: 'tags' (research topics), 'department' (faculty/unit), 'customFilterThree' (availability)",
        pattern=r"^(tags|department|customFilterThree|customFilterFour|customFilterFive)$",
    )


# ─── Output models ──────────────────────────────────────────────────────────────
#
# These drive the published output schemas.
#
# Optional types are required where a field is read without a default and is
# simply missing for some records — `id`, `name`, `year` — and where `email`
# and `orcid` are unwrapped from objects the portal may not send at all.
#
# Sampled on 2026-08-04 (25 grants, 25 publications, 2 profiles): `amount` was
# missing from all 25 grants, `doi` from 7 publications and `journal` from 4,
# and `emailAddress` from one profile. Those were absent keys rather than
# explicit nulls, so the `.get` defaults do apply and the values arrive as "".
# The optional types on those particular fields are therefore defensive — the
# sample is 25 records per endpoint, not the whole portal.


class ScholarSummary(BaseModel):
    """One scholar as returned by search."""

    id: str | None = Field(default=None, description="Numeric id for the other tools")
    url_id: str | None = Field(default=None, description="Slug used in the profile URL")
    name: str | None = None
    positions: list[str] = Field(
        default_factory=list, description="'Department — Position Title'"
    )
    tags: list[str] = Field(default_factory=list, description="Research topic tags")
    bio_excerpt: str = ""
    availability: list[str] = Field(default_factory=list)
    profile_url: str = ""


class SearchResult(BaseModel):
    total: int
    page: int
    per_page: int
    has_more: bool
    scholars: list[ScholarSummary] = Field(default_factory=list)


class Degree(BaseModel):
    name: str = ""
    institution: str = ""


class ScholarProfile(BaseModel):
    """A scholar's full profile."""

    id: str | None = None
    name: str | None = None
    profile_url: str = ""
    bio: str = ""
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    orcid: str | None = None
    elements_profile_url: str | None = None
    positions: list[dict] = Field(default_factory=list)
    academic_appointments: list[dict] = Field(default_factory=list)
    non_academic_appointments: list[dict] = Field(default_factory=list)
    degrees: list[Degree] = Field(default_factory=list)
    research_topics: list[str] = Field(default_factory=list)
    availability: list[str] = Field(default_factory=list)
    personal_websites: list[dict] = Field(default_factory=list)
    publication_count: int = 0
    grant_count: int = 0
    professional_activity_count: int = 0
    teaching_summary: str = ""
    grants_summary: str = ""


class Publication(BaseModel):
    id: str | None = None
    title: str | None = None
    type: str | None = Field(default=None, description="e.g. 'Journal article'")
    year: int | None = None
    authors: str = ""
    journal: str | None = None
    abstract: str = ""
    doi: str | None = None
    url: str | None = None


class PublicationsResult(BaseModel):
    scholar_id: str
    total: int
    page: int
    per_page: int
    has_more: bool
    publications: list[Publication] = Field(default_factory=list)


class Grant(BaseModel):
    id: str | None = None
    title: str | None = None
    type: str | None = Field(
        default=None, description="e.g. 'Sponsored Research Agreement'"
    )
    funder: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    amount: str | None = None


class GrantsResult(BaseModel):
    scholar_id: str
    total: int
    page: int
    per_page: int
    has_more: bool
    grants: list[Grant] = Field(default_factory=list)


class FilterOption(BaseModel):
    value: str = Field(description="Exact string to pass as a search filter")
    count: int = Field(description="Number of matching scholars")


class FilterOptionsResult(BaseModel):
    filter_type: str
    query: str
    options: list[FilterOption] = Field(default_factory=list)
    note: str | None = None


# ─── Tools ───────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="discover_search_scholars",
    annotations={
        "title": "Search U of T Scholars",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_search_scholars(
    params: SearchScholarsInput, ctx: Context
) -> SearchResult:
    """Search for University of Toronto scholars by name, subject, discipline, or topic.

    Returns a paginated list of matching scholar profiles with basic info. Use
    discover_get_scholar for full details on one scholar, and
    discover_get_filter_options to look up exact values for the filters.

    Result JSON carries total, page, per_page, has_more, and a scholars list
    whose entries each have: id (pass this to the other scholar tools), url_id,
    name, positions ("Department — Position Title"), tags, bio_excerpt,
    availability, and profile_url.

    For example: "Find scholars working on climate change" becomes
    query="climate change". "Search for professor Susan Abbey" becomes
    query="Susan Abbey", search_by="name". "Find ML researchers in Engineering"
    becomes query="machine learning" with department_filter set to the exact
    faculty string from discover_get_filter_options.
    """
    start_from = (params.page - 1) * params.per_page

    filters = []
    for f in DEFAULT_FILTERS:
        entry = dict(f)
        # Apply tag filter
        if params.tag_filter and f["name"] == "tags":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [params.tag_filter]
        # Apply department filter
        elif params.department_filter and f["name"] == "department":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [params.department_filter]
        # Apply availability filter (customFilterThree)
        elif params.availability_filter and f["name"] == "customFilterThree":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [params.availability_filter]
        filters.append(entry)

    payload = {
        "params": {
            "by": params.search_by,
            "category": "user",
            "text": params.query,
        },
        "filters": filters,
        # The portal defaults to 25 records when no page size is expressed, so
        # per_page must be sent or offsets computed from it will overlap pages.
        # The top-level startFrom is retained: perPage is verified to work
        # alongside it, but pagination.startFrom alone is not verified to drive
        # the offset.
        "startFrom": start_from,
        "pagination": {"perPage": params.per_page, "startFrom": start_from},
    }

    try:
        resp = await _http(ctx).post(f"{API_URL}/users", json=payload)
        resp.raise_for_status()
        data = resp.json()

        pagination = data.get("pagination", {})
        total = pagination.get("total", 0)
        resources = data.get("resource", [])

        scholars = [_format_scholar_summary(s) for s in resources]

        return SearchResult(
            total=total,
            page=params.page,
            per_page=params.per_page,
            has_more=total > start_from + len(resources),
            scholars=scholars,
        )

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


@mcp.tool(
    name="discover_get_scholar",
    annotations={
        "title": "Get U of T Scholar Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar(
    params: GetScholarInput, ctx: Context
) -> ScholarProfile:
    """Retrieve the full profile for a University of Toronto scholar.

    Returns bio, positions, degrees, contact details, research areas, and counts
    of linked publications and grants.

    Result JSON carries: id, name, profile_url, bio (plain text), email, phone,
    address, orcid, positions, academic_appointments, degrees, research_topics,
    availability, personal_websites, elements_profile_url, publication_count,
    grant_count, teaching_summary, and grants_summary.

    For example: after finding a scholar in search results, pass their id here
    for full detail — "Get the full profile for scholar 17964" becomes
    scholar_id="17964". Either the numeric id or the URL-style id
    ("17964-michael-guerzhoy") is accepted.
    """
    numeric_id = _normalize_scholar_id(params.scholar_id)

    try:
        resp = await _http(ctx).get(f"{API_URL}/users/{numeric_id}")
        resp.raise_for_status()
        data = resp.json()

        linked = data.get("linkedObjectIds", {})
        tags = [t["value"] for t in data.get("tags", {}).get("explicit", [])]
        degrees = [
            {
                "name": d.get("name", ""),
                "institution": d.get("institution", {}).get("organisation", ""),
            }
            for d in data.get("degrees", [])
        ]
        phones = data.get("phoneNumbers", [])
        phone = phones[0].get("number", "") if phones else ""
        addresses = data.get("addresses", [])
        address = addresses[0].get("singleLineFormat", "") if addresses else ""

        teaching = data.get("tabSummaryTeachingActivities", {})
        grants_summary = data.get("tabSummaryGrants", {})

        # `or []` rather than a .get default, so a null collection is handled
        # as well as a missing one. The sampled profiles sent lists, but a
        # default only covers the absent-key case.
        return ScholarProfile(
            id=data.get("discoveryId"),
            name=data.get("firstNameLastName"),
            profile_url=f"{BASE_URL}/{data.get('discoveryUrlId', numeric_id)}",
            bio=_strip_html(data.get("tabSummaryAbout", {}).get("value", "")),
            email=_unwrap(data.get("emailAddress"), "address"),
            phone=phone,
            address=address,
            orcid=_unwrap(data.get("orcid"), "value"),
            elements_profile_url=_unwrap(data.get("elementsUserProfileUrl"), "uri"),
            positions=data.get("positions") or [],
            academic_appointments=data.get("academicAppointments") or [],
            non_academic_appointments=data.get("nonAcademicAppointments") or [],
            degrees=degrees,
            research_topics=tags,
            availability=data.get("customFilterThree") or [],
            personal_websites=data.get("personalWebsites") or [],
            publication_count=len(linked.get("publications") or []),
            grant_count=len(linked.get("grants") or []),
            professional_activity_count=len(linked.get("professionalActivities") or []),
            teaching_summary=_strip_html(teaching.get("value", "")) if teaching else "",
            grants_summary=_strip_html(grants_summary.get("value", ""))
            if grants_summary
            else "",
        )

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


@mcp.tool(
    name="discover_get_scholar_publications",
    annotations={
        "title": "Get Scholar Publications",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar_publications(
    params: GetPublicationsInput, ctx: Context
) -> PublicationsResult:
    """Retrieve publications (scholarly and creative works) for a U of T scholar.

    Result JSON carries scholar_id, total, page, per_page, has_more, and a
    publications list whose entries each have: id, title, type (e.g. "Journal
    article", "Book chapter"), year, authors, journal, abstract, doi, and url.

    For example: "List recent papers by scholar 17964" becomes
    scholar_id="17964". "Find their oldest publications first" adds
    sort="dateAsc". Either the numeric id or the URL-style id is accepted.
    """
    scholar_id = _normalize_scholar_id(params.scholar_id)
    start_from = (params.page - 1) * params.per_page
    payload = {
        "objectId": scholar_id,
        "category": "user",
        "pagination": {"perPage": params.per_page, "startFrom": start_from},
        "sort": params.sort,
        "favouritesFirst": True,
    }

    try:
        resp = await _http(ctx).post(f"{API_URL}/publications/linkedTo", json=payload)
        resp.raise_for_status()
        data = resp.json()

        pagination = data.get("pagination", {})
        total = pagination.get("total", 0) if pagination else 0
        resources = data.get("resource", [])

        pubs = []
        for p in resources:
            date1 = p.get("date1", {})
            year = date1.get("year") if date1 else None

            authors_list = p.get("authors", [])
            authors = ", ".join(
                a.get("displayName", "") for a in authors_list if a.get("displayName")
            )

            pubs.append(
                {
                    "id": p.get("discoveryId"),
                    "title": p.get("title", ""),
                    "type": p.get("objectTypeDisplayName", ""),
                    "year": year,
                    "authors": authors,
                    "journal": p.get("journal", p.get("publisherName", "")),
                    "abstract": _strip_html(p.get("abstract", ""))[:500]
                    if p.get("abstract")
                    else "",
                    "doi": p.get("doi", ""),
                    "url": p.get("url", ""),
                }
            )

        return PublicationsResult(
            scholar_id=scholar_id,
            total=total,
            page=params.page,
            per_page=params.per_page,
            has_more=total > start_from + len(resources),
            publications=pubs,
        )

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


@mcp.tool(
    name="discover_get_scholar_grants",
    annotations={
        "title": "Get Scholar Research Grants",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar_grants(
    params: GetGrantsInput, ctx: Context
) -> GrantsResult:
    """Retrieve research grants for a University of Toronto scholar.

    Result JSON carries scholar_id, total, page, per_page, has_more, and a
    grants list whose entries each have: id, title, type (e.g. "Sponsored
    Research Agreement"), funder, start_year, end_year, and amount.

    For example: "What grants does scholar 1545 hold?" becomes
    scholar_id="1545". Either the numeric id or the URL-style id is accepted.
    """
    scholar_id = _normalize_scholar_id(params.scholar_id)
    start_from = (params.page - 1) * params.per_page
    payload = {
        "objectId": scholar_id,
        "category": "user",
        "pagination": {"perPage": params.per_page, "startFrom": start_from},
        "sort": "dateDesc",
        "favouritesFirst": True,
    }

    try:
        resp = await _http(ctx).post(f"{API_URL}/grants/linkedTo", json=payload)
        resp.raise_for_status()
        data = resp.json()

        pagination = data.get("pagination", {})
        total = pagination.get("total", 0) if pagination else 0
        resources = data.get("resource", [])

        grants = []
        for g in resources:
            date1 = g.get("date1", {})
            date2 = g.get("date2", {})
            grants.append(
                {
                    "id": g.get("discoveryId"),
                    "title": g.get("title", ""),
                    "type": g.get("objectTypeDisplayName", ""),
                    "funder": g.get("funderName", ""),
                    "start_year": date1.get("year") if date1 else None,
                    "end_year": date2.get("year") if date2 else None,
                    "amount": g.get("amount", ""),
                }
            )

        return GrantsResult(
            scholar_id=scholar_id,
            total=total,
            page=params.page,
            per_page=params.per_page,
            has_more=total > start_from + len(resources),
            grants=grants,
        )

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


@mcp.tool(
    name="discover_get_filter_options",
    annotations={
        "title": "Get Available Search Filter Options",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_filter_options(
    params: GetFilterOptionsInput, ctx: Context
) -> FilterOptionsResult:
    """Get the available filter values for scholar search (departments, tags, availability types).

    Call this before discover_search_scholars to discover valid filter values:
    its filters match on exact strings, so guessed values return nothing. The
    filter types are 'tags' (research topics such as "Machine learning"),
    'department' (faculty and unit names), and 'customFilterThree'
    (availability, such as "Media enquiries").

    Result JSON carries filter_type, query, and an options list whose entries
    have value — the exact string to pass as a filter — and count, the number
    of matching scholars.

    For example: "What research topics can I filter by?" becomes
    filter_type="tags". "List all departments" becomes
    filter_type="department". "Which ML researchers take media enquiries?"
    becomes query="machine learning", filter_type="customFilterThree".
    """
    # Build filters requesting options for the target filter type
    filters = []
    for f in DEFAULT_FILTERS:
        if f["name"] in (
            "department",
            "tags",
            "customFilterThree",
            "customFilterFour",
            "customFilterFive",
        ):
            filters.append(
                {
                    "name": f["name"],
                    "matchDocsWithMissingValues": True,
                    "useValuesToFilter": False,
                }
            )

    payload = {
        "params": {
            "by": "text",
            "category": "user",
            "text": params.query,
        },
        "filters": filters,
        "startFrom": 0,
    }

    try:
        resp = await _http(ctx).post(f"{API_URL}/users", json=payload)
        resp.raise_for_status()
        data = resp.json()

        response_filters = data.get("filters", [])
        target = next(
            (f for f in response_filters if f.get("name") == params.filter_type), None
        )

        if not target:
            return FilterOptionsResult(
                filter_type=params.filter_type,
                query=params.query,
                note=f"No options found for filter type '{params.filter_type}'",
            )

        options = [
            {"value": opt["value"], "count": opt["count"]}
            for opt in target.get("options") or []
        ]

        return FilterOptionsResult(
            filter_type=params.filter_type,
            query=params.query,
            options=options,
        )

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


if __name__ == "__main__":
    mcp.run()
