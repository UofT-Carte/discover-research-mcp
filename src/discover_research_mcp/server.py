"""
MCP Server for University of Toronto Discover Research portal.

Provides tools to search for U of T scholars and retrieve their profiles,
publications, and research grants.
"""

from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.server.middleware.caching import ResponseCachingMiddleware
from fastmcp.server.middleware.error_handling import RetryMiddleware
from pydantic import Field, StringConstraints

from .models import (
    FilterOptionsResult,
    GrantsResult,
    PageNumber,
    PageSize,
    PublicationsResult,
    ScholarId,
    ScholarProfile,
    SearchResult,
)
from .portal import (
    API_URL,
    BASE_URL,
    DEFAULT_FILTERS,
    RETRY_ATTEMPTS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_EXCEPTIONS,
    fetch_grants,
    fetch_publications,
    format_scholar_summary,
    http_client,
    lifespan,
    normalize_scholar_id,
    portal_error,
    strip_html,
    unwrap,
)

# A per-attempt ceiling on everything a tool does, HTTP or not. Set above the
# read timeout so the HTTP layer fails first with a specific diagnostic and
# this only catches hangs the HTTP timeouts cannot see.
TOOL_TIMEOUT_SECONDS = 35.0

# Scholar records change on the order of weeks, so a short cache costs nothing
# in freshness while sparing the portal repeated identical lookups.
RESPONSE_CACHE_TTL_SECONDS = 900


def build_response_cache() -> ResponseCachingMiddleware:
    """Cache successful tool results for a short window.

    Only successful results are ever stored: the caching middleware performs no
    error check before caching, but a failure raised out of a tool propagates
    past it and is never written. That is why portal failures raise rather than
    return — returning an error value here would memoise it for the full TTL.

    Exposed as a factory so tests can reset cache state between cases.
    """
    return ResponseCachingMiddleware(
        call_tool_settings={"enabled": True, "ttl": RESPONSE_CACHE_TTL_SECONDS},
    )


mcp = FastMCP("discover_research_mcp", lifespan=lifespan)

# Cache first so a hit short-circuits before any retry bookkeeping.
mcp.add_middleware(build_response_cache())
mcp.add_middleware(
    RetryMiddleware(
        max_retries=RETRY_ATTEMPTS,
        base_delay=RETRY_BASE_DELAY_SECONDS,
        retry_exceptions=RETRY_EXCEPTIONS,
    )
)


