"""
MCP Server for University of Toronto Discover Research portal.

Provides tools to search for U of T scholars and retrieve their profiles,
publications, and research grants.
"""

import json

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, field_validator

mcp = FastMCP("discover_research_mcp")

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
async def discover_search_scholars(params: SearchScholarsInput) -> str:
    """Search for University of Toronto scholars by name, subject, discipline, or topic.

    Returns a paginated list of matching scholar profiles with basic info.
    Use discover_get_scholar to retrieve full details for a specific scholar.

    Args:
        params (SearchScholarsInput):
            - query (str): Search text — can be a name, topic, or keyword
            - search_by (str): 'text' for keyword search, 'name' for name search (default: 'text')
            - department_filter (Optional[str]): Exact department name to filter by
            - tag_filter (Optional[str]): Exact research tag to filter by
            - availability_filter (Optional[str]): Exact availability type to filter by
            - page (int): Page number, 1-indexed (default: 1)
            - per_page (int): Results per page, 1–100 (default: 20)

    Returns:
        str: JSON with:
        {
            "total": int,
            "page": int,
            "per_page": int,
            "has_more": bool,
            "scholars": [
                {
                    "id": str,            # numeric ID for use with other tools
                    "url_id": str,        # slug used in the profile URL
                    "name": str,
                    "positions": [str],   # "Department — Position Title"
                    "tags": [str],        # research topic tags
                    "bio_excerpt": str,
                    "availability": [str],
                    "profile_url": str
                }
            ]
        }

    Examples:
        - "Find scholars working on climate change" → query="climate change"
        - "Search for professor Susan Abbey" → query="Susan Abbey", search_by="name"
        - "Find ML researchers in Engineering" → query="machine learning", department_filter="Faculty of Applied Science and Engineering..."
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_URL}/users",
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

        pagination = data.get("pagination", {})
        total = pagination.get("total", 0)
        resources = data.get("resource", [])

        scholars = [_format_scholar_summary(s) for s in resources]

        result = {
            "total": total,
            "page": params.page,
            "per_page": params.per_page,
            "has_more": total > start_from + len(resources),
            "scholars": scholars,
        }
        return json.dumps(result, indent=2)

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
async def discover_get_scholar(params: GetScholarInput) -> str:
    """Retrieve the full profile for a University of Toronto scholar.

    Returns detailed information including bio, positions, degrees, contact details,
    research areas, and counts of linked publications and grants.

    Args:
        params (GetScholarInput):
            - scholar_id (str): Numeric ID (e.g. '17964') from search results

    Returns:
        str: JSON with full scholar profile:
        {
            "id": str,
            "name": str,
            "profile_url": str,
            "bio": str,          # plain-text biography
            "email": str,
            "phone": str,
            "address": str,
            "orcid": str,
            "positions": [{"position": str, "department": str}],
            "academic_appointments": [...],
            "degrees": [{"name": str, "institution": str}],
            "research_topics": [str],     # tags
            "availability": [str],        # e.g. "Media enquiries"
            "personal_websites": [{"type": str, "label": str, "url": str}],
            "elements_profile_url": str,
            "publication_count": int,
            "grant_count": int,
            "teaching_summary": str,
            "grants_summary": str
        }

    Examples:
        - After finding a scholar in search results, use their 'id' here for full details
        - "Get full profile for scholar 17964" → scholar_id="17964"
    """
    numeric_id = _normalize_scholar_id(params.scholar_id)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_URL}/users/{numeric_id}",
                headers=HEADERS,
                timeout=TIMEOUT,
            )
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

        profile = {
            "id": data.get("discoveryId"),
            "name": data.get("firstNameLastName"),
            "profile_url": f"{BASE_URL}/{data.get('discoveryUrlId', numeric_id)}",
            "bio": _strip_html(data.get("tabSummaryAbout", {}).get("value", "")),
            "email": data.get("emailAddress", ""),
            "phone": phone,
            "address": address,
            "orcid": data.get("orcid", ""),
            "elements_profile_url": data.get("elementsUserProfileUrl", ""),
            "positions": data.get("positions", []),
            "academic_appointments": data.get("academicAppointments", []),
            "non_academic_appointments": data.get("nonAcademicAppointments", []),
            "degrees": degrees,
            "research_topics": tags,
            "availability": data.get("customFilterThree", []),
            "personal_websites": data.get("personalWebsites", []),
            "publication_count": len(linked.get("publications", [])),
            "grant_count": len(linked.get("grants", [])),
            "professional_activity_count": len(
                linked.get("professionalActivities", [])
            ),
            "teaching_summary": _strip_html(teaching.get("value", ""))
            if teaching
            else "",
            "grants_summary": _strip_html(grants_summary.get("value", ""))
            if grants_summary
            else "",
        }
        return json.dumps(profile, indent=2)

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
async def discover_get_scholar_publications(params: GetPublicationsInput) -> str:
    """Retrieve publications (scholarly and creative works) for a U of T scholar.

    Args:
        params (GetPublicationsInput):
            - scholar_id (str): Numeric scholar ID (e.g. '17964')
            - page (int): Page number, 1-indexed (default: 1)
            - per_page (int): Results per page, 1–100 (default: 25)
            - sort (str): 'dateDesc' newest first or 'dateAsc' oldest first (default: 'dateDesc')

    Returns:
        str: JSON with:
        {
            "scholar_id": str,
            "total": int,
            "page": int,
            "per_page": int,
            "has_more": bool,
            "publications": [
                {
                    "id": str,
                    "title": str,
                    "type": str,          # e.g. "Journal article", "Book chapter"
                    "year": int,
                    "authors": str,
                    "journal": str,
                    "abstract": str,
                    "doi": str,
                    "url": str
                }
            ]
        }

    Examples:
        - "List recent papers by scholar 17964" → scholar_id="17964"
        - "Find oldest publications" → scholar_id="17964", sort="dateAsc"
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_URL}/publications/linkedTo",
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT,
            )
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

        result = {
            "scholar_id": scholar_id,
            "total": total,
            "page": params.page,
            "per_page": params.per_page,
            "has_more": total > start_from + len(resources),
            "publications": pubs,
        }
        return json.dumps(result, indent=2)

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
async def discover_get_scholar_grants(params: GetGrantsInput) -> str:
    """Retrieve research grants for a University of Toronto scholar.

    Args:
        params (GetGrantsInput):
            - scholar_id (str): Numeric scholar ID (e.g. '1545')
            - page (int): Page number, 1-indexed (default: 1)
            - per_page (int): Results per page, 1–100 (default: 25)

    Returns:
        str: JSON with:
        {
            "scholar_id": str,
            "total": int,
            "page": int,
            "per_page": int,
            "has_more": bool,
            "grants": [
                {
                    "id": str,
                    "title": str,
                    "type": str,          # e.g. "Sponsored Research Agreement"
                    "funder": str,
                    "start_year": int,
                    "end_year": int,
                    "amount": str
                }
            ]
        }

    Examples:
        - "What grants does scholar 1545 have?" → scholar_id="1545"
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_URL}/grants/linkedTo",
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT,
            )
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

        result = {
            "scholar_id": scholar_id,
            "total": total,
            "page": params.page,
            "per_page": params.per_page,
            "has_more": total > start_from + len(resources),
            "grants": grants,
        }
        return json.dumps(result, indent=2)

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
async def discover_get_filter_options(params: GetFilterOptionsInput) -> str:
    """Get the available filter values for scholar search (departments, tags, availability types).

    Use this to discover valid filter values before passing them to discover_search_scholars.

    Args:
        params (GetFilterOptionsInput):
            - query (str): Optional query to scope filter options (default: '' for all scholars)
            - filter_type (str): Which filter options to return:
                - 'tags' — research topic tags (e.g. 'Machine learning', 'Cancer')
                - 'department' — faculty/unit names
                - 'customFilterThree' — availability types (e.g. 'Media enquiries')

    Returns:
        str: JSON with:
        {
            "filter_type": str,
            "query": str,
            "options": [
                {
                    "value": str,    # use this exact string in discover_search_scholars filters
                    "count": int     # number of matching scholars
                }
            ]
        }

    Examples:
        - "What research topics can I filter by?" → filter_type="tags"
        - "List all departments" → filter_type="department"
        - "Find media-available scholars in ML" → query="machine learning", filter_type="customFilterThree"
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_URL}/users",
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

        response_filters = data.get("filters", [])
        target = next(
            (f for f in response_filters if f.get("name") == params.filter_type), None
        )

        if not target:
            return json.dumps(
                {
                    "filter_type": params.filter_type,
                    "query": params.query,
                    "options": [],
                    "note": f"No options found for filter type '{params.filter_type}'",
                },
                indent=2,
            )

        options = [
            {"value": opt["value"], "count": opt["count"]}
            for opt in target.get("options", [])
        ]

        result = {
            "filter_type": params.filter_type,
            "query": params.query,
            "options": options,
        }
        return json.dumps(result, indent=2)

    except httpx.HTTPError as e:
        raise _portal_error(e) from e


if __name__ == "__main__":
    mcp.run()
