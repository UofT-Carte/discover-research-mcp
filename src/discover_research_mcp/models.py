"""The shapes tools accept and return.

Output models drive the published output schemas; the parameter aliases keep
one definition of arguments shared across tools. No portal or protocol
knowledge belongs here.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# ─── Shared parameter types ─────────────────────────────────────────────────────

ScholarId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    Field(
        description="Scholar ID from search results — either the numeric form (e.g. '17964') or the URL-style form (e.g. '17964-michael-guerzhoy'). Both are accepted by every scholar tool."
    ),
]
PageNumber = Annotated[int, Field(description="Page number (1-indexed)", ge=1)]
PageSize = Annotated[int, Field(description="Results per page (max 100)", ge=1, le=100)]


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