# ─── Tools ───────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="discover_search_scholars",
    timeout=TOOL_TIMEOUT_SECONDS,
    annotations={
        "title": "Search U of T Scholars",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_search_scholars(
    ctx: Context,
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        Field(
            description="Search query — name, subject, discipline, or topic (e.g. 'climate change', 'Susan Abbey', 'machine learning')"
        ),
    ],
    search_by: Annotated[
        str,
        Field(
            description="How to interpret the query: 'text' for full-text keyword search, 'name' for scholar name search",
            pattern=r"^(text|name)$",
        ),
    ] = "text",
    department_filter: Annotated[
        str | None,
        Field(
            description="Filter results to a specific faculty/department (e.g. 'Faculty of Arts and Science, Department of Chemistry'). Use exact values returned by discover_get_filter_options."
        ),
    ] = None,
    tag_filter: Annotated[
        str | None,
        Field(
            description="Filter results by a research tag/topic (e.g. 'Machine learning', 'Cancer'). Use exact values from discover_get_filter_options."
        ),
    ] = None,
    availability_filter: Annotated[
        str | None,
        Field(
            description="Filter by availability type (e.g. 'Media enquiries', 'Industry Projects'). Use exact values from discover_get_filter_options."
        ),
    ] = None,
    page: PageNumber = 1,
    per_page: PageSize = 20,
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
    start_from = (page - 1) * per_page

    filters = []
    for f in DEFAULT_FILTERS:
        entry = dict(f)
        # Apply tag filter
        if tag_filter and f["name"] == "tags":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [tag_filter]
        # Apply department filter
        elif department_filter and f["name"] == "department":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [department_filter]
        # Apply availability filter (customFilterThree)
        elif availability_filter and f["name"] == "customFilterThree":
            entry["useValuesToFilter"] = True
            entry["matchDocsWithMissingValues"] = False
            entry["values"] = [availability_filter]
        filters.append(entry)

    payload = {
        "params": {
            "by": search_by,
            "category": "user",
            "text": query,
        },
        "filters": filters,
        # The portal defaults to 25 records when no page size is expressed, so
        # per_page must be sent or offsets computed from it will overlap pages.
        # The top-level startFrom is retained: perPage is verified to work
        # alongside it, but pagination.startFrom alone is not verified to drive
        # the offset.
        "startFrom": start_from,
        "pagination": {"perPage": per_page, "startFrom": start_from},
    }

    try:
        resp = await http_client(ctx).post(f"{API_URL}/users", json=payload)
        resp.raise_for_status()
        data = resp.json()

        pagination = data.get("pagination", {})
        total = pagination.get("total", 0)
        resources = data.get("resource", [])

        scholars = [format_scholar_summary(s) for s in resources]

        return SearchResult(
            total=total,
            page=page,
            per_page=per_page,
            has_more=total > start_from + len(resources),
            scholars=scholars,
        )

    except httpx.HTTPError as e:
        raise portal_error(e) from e


@mcp.tool(
    name="discover_get_scholar",
    timeout=TOOL_TIMEOUT_SECONDS,
    annotations={
        "title": "Get U of T Scholar Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar(ctx: Context, scholar_id: ScholarId) -> ScholarProfile:
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
    numeric_id = normalize_scholar_id(scholar_id)

    try:
        resp = await http_client(ctx).get(f"{API_URL}/users/{numeric_id}")
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
            bio=strip_html(data.get("tabSummaryAbout", {}).get("value", "")),
            email=unwrap(data.get("emailAddress"), "address"),
            phone=phone,
            address=address,
            orcid=unwrap(data.get("orcid"), "value"),
            elements_profile_url=unwrap(data.get("elementsUserProfileUrl"), "uri"),
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
            teaching_summary=strip_html(teaching.get("value", "")) if teaching else "",
            grants_summary=strip_html(grants_summary.get("value", ""))
            if grants_summary
            else "",
        )

    except httpx.HTTPError as e:
        raise portal_error(e) from e


@mcp.tool(
    name="discover_get_scholar_publications",
    timeout=TOOL_TIMEOUT_SECONDS,
    annotations={
        "title": "Get Scholar Publications",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar_publications(
    ctx: Context,
    scholar_id: ScholarId,
    page: PageNumber = 1,
    per_page: PageSize = 25,
    sort: Annotated[
        str,
        Field(
            description="Sort order: 'dateDesc' (newest first), 'dateAsc' (oldest first)",
            pattern=r"^(dateDesc|dateAsc)$",
        ),
    ] = "dateDesc",
) -> PublicationsResult:
    """Retrieve publications (scholarly and creative works) for a U of T scholar.

    Result JSON carries scholar_id, total, page, per_page, has_more, and a
    publications list whose entries each have: id, title, type (e.g. "Journal
    article", "Book chapter"), year, authors, journal, abstract, doi, and url.

    For example: "List recent papers by scholar 17964" becomes
    scholar_id="17964". "Find their oldest publications first" adds
    sort="dateAsc". Either the numeric id or the URL-style id is accepted.
    """
    return await fetch_publications(ctx, scholar_id, page, per_page, sort)


@mcp.tool(
    name="discover_get_scholar_grants",
    timeout=TOOL_TIMEOUT_SECONDS,
    annotations={
        "title": "Get Scholar Research Grants",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_scholar_grants(
    ctx: Context,
    scholar_id: ScholarId,
    page: PageNumber = 1,
    per_page: PageSize = 25,
) -> GrantsResult:
    """Retrieve research grants for a University of Toronto scholar.

    Result JSON carries scholar_id, total, page, per_page, has_more, and a
    grants list whose entries each have: id, title, type (e.g. "Sponsored
    Research Agreement"), funder, start_year, end_year, and amount.

    For example: "What grants does scholar 1545 hold?" becomes
    scholar_id="1545". Either the numeric id or the URL-style id is accepted.
    """
    return await fetch_grants(ctx, scholar_id, page, per_page)


@mcp.tool(
    name="discover_get_filter_options",
    timeout=TOOL_TIMEOUT_SECONDS,
    annotations={
        "title": "Get Available Search Filter Options",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def discover_get_filter_options(
    ctx: Context,
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=200),
        Field(
            description="Optional search query to scope the filter options (leave empty for global options)"
        ),
    ] = "",
    filter_type: Annotated[
        str,
        Field(
            description="Which filter to retrieve options for: 'tags' (research topics), 'department' (faculty/unit), 'customFilterThree' (availability)",
            pattern=r"^(tags|department|customFilterThree|customFilterFour|customFilterFive)$",
        ),
    ] = "tags",
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
            "text": query,
        },
        "filters": filters,
        "startFrom": 0,
    }

    try:
        resp = await http_client(ctx).post(f"{API_URL}/users", json=payload)
        resp.raise_for_status()
        data = resp.json()

        response_filters = data.get("filters", [])
        target = next(
            (f for f in response_filters if f.get("name") == filter_type), None
        )

        if not target:
            return FilterOptionsResult(
                filter_type=filter_type,
                query=query,
                note=f"No options found for filter type '{filter_type}'",
            )

        options = [
            {"value": opt["value"], "count": opt["count"]}
            for opt in target.get("options") or []
        ]

        return FilterOptionsResult(
            filter_type=filter_type,
            query=query,
            options=options,
        )

    except httpx.HTTPError as e:
        raise portal_error(e) from e


def main() -> None:
    """Console entry point: serve over stdio.

    Declared as `discover-research-mcp` in pyproject, so the server can be run
    without cloning: `uvx --from git+<repo> discover-research-mcp`.
    """
    mcp.run()


if __name__ == "__main__":
    main()
