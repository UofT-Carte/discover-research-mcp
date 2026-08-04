"""Everything that talks to the Discover Research portal.

Endpoint addresses, the shared HTTP client and its lifetime, the retry policy,
and the translation of portal payloads and failures into terms the tools use.
Tool definitions live in `server.py`; this module knows nothing about them.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

BASE_URL = "https://discover.research.utoronto.ca"
API_URL = f"{BASE_URL}/api"

# Connect is kept far below read because connection faults are the retried
# class, so the connect timeout is paid once per attempt: a dead host costs
# 3 x 5s rather than 3 x 30s. A slow-but-alive portal is not retried, so the
# read timeout is paid at most once.
PORTAL_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

RETRY_ATTEMPTS = 2
RETRY_BASE_DELAY_SECONDS = 0.5

# Retry only failures to establish or hold a connection.
#
# The middleware default is (ConnectionError, TimeoutError) — Python builtins
# that no httpx exception inherits from, so retry would silently never fire.
#
# ReadTimeout is deliberately absent: the portal accepted the request and is
# merely slow, so retrying re-pays the full read timeout. HTTPStatusError is
# absent too, so definitive answers like 404 are not retried.
RETRY_EXCEPTIONS = (
    httpx.NetworkError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)

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
    async with httpx.AsyncClient(headers=HEADERS, timeout=PORTAL_TIMEOUT) as http:
        yield PortalSession(http=http)


def http_client(ctx: Context) -> httpx.AsyncClient:
    """The shared HTTP client for this server."""
    return ctx.request_context.lifespan_context.http


def strip_html(html: str) -> str:
    """Strip HTML tags and decode entities from a string."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ").strip()


def portal_error(e: httpx.HTTPError) -> ToolError:
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


def unwrap(value: object, key: str) -> str | None:
    """Pull a scalar out of a field the portal may return wrapped.

    Some profile fields arrive as objects rather than strings — `orcid` as
    {"value", "uri"} and `emailAddress` as {"address"} (observed 2026-08-04).
    Returns the value as-is when it is already scalar.
    """
    if isinstance(value, dict):
        return value.get(key)
    return value


def normalize_scholar_id(scholar_id: str) -> str:
    """Reduce a scholar identifier to the numeric form the portal expects.

    Search results expose both a numeric id ('17964') and a URL-style id
    ('17964-michael-guerzhoy'); either is accepted anywhere a scholar id is.
    """
    return scholar_id.split("-")[0]


def format_scholar_summary(scholar: dict) -> dict:
    """Extract a compact summary of a scholar from a search result."""
    about = scholar.get("tabSummaryAbout", {})
    bio = strip_html(about.get("value", "")) if about else ""
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
