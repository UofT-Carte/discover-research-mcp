# Idiomatic FastMCP 3.4.5 design for `discover-research-mcp`

**Retrieval date: 2026-08-04.** Target version: **FastMCP 3.4.5** (released 2026-07-27).

## How to read the citations

Every FastMCP citation below is pinned to the **`v3.4.5` git tag** of `PrefectHQ/fastmcp`
(`jlowin/fastmcp` 301-redirects to it). The live docs site, gofastmcp.com, now serves **v4**
documentation and must not be used for this target. I worked from a shallow clone of the tag:

```
git clone --depth 1 --branch v3.4.5 https://github.com/PrefectHQ/fastmcp.git
# HEAD = 8de0c94cbbe71849c98cef2bbe08cdf498dba09c, dated 2026-07-27  (OBSERVED)
```

Paths map to `https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/<path>`. Note the source lives under
`fastmcp_slim/fastmcp/…`, not `src/fastmcp/…`.

**Evidence labels.** FastMCP 3.4.5 was **not installed and not executed** (the task forbade
installing). So:

- **OBSERVED** — I ran a command and read its output. This applies to the clone itself, to
  `httpx`'s exception hierarchy, and to the *current* behaviour of this repo under its installed
  `mcp` 1.26.0.
- **SOURCE** — I read the exact file at the `v3.4.5` tag and am quoting it. The text is verified;
  the runtime behaviour it implies is not.
- **INFERRED** — reasoned from SOURCE, not verified by running anything.

Anything I could not verify is called out in [§12](#12-what-i-could-not-verify) rather than guessed.

## Relationship to the prior research pass

The migration-mechanics question is already answered in
[`fastmcp-v2-migration.md`](./fastmcp-v2-migration.md) — what breaks, the minimum diff, the
dependency situation, the `mcp` 2.0 hazard. **This document does not restate any of that.** Read it
first for the mechanics; read this one for the redesign.

That pass graded features by whether they were strictly *necessary* and marked several SKIP on that
basis. This pass asks a different question — *how would you write this server today, from scratch,
in 3.4.5* — and **three of those verdicts flip**. They are flagged inline and summarised in
[§11](#11-verdicts-that-differ-from-the-prior-pass).

---

## 0. Summary of verdicts

| # | Area | Verdict | Prior pass |
| --- | --- | --- | --- |
| 1 | Typed returns / structured output | **ADOPT** — typed Pydantic result models | ADOPT (bare `dict` or typed) |
| 2 | `ToolError` for failures | **ADOPT** — correctness fix, not polish | ADOPT |
| 3 | `Context` injection | **ADOPT NARROWLY** — logging only; skip progress/sampling/elicitation | not assessed |
| 4 | Lifespan / shared `httpx.AsyncClient` | **ADOPT** — lifespan + `Depends()` | "follow-up, not migration scope" |
| 5 | Resources vs tools | **SKIP resources; keep 5 tools** | SKIP |
| 6 | Middleware | **ADOPT** — caching + retry are built in | **SKIP** ⟵ *flips* |
| 7 | Server structure | **SKIP composition** (clear). Module split = *optional polish* — 707 lines is inside FastMCP's own 1,000-line gate; justify by testability, not length | SKIP composition |
| 8 | Tool metadata | **ADOPT** — `timeout`, docstring fix, keep annotations; **flat params** (breaking) | "already adopted, zero work" ⟵ *flips* |
| 9 | Testing with `Client(mcp)` | **ADOPT** — alongside `pytest-httpx` | ADOPT (optional) |
| 10 | Anti-patterns | several present | partly covered |

---

## 1. Typed returns and structured output

### How 3.4.5 derives output schemas

FastMCP produces **two things** from every tool call, and the rules are explicit
([`docs/servers/tools.mdx` L509–512](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)) — SOURCE:

> **Automatic Structured Content Rules:**
> - **Object-like results** (`dict`, Pydantic models, dataclasses) → Always become structured content (even without output schema)
> - **Non-object results** (`int`, `str`, `list`) → Only become structured content if there's an output schema to validate/serialize them
> - **All results** → Always become traditional content blocks for backward compatibility

That last line is the client-compatibility answer: **adding structured output does not break
text-only clients.** Content blocks are always emitted. A client that only reads
`content[0].text` keeps working; a client that understands `structuredContent` gets a parsed object
for free.

The schema is generated from the return annotation. For **non-object** returns the result is wrapped
under a `result` key — SOURCE,
[`fastmcp_slim/fastmcp/tools/function_parsing.py` L340–351](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py):

```python
# Generate schema for wrapped type if it's non-object
if wrap_non_object_output_schema and not _is_object_schema(base_schema):
    wrapped_type = _WrappedResult[clean_output_type]
    output_schema = wrapped_adapter.json_schema(...)
    output_schema["x-fastmcp-wrap-result"] = True
else:
    output_schema = base_schema
```

`_is_object_schema` is `schema.get("type") == "object"` plus a properties fallback
([same file, L131–134](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py)).

### Dataclass vs Pydantic model vs `dict` vs `ToolResult`

| Return annotation | Output schema | Verdict for this server |
| --- | --- | --- |
| `-> str` (today) | `{"result": {"type": "string"}}` — "returns a string", semantically empty | **the current state; replace** |
| `-> dict` | object type, **no property detail** | better than `str`, still no contract |
| `-> list[Pub]` | wrapped under `result` with `x-fastmcp-wrap-result` | avoid at top level |
| `-> SomeDataclass` | full field-level schema | fine |
| `-> SomePydanticModel` | full field-level schema | **recommended here** |
| `-> ToolResult` | whatever you set; no auto-wrapping | not needed |

Dataclasses and Pydantic models both yield a real schema — the docs show the dataclass case
generating a full `properties` block
([`tools.mdx` L598–655](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
**Pydantic wins for this repo purely because `pydantic` is already a dependency and already used
for the input models** (`server.py` L14), so it adds no new concept.

`ToolResult` gives explicit control over content / structured data / metadata
([`tools.mdx` L720–782](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx),
example at [`examples/tool_result_echo.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/examples/tool_result_echo.py)).
It is the documented home for **custom serialisation** — and notably the removed `tool_serializer`
constructor kwarg now points at it:

> `"tool_serializer": "Return ToolResult from your tools instead."`
> — SOURCE, [`server/server.py` L157](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)

**SKIP `ToolResult` here.** These five tools return homogeneous JSON-ish records with no mixed
media and no custom format. Typed models give the same structured content with a better schema and
less ceremony. (This agrees with the prior pass.)

### What these five tools should return

Every tool already *builds the right dict* and then destroys it with `json.dumps`. The redesign is
to name those shapes. E.g. for `discover_search_scholars`, whose result dict is assembled at
`server.py` L283–289:

```python
class ScholarSummary(BaseModel):
    id: str | None
    url_id: str | None
    name: str | None
    positions: list[str]
    tags: list[str]
    bio_excerpt: str
    availability: list[str]
    profile_url: str

class ScholarSearchResult(BaseModel):
    total: int
    page: int
    per_page: int
    has_more: bool
    scholars: list[ScholarSummary]

async def discover_search_scholars(...) -> ScholarSearchResult: ...
```

Returning the **envelope model** (not `list[ScholarSummary]`) matters: the envelope is object-typed,
so it produces a clean schema, while a bare list would be wrapped under `result`.

A large bonus: the JSON shapes currently hand-documented in prose in the `Returns:` docstring
sections (`server.py` L208–227, L317–338, L424–444, L536–548, L628–639 — roughly 100 lines of
hand-maintained, unenforced documentation) become **generated schema**. That prose is already at
risk of drifting from the code; §8 shows it is also about to be silently dropped from the tool
description.

---

## 2. Error handling

### The current behaviour is a correctness bug, not a style issue

All five tools end in `except Exception as e: return _handle_error(e)` (`server.py` L292, L399,
L506, L601, L702), and `_handle_error` (L47–59) **returns a string**. On the wire that is a
**successful tool result** whose text begins `"Error: "`. `isError` is never set. The model is not
told the call failed, and neither is any programmatic consumer.

This is the single highest-value fix in this document, and §6 shows it gets worse once caching is
added.

### The idiomatic form

SOURCE, [`docs/servers/tools.mdx` L813–845](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx):

> If your tool encounters an error, you can raise a standard Python exception (`ValueError`,
> `TypeError`, `FileNotFoundError`, custom exceptions, etc.) or a FastMCP `ToolError`.
>
> By default, all exceptions (including their details) are logged and converted into an MCP error
> response to be sent back to the client LLM. This helps the LLM understand failures and react
> appropriately.
>
> Error messages from `ToolError` are always sent to clients, regardless of `mask_error_details`
> setting… When `mask_error_details=True`, only error messages from `ToolError` will include
> details, other exceptions will be converted to a generic message.

The exception hierarchy — SOURCE,
[`fastmcp_slim/fastmcp/exceptions.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/exceptions.py):

```python
class FastMCPError(Exception):
    """Base error for FastMCP."""
    def __init__(self, *args: object, log_level: int = logging.ERROR) -> None:
        super().__init__(*args)
        self.log_level = log_level

class ToolError(FastMCPError):
    """Error in tool operations."""

class NotFoundError(Exception):
    """Object not found."""
```

Two details worth using:

- **`log_level`** is a constructor kwarg on every `FastMCPError`. A 404 on a scholar ID is a normal
  user mistake, not a server fault — `ToolError("…", log_level=logging.WARNING)` keeps the error
  logs meaningful.
- **`NotFoundError`** is mapped by `ErrorHandlingMiddleware` to MCP code `-32001` "Not found"
  (SOURCE, [`middleware/error_handling.py` L98–105](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/error_handling.py)).

### `mask_error_details`

**SKIP.** It defaults off (`mask_error_details: bool | None = None`, SOURCE
[`server/server.py` L336](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)).
This server scrapes a public, unauthenticated portal over local stdio; there are no secrets in a
traceback, and detail helps both the model and the developer. Agrees with the prior pass.

### The correct pattern for a scraper

Distinguish three failure classes, because they warrant different client behaviour:

```python
from fastmcp.exceptions import ToolError

async def _get_json(client: httpx.AsyncClient, ...) -> dict:
    try:
        resp = await client.request(...)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 404:
            # user error: bad scholar ID. Actionable, low-severity.
            raise ToolError(
                "Scholar not found. Check the ID from discover_search_scholars.",
                log_level=logging.WARNING,
            ) from e
        if code == 429:
            raise ToolError("Upstream rate limit hit. Retry shortly.") from e
        raise ToolError(f"Upstream returned HTTP {code}.") from e
    except httpx.TimeoutException as e:
        raise ToolError("Upstream request timed out.") from e
```

**The `from e` is load-bearing, not cosmetic.** `RetryMiddleware` inspects exactly one level of
`__cause__` to decide whether to retry — SOURCE,
[`middleware/error_handling.py` L183–195](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/error_handling.py):

```python
def _should_retry(self, error: Exception) -> bool:
    """...Checks both the error itself and its ``__cause__``, since FastMCP
    wraps tool exceptions as ``ToolError(...) from original``. Only one
    level of cause is inspected — middleware below this one must not
    re-wrap errors with a new ``from`` clause, or the real type will be
    hidden from the retry decision."""
    if isinstance(error, self.retry_exceptions):
        return True
    cause = error.__cause__
    return cause is not None and isinstance(cause, self.retry_exceptions)
```

Raise `ToolError(...)` without `from e` and you permanently disable retry for that failure (§6).

**Parse failures** are the third class and deserve their own handling. In a scraper, a `KeyError`
or `AttributeError` from `_format_scholar_summary` (L62–84) means *the upstream HTML/JSON shape
changed* — a different operational problem from a network blip, and one you do **not** want
retried. Let it raise a distinct error so it is visibly not a transient failure:

```python
class UpstreamShapeError(ToolError):
    """The portal returned a payload we no longer understand."""
```

Today all three classes collapse into one `except Exception` and one indistinguishable string.

### The trap when you adopt this

`except Exception` at L292/L399/L506/L601/L702 will **swallow a `ToolError` raised inside the
`try`** and convert it back to a success string. Either re-raise `ToolError` explicitly or — better
— delete the blanket handlers entirely and let a shared `_get_json` helper own error translation.
Deleting them is the structural fix; re-raising is the patch.

---

## 3. Context — adopt narrowly

### How to inject it, and a docs contradiction worth knowing

3.4.5 documents a **dependency form** as preferred — SOURCE,
[`docs/servers/context.mdx` L33–49](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/context.mdx):

> The preferred way to access context is using the `CurrentContext()` dependency:

```python
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

@mcp.tool
async def process_file(file_uri: str, ctx: Context = CurrentContext()) -> str:
    await ctx.info(f"Processing {file_uri}")
```

…and labels the bare type-hint form **"Legacy Type-Hint Injection… For backwards compatibility"**
([L77–79](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/context.mdx)).

**But every other doc page and the project's own tests use the bare annotation** — including
[`progress.mdx` L23](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/progress.mdx),
[`logging.mdx` L26](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/logging.mdx),
[`lifespan.mdx` L58](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx),
the `Context` class docstring itself
([`context.py` L143–147](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)),
and `tests/client/test_logs.py` / `test_progress.py`. Neither form is deprecated in code.

**Recommendation: use the bare `ctx: Context` annotation.** It is what the lifespan docs you are
copying from use, it is what the codebase uses, and "Legacy" here reads as a docs-consistency lag
rather than a real deprecation. Note the disagreement so the choice is deliberate.

For helper functions, **`get_context()`** avoids threading `ctx` through every signature — SOURCE,
[`server/dependencies.py` L321–328](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/dependencies.py):

```python
def get_context() -> Context:
    """Get the current FastMCP Context instance directly."""
    from fastmcp.server.context import _current_context
    context = _current_context.get()
    if context is None:
        raise RuntimeError("No active context found.")
    return context
```

### The capability surface, triaged for this server

| Capability | API | Verdict here |
| --- | --- | --- |
| **Logging** | `ctx.debug/info/warning/error` ([`context.py` L720–768](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **ADOPT** — the one clear win |
| Progress | `ctx.report_progress(progress, total, message)` ([L389](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **SKIP** — see below |
| Sampling | `ctx.sample(...)` ([L948](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **SKIP** — asking the client's LLM to summarise scraped bios is scope creep; the calling agent can do that |
| Elicitation | `ctx.elicit(...)` ([L1107](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **SKIP** — no interactive decisions; `discover_get_filter_options` already solves "which filter value?" without a round trip |
| Resource access | `ctx.read_resource(uri)` ([L533](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **SKIP** — no resources (§5) |
| Request metadata | `ctx.request_id`, `ctx.client_id`, `ctx.session_id`, `ctx.transport` | **SKIP** — nothing branches on caller identity |
| Lifespan state | `ctx.lifespan_context` ([L353](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **ADOPT** — this is how §4's shared client is reached |
| Session state | `ctx.set_state/get_state` ([L1249](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)) | **SKIP** — caching middleware (§6) covers the memoisation case better |

**Why logging and not progress.** Progress is a **no-op unless the client opts in** — SOURCE,
[`docs/servers/progress.mdx` L47–49](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/progress.mdx):

> Clients must send a `progressToken` in the initial request to receive progress updates. If no
> progress token is provided, progress calls have no effect (they don't error).

Confirmed in source — `report_progress` returns early unless `request_context.meta.progressToken`
is set ([`context.py` L403–418](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)).
More decisively: **these tools are not actually long-running.** Each makes exactly *one* upstream
request (`server.py` L268, L349, L461, L564, L668) with `TIMEOUT = 30.0`. There is no loop to report
progress *through* — there is nothing to report but "started" and "done". Progress earns its place
when a tool iterates pages or files; it would be decoration here.

Logging, by contrast, pays off immediately for a scraper. `ctx.warning("Upstream returned no
`resource` key — portal shape may have changed")` is exactly the diagnostic that today's
`except Exception → "Error: …"` string destroys. Note MCP logging goes to the *client* over the
protocol ([`logging.mdx` L14](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/logging.mdx)),
while FastMCP's own server-side logs are routed to **stderr**, not stdout
([`utilities/logging.py` L65–75](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/utilities/logging.py)) — so
neither pollutes the stdio JSON-RPC stream.

### Background tasks — SKIP

`@mcp.tool(task=True)` implements the MCP background-task protocol
([`docs/servers/tasks.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tasks.mdx)),
but it requires the `fastmcp[tasks]` extra (pydocket), it requires the **client** to implement
SEP-1686, and the in-memory backend is "Ephemeral… ~250ms task pickup… No horizontal scaling"
([`tasks.mdx` L170–172](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tasks.mdx)).
For five sub-30-second read-only calls on local stdio, this is a distributed task scheduler in
exchange for nothing.

`@mcp.tool(timeout=...)` (§8) is the right-sized version of this concern.

---

## 4. Lifespan and shared state — where the shared `httpx.AsyncClient` belongs

### The problem in the current code

Every tool opens and closes its own client:

```python
async with httpx.AsyncClient() as client:   # server.py L267, L348, L460, L563, L667
```

Five separate call sites, one new TCP connection and TLS handshake per tool call, no connection
reuse, and `TIMEOUT`/`HEADERS` re-passed by hand each time. Against a single upstream host this is
pure waste — and a typical agent session hits this server many times in a row.

### The documented answer: `lifespan`

`lifespan=` is a live constructor kwarg (SOURCE,
[`server/server.py` L333](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)),
is **not** in `_REMOVED_KWARGS`, and its doc page carries a `VersionBadge version="3.0.0"`. 3.4.5
adds an `@lifespan` decorator:

> Lifespans let you run code once when the server starts and clean up when it stops. Unlike
> per-session handlers, lifespans run exactly once regardless of how many clients connect.
> — SOURCE, [`docs/servers/lifespan.mdx` L13](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx)

The documented access pattern — SOURCE, verbatim from
[`docs/servers/lifespan.mdx` L44–62](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx):

```python
from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan

@lifespan
async def app_lifespan(server):
    # Initialize shared state
    data = {"users": ["alice", "bob"]}
    yield {"data": data}

mcp = FastMCP("MyServer", lifespan=app_lifespan)

@mcp.tool
def list_users(ctx: Context) -> list[str]:
    data = ctx.lifespan_context["data"]
    return data["users"]
```

"Always use `try/finally` for cleanup code to ensure it runs even if the server is cancelled"
([`lifespan.mdx` L38–40](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx)).
Lifespans also compose with `|` ([L68–84](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx)),
and plain `@asynccontextmanager` lifespans still work ([L91–104](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx)).

Applied here — this replaces all five `async with httpx.AsyncClient()` blocks:

```python
import httpx
from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan

@lifespan
async def http_lifespan(server):
    client = httpx.AsyncClient(base_url=API_URL, headers=HEADERS, timeout=TIMEOUT)
    try:
        yield {"client": client}
    finally:
        await client.aclose()

mcp = FastMCP("discover_research_mcp", lifespan=http_lifespan)

@mcp.tool(...)
async def discover_get_scholar(scholar_id: str, ctx: Context) -> ScholarProfile:
    client: httpx.AsyncClient = ctx.lifespan_context["client"]
    ...
```

Use `ctx.lifespan_context`, **not** `ctx.request_context.lifespan_context`. The latter is an
internal legacy fallback that returns the *parent's* context under mounting — SOURCE,
[`server/context.py` L353–387](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py).

### ⚠️ `Depends()` is the wrong tool here — and it looks right

FastMCP 3.4.5 has a real DI system, `from fastmcp.dependencies import Depends`
([`fastmcp_slim/fastmcp/dependencies.py` L11](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/dependencies.py)),
and its docs contain a "Resource Management" section whose example is *literally an HTTP client
being opened and closed via `@asynccontextmanager`*
([`dependency-injection.mdx` L382–407](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/dependency-injection.mdx)).
It reads like the answer. It is not:

> Dependencies are cached **per-request**. If multiple parameters use the same dependency… it's
> resolved once and the same instance is reused.
> — SOURCE, [`dependency-injection.mdx` L350](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/dependency-injection.mdx)

Per-request. So `client: httpx.AsyncClient = Depends(get_client)` constructs and tears down a client
**on every tool call** — exactly the behaviour you are trying to eliminate, now with more machinery.
`Depends()` is for per-request values (identity, headers, request-scoped handles) and for hiding
parameters from the LLM ([`tools.mdx` L413–434](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).

There *is* an app-scoped primitive, `Shared()`, exported from the same module and proven
app-scoped by the project's own test (`tests/server/test_dependencies.py` L1071–1096 asserts
`enter_count == 1` across two tool calls). **Do not adopt it yet**: it appears nowhere in `docs/`
at this tag, and two source comments disagree about whether its scope is app-wide or per-request
when `fastmcp[tasks]` is not installed
([`server/mixins/lifespan.py` L99–105](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/mixins/lifespan.py)
says the lifespan sets up a `SharedContext`;
[`server/context.py` L288–292](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/context.py)
says a per-`Context` one is created instead). This repo would not install `[tasks]`. Undocumented
plus ambiguous scope is not where to put your connection pool. **Use `lifespan`.**

### Note for testing

No example in the 3.4.5 tree owns an `httpx.AsyncClient` in a lifespan (OBSERVED —
`grep -rn "lifespan" examples/` yields only `examples/auth/mounted/server.py` and
`examples/diagnostics/server.py`, and the latter's client is closed before `yield`). Also,
`examples/persistent_state/` is **not** a model for this — it demonstrates *session*-scoped
`ctx.set_state`, which is the opposite of what a connection pool wants.

Moving to a shared client changes what `pytest-httpx` intercepts, so pair this change with §9.

---

## 5. Resources vs tools vs prompts

**Verdict: keep all five as tools. Do not add resources. Do not add prompts.** This agrees with the
prior pass, but for better-evidenced reasons than "nothing to compose."

### There is no crisp decision rule in the docs

`docs/servers/resources.mdx` (747 lines) has **no** "when to use a resource instead of a tool"
section, and `tools.mdx` has no comparison section (OBSERVED via grep). The only framing is
tutorial-level — SOURCE,
[`docs/tutorials/mcp.mdx` L33–58](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/tutorials/mcp.mdx):

> you can think of **Tools as being like `POST` requests.** They are used to *perform an action*,
> *change state*, or *trigger a side effect*…
>
> Following the REST API analogy, **Resources are like `GET` requests.** Their purpose is to
> *retrieve information* idempotently, ideally without causing side effects.

On that analogy alone, four or five of these tools "should" be resources. **But FastMCP's own
practice contradicts the analogy**, and that is the decisive evidence.

### FastMCP itself made exactly this call, in the same direction, for exactly this shape of problem

Its OpenAPI integration — the feature whose whole job is turning a read-only HTTP API into MCP —
maps **everything to tools by default**:

> By default, FastMCP converts every API endpoint into an MCP `Tool`. This ensures maximum
> compatibility with contemporary LLM clients, many of which **only support the `tools` part of the
> MCP specification.**
> — SOURCE, [`docs/tutorials/rest-api.mdx` L140](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/tutorials/rest-api.mdx)

> prior to FastMCP 2.8.0, GET requests were automatically mapped to `Resource` and
> `ResourceTemplate` components based on whether they had path parameters. **(This was changed
> solely for client compatibility reasons.)**
> — SOURCE, [`docs/integrations/openapi.mdx` L100](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/integrations/openapi.mdx)

That is the project reversing the exact design you would be adopting, on real-client grounds. It is
the "consider real client support, not just theory" answer, from the framework's own history.

### The technical clincher: resources cannot carry structured output

Resource functions may return only three things — SOURCE,
[`docs/servers/resources.mdx` L147–155](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/resources.mdx):

> -   **`str`**: Sent as `TextResourceContents`…
> -   **`bytes`**: Base64 encoded and sent as `BlobResourceContents`…
> -   **`ResourceResult`**: Full control over contents, MIME types, and metadata.
>
> To return structured data like dicts or lists, **serialize them to JSON strings using
> `json.dumps()`.**

Resources have **no output schema and no `structuredContent`**. So converting these tools to
resources would mean going back to `json.dumps()` — re-introducing precisely the anti-pattern §1
eliminates. The two recommendations are in direct conflict, and §1 is worth far more.

### What about exposing both?

3.4.5 does ship a sanctioned "both" — `ResourcesAsTools`, applied via `mcp.add_transform(...)`
([`examples/resources_as_tools/server.py` L10–11, L60–61](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/examples/resources_as_tools/server.py);
docs at [`docs/servers/transforms/resources-as-tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/transforms/resources-as-tools.mdx)).
But note what it generates:

> - **`list_resources`** returns JSON describing all available resources and templates
> - **`read_resource`** reads a specific resource by URI
> — SOURCE, [`resources-as-tools.mdx` L15–20](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/transforms/resources-as-tools.mdx)

Two *generic* tools, not one named tool per resource. An LLM would have to hand-construct
`scholar://17964/publications?limit=25` instead of calling a named tool with a validated schema.
For this server that is strictly worse than what already exists. `ResourcesAsTools` is a
compatibility bridge for servers whose primary interface is resources — it is not an argument for
becoming such a server.

**Prompts: SKIP.** Prompts are "reusable, parameterized message templates"
([`mcp.mdx` L93](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/tutorials/mcp.mdx)).
There is no recurring multi-step workflow here to encode. If a "find me a faculty recruit matching
X" workflow ever solidifies, that is when a prompt earns its place.

*(For completeness, since it was not obvious: resource templates would not have blocked on
pagination — RFC 6570 query params like `scholar://{id}/publications{?limit,offset}` are supported
([`resources.mdx` L557–599](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/resources.mdx)).
The blockers are client support and loss of structured output, not expressiveness.)*

---

## 6. Middleware — the prior pass's SKIP does not survive contact with the source

The prior pass called middleware a "plausible later home for caching/rate-limiting… no current
need." That was reasoned about middleware as a *concept you would have to build on*. In fact
FastMCP 3.4.5 **ships production middleware for exactly these concerns**, so the cost is an import
and one line, not an implementation.

Directory listing — OBSERVED,
[`fastmcp_slim/fastmcp/server/middleware/`](https://github.com/PrefectHQ/fastmcp/tree/v3.4.5/fastmcp_slim/fastmcp/server/middleware):

```
authorization.py  caching.py  dereference.py  error_handling.py  logging.py
middleware.py     ping.py     rate_limiting.py  response_limiting.py
timing.py         tool_injection.py
```

### Hooks available

SOURCE, [`docs/servers/middleware.mdx` L93–99](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx):

| Level | Hooks |
| --- | --- |
| Message | `on_message` |
| Type | `on_request`, `on_notification` |
| Operation | `on_call_tool`, `on_read_resource`, `on_get_prompt`, `on_list_tools`, `on_list_resources`, `on_list_resource_templates`, `on_list_prompts`, `on_initialize` |

Middleware is registered via `mcp.add_middleware(...)` or the `middleware=` constructor kwarg
(SOURCE, [`server/server.py` L330](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)).
Order matters: "The first middleware runs first on the way in and last on the way out"
([`middleware.mdx` L49](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx)).

### Caching — **ADOPT**, and it is the best fit of the three

`ResponseCachingMiddleware` caches `tools/call` results with TTL expiry, defaulting to an in-memory
store — SOURCE,
[`middleware/caching.py` L208–232](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/caching.py):

```python
def __init__(
    self,
    cache_storage: AsyncKeyValue | None = None,
    ...
    call_tool_settings: CallToolSettings | None = None,
    max_item_size: int = ONE_MB_IN_BYTES,
):
    """
    cache_storage: The cache backend to use. If None, an in-memory cache is used.
    call_tool_settings: ... If None, the default settings are used (1 hour TTL).
    """
```

Why it fits this server unusually well: **all five tools are annotated `readOnlyHint=True` and
`idempotentHint=True`** (`server.py` L184–190, L298–304, L406–411, L513–518, L608–613). Those
annotations are a promise that repeated identical calls are safe to serve from cache — this server
has already declared itself cacheable. A scholar directory changes on the order of weeks; an agent
exploring it re-queries the same scholar constantly.

```python
from fastmcp.server.middleware.caching import (
    ResponseCachingMiddleware, CallToolSettings, ListToolsSettings,
)

mcp.add_middleware(ResponseCachingMiddleware(
    call_tool_settings=CallToolSettings(ttl=900),   # 15 min; default is 3600
    list_tools_settings=ListToolsSettings(ttl=3600),
))
```

Three caveats, all SOURCE-verified:

1. **The default `tools/call` TTL is 1 hour** (`ONE_HOUR_IN_SECONDS = 3600`, used at
   [`caching.py` L449](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/caching.py)).
   Tune it deliberately.
2. **Cache keys ignore identity for stdio.** "Unauthenticated callers (including STDIO) share a
   single anonymous partition" ([`caching.py` L200–205](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/caching.py)).
   Harmless here — the data is public and identical for everyone.
3. **⚠️ Caching must not be adopted before the §2 error fix.** `on_call_tool` stores the result
   unconditionally after `call_next` returns; there is no `is_error` check
   ([`caching.py` L441–450](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/caching.py)).
   Today's `"Error: Request timed out."` is a perfectly ordinary successful result — so **one
   transient timeout would be cached and replayed for an hour.** Once errors are *raised* instead,
   the exception propagates out of `call_next` and the `put` is never reached, so failures are not
   cached. INFERRED from the control flow, and reinforced by `is_error=True` appearing nowhere in
   the server-side source (OBSERVED via grep; the only hit is in `client/oauth_callback.py`).
   **This ordering dependency is the reason §2 must ship before §6.**

### Retry / backoff — **ADOPT, but the defaults are a trap**

`RetryMiddleware` implements exponential backoff — SOURCE,
[`middleware/error_handling.py` L157–200](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/error_handling.py):

```python
def __init__(
    self,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    retry_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
    ...
)
```

**Those defaults will never fire for this server.** `httpx`'s exceptions do not inherit from the
builtins — OBSERVED, run against the repo's own installed `httpx` 0.28.1:

```
httpx.TimeoutException -> ['TransportError', 'RequestError', 'HTTPError', 'Exception', ...]
httpx.ConnectError     -> ['NetworkError', 'TransportError', 'RequestError', 'HTTPError', ...]

TimeoutException subclass of builtin TimeoutError:  False
ConnectError    subclass of builtin ConnectionError: False
```

So the middleware must be told the real types:

```python
mcp.add_middleware(RetryMiddleware(
    max_retries=2,
    retry_exceptions=(httpx.TimeoutException, httpx.ConnectError, httpx.ReadError),
))
```

and — per §2 — the tool must raise `ToolError(...) **from** e` or `_should_retry` cannot see
through to the httpx type. These two facts together are the least obvious thing in this document.

Retrying is safe here precisely because every tool is a read-only GET/POST-as-query with
`idempotentHint=True`.

### Rate limiting — **SKIP, and the prior pass's framing was subtly wrong**

The question asked whether middleware is the home for "rate-limiting against an upstream portal."
It is not. `RateLimitingMiddleware` limits **inbound MCP requests to your server**, keyed by client
identity (`get_client_id`), not outbound requests to `discover.research.utoronto.ca`
([`middleware.mdx` L450–476](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx)).

On a local single-user stdio server there is exactly one client and no inbound abuse to prevent. It
does throttle upstream *indirectly* (roughly one tool call ≈ one upstream request), but as
upstream-politeness protection it is a side effect of the wrong mechanism. **Caching is the correct
tool for reducing upstream load**, and it reduces it far more.

If you later want genuine upstream politeness, that belongs in the httpx layer (a semaphore or a
transport wrapper on the shared client from §4), not in MCP middleware.

### Response limiting — **ADOPT (cheap insurance)**

`ResponseLimitingMiddleware` caps tool response size; default `max_size=1_000_000`
([`middleware.mdx` L550–596](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx)).
Relevant because `discover_get_filter_options` enumerates **every department or tag in the
university** with no pagination at all (`server.py` L690–699) — an unbounded list straight into the
model's context. Note the documented interaction: truncated responses stop conforming to the
output schema from §1, so treat this as a backstop, not a substitute for bounding that tool.

### `ErrorHandlingMiddleware` — SKIP for now

Useful for centralised logging, but its error-mapping duplicates what explicit `ToolError` raising
does more precisely. One discrepancy worth knowing: the **docs table says `transform_errors`
defaults to `False`** ([`middleware.mdx` L512](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx))
but the **source signature says `transform_errors: bool = True`**
([`error_handling.py` L42](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/middleware/error_handling.py)).
Trust the source. Flagged because it is the kind of thing that bites when you adopt on the docs' word.

---

## 7. Server structure at ~700 lines

**Split into modules: YES. Use composition (`mount` / `import_server`): NO.** These are separate
questions and the prior pass only answered the second.

### Composition is for combining *servers*, not organising *one* server

SOURCE, [`docs/servers/composition.mdx` L12–14](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/composition.mdx):

> As your application grows, you'll want to split it into focused servers — one for weather, one for
> calendar, one for admin — and combine them into a single server that clients connect to. That's
> what `mount()` does.

The unit is a *server with its own domain*, typically its own lifespan and middleware. This repo has
**one upstream API, one auth story (none), one lifespan, five cohesive tools.** There is nothing to
compose. `mount()` would add a namespace layer and a second `FastMCP` object for zero benefit.

Also note `import_server` is now deprecated in favour of `mount` — SOURCE,
[`docs/getting-started/upgrading/from-fastmcp-2.mdx` L88–90](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/getting-started/upgrading/from-fastmcp-2.mdx):

> - `mount(prefix="x")` -> `mount(namespace="x")`
> - `import_server(sub)` -> `mount(sub)`

So "use `import_server` to organise modules" would be adopting a deprecated API for a job it was
never for.

### What real FastMCP servers of this size actually do

The best evidence at the tag is `examples/atproto_mcp` — a **~1,040-line MCP server wrapping a
single external API**, i.e. this repo's exact shape, one size up. OBSERVED (`wc -l`, and
`grep -rn "mount\|import_server" examples/atproto_mcp/src/` → **0 hits**, with exactly **one**
`FastMCP(...)` instance):

```
src/atproto_mcp/
  server.py        149 lines   <- ONLY tool/resource definitions; thin
  types.py         142 lines   <- result models
  settings.py       17 lines   <- config
  __main__.py        9 lines   <- entrypoint: `atproto_mcp.run()`
  _atproto/                    <- private package: all upstream API work
    _client.py      16         <- shared client construction
    _read.py       124
    _posts.py      420
    _profile.py     33
    _social.py     108
```

Three things to take from it:

1. **1,040 lines, zero composition.** Multi-module ≠ multi-server.
2. **`server.py` holds only tool definitions and delegates**, e.g.
   `return _atproto.fetch_timeline(...)`. Tool functions are adapters; upstream logic lives behind
   a private package.
3. It independently corroborates §1 and §8: flat `Annotated[..., Field(...)]` parameters and typed
   return models (`types.py`), imported into `server.py`
   ([`examples/atproto_mcp/src/atproto_mcp/server.py` L1–25](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/examples/atproto_mcp/src/atproto_mcp/server.py)).

### Recommended layout here

`server.py`'s 707 lines currently interleave four concerns per tool: MCP declaration, upstream
payload construction, HTTP, and response parsing. Mirroring the example:

```
discover_research_mcp/
  __init__.py
  server.py        # FastMCP instance, lifespan, middleware, 5 @mcp.tool defs. ~150 lines
  models.py        # Pydantic result models (§1)  + input Annotated types
  config.py        # BASE_URL, API_URL, TIMEOUT, HEADERS, DEFAULT_FILTERS  (server.py L19-36)
  _discover/
    _client.py     # shared httpx.AsyncClient plumbing + _get_json error translation (§2)
    _search.py     # search + filter-options payload building & parsing
    _scholars.py   # profile parsing
    _works.py      # publications + grants parsing
  __main__.py      # mcp.run()
```

The seam that matters most is **parsing vs. transport**. `_strip_html` (L39–44),
`_format_scholar_summary` (L62–84), and the inline publication/grant loops (L474–494, L577–589) are
pure functions of an upstream dict. Isolating them makes the scraper's most failure-prone code
directly unit-testable with no HTTP and no MCP (§9) — that is the payoff, not tidiness.

**Is this warranted for five tools? The honest counter-argument.** FastMCP's own repo enforces a
file-size gate of **1,000 lines** — SOURCE,
[`loq.toml` L4](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/loq.toml): `default_max_lines = 1000`,
referenced by [`CLAUDE.md` L182](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/CLAUDE.md)
("File sizes enforced by loq"). At 707 lines **this server is comfortably inside the framework
authors' own limit**, and they grant `server.py` itself an exemption to 2,410 lines
([`loq.toml` L17–19](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/loq.toml)).

So "707 lines is too long" is **not** supportable from primary sources. The defensible case for
splitting is narrower and rests on testability: the parsing functions are the bug-prone part, they
have zero coverage today, and they are currently unreachable without going through HTTP. If you do
only one thing structurally, **extract `_discover/` (transport + parsing) and leave everything
else** — that captures nearly all the benefit for a fraction of the churn. Treat the full layout
above as the destination, not a prerequisite.

Worth noting the project's own coding standard indicts one specific line-level pattern here, not
the file length — SOURCE, [`CLAUDE.md` L181](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/CLAUDE.md):

> - Never use bare `except` - be specific with exception types

which is exactly the `except Exception` at L292/L399/L506/L601/L702 (§2).

### Entrypoint: `fastmcp.json` is now the canonical project config

SOURCE, [`docs/deployment/server-configuration.mdx` L12](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/deployment/server-configuration.mdx):

> FastMCP supports declarative configuration through `fastmcp.json` files. **This is the canonical
> and preferred way to configure FastMCP projects**, providing a single source of truth for server
> settings, dependencies, and deployment options that replaces complex command-line arguments.

It answers *where* the code is (`source`), *what* it needs (`environment`), and *how* to run it
(`deployment`); only `source` is required
([`server-configuration.mdx` L36–66](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/deployment/server-configuration.mdx)).
The working template is `examples/atproto_mcp/fastmcp.json`.

This is **optional polish** for this repo — the existing `mcp.json` (`uv run python server.py`)
works fine and is what the MCP client reads. Adopt `fastmcp.json` only if you want
`fastmcp run` / `fastmcp inspect` to work without arguments. If you do, copy
[`examples/atproto_mcp/fastmcp.json`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/examples/atproto_mcp/fastmcp.json)
— **not** `examples/fastmcp_config/simple.fastmcp.json` or `env_interpolation_example.json`, which
put `entrypoint` at the top level with no `source` key and would fail validation (`source` is the
sole required field per
[`schema.json` L359–360](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/utilities/mcp_server_config/v1/schema.json)).
Several shipped example configs are stale — a third docs-vs-source inconsistency.

`__main__.py` also resolves `main.py`'s limbo: today it is a 6-line stub printing
`"Hello from discover-research-mcp!"` that is not on the run path at all (`mcp.json` invokes
`server.py` directly).

### Pagination stays hand-rolled

`docs/servers/pagination.mdx` is about paginating the **catalog** (`tools/list`, `resources/list`),
not tool results — SOURCE,
[L13](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/pagination.mdx):

> When a server exposes many tools, resources, or prompts, returning them all in a single response
> can be impractical.

There is `fastmcp_slim/fastmcp/utilities/pagination.py`, but its docstring scopes it to
"Pagination utilities for **MCP list operations**", it only paginates an in-memory `Sequence`, and
it is not re-exported to `fastmcp.*`. **No FastMCP affordance exists for paginating upstream API
results.** The `page`/`per_page`/`has_more` handling at L234, L450–503, L553–598 is correct as
ordinary tool parameters and should stay — just move it into typed models (§1).

---

## 8. Tool metadata

### The decorator surface in 3.4.5

Taken from the **real signature**, not the docs — SOURCE, verbatim from
[`fastmcp_slim/fastmcp/server/server.py` L1737–1755](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py):

```python
    def tool(
        self,
        name_or_fn: str | AnyFunction | None = None,
        *,
        name: str | None = None,
        version: str | int | None = None,
        title: str | None = None,
        description: str | None = None,
        icons: list[mcp.types.Icon] | None = None,
        tags: set[str] | None = None,
        output_schema: dict[str, Any] | NotSetT | None = NotSet,
        annotations: ToolAnnotations | dict[str, Any] | None = None,
        exclude_args: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        app: AppConfig | dict[str, Any] | bool | None = None,
        task: bool | TaskConfig | None = None,
        timeout: float | None = None,
        auth: AuthCheck | list[AuthCheck] | None = None,
        run_in_thread: bool = True,
    ) -> (
```

| Param | Relevant here? |
| --- | --- |
| `name` | already used |
| `description` | overrides docstring — see below |
| `tags` | marginal — SKIP |
| `annotations` | already used, correctly |
| `meta` | optional polish |
| **`timeout`** | **ADOPT** |
| `output_schema` | not needed — derived from §1's return types. Note the default is the sentinel `NotSet`, not `None`, distinguishing "infer from return annotation" from "explicitly none" |
| `title` | available on the decorator *and* as a `ToolAnnotations` field — this server sets it via annotations, which is fine |
| `exclude_args` | deprecated in favour of `Depends()` |
| `app`, `task`, `auth`, `icons`, `version`, `run_in_thread` | no |

> ⚠️ **`enabled=` is not a parameter and will raise `TypeError`.** The docs still document it as a
> deprecated-but-present argument
> ([`tools.mdx` L80–83](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)),
> but it is **absent from the signature above**, which is keyword-only with no `**kwargs`
> (OBSERVED — grepping L1737–1860 for `enabled` returns nothing). It survives one layer down on
> `LocalProvider.tool`
> ([`server/providers/local_provider/decorators/tools.py` L242](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/providers/local_provider/decorators/tools.py)).
> This is the **second** docs/source contradiction found (see also `on_duplicate_tools` in §10) —
> read the signature, not the prose.

### Annotations — already correct, keep them

All five tools already pass the full annotation set (`server.py` L184–190, L298–304, L406–411,
L513–518, L608–613), and plain dicts remain valid — the union type is
`ToolAnnotations | dict[str, Any] | None`. The docs use `ToolAnnotations` "for consistency and
stronger editor/type support" ([`tools.mdx` L944](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx))
but accept either. Switching to `ToolAnnotations` is cosmetic; the values are what matter, and
they are right. These annotations are also what makes the §6 caching verdict defensible.

### ⚠️ `timeout` — ADOPT (and this is a real gap, not polish)

```python
@mcp.tool(timeout=45.0, annotations={...})
async def discover_search_scholars(...) -> ScholarSearchResult: ...
```

> Tools can specify a `timeout` parameter to limit how long execution can take. When the timeout is
> exceeded, the client receives an MCP error and the tool stops processing.
> — SOURCE, [`tools.mdx` L847–866](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)

Today the only bound is httpx's own `TIMEOUT = 30.0` per request (`server.py` L21). Once §6 adds
`RetryMiddleware`, total wall-clock becomes *retries × (timeout + backoff)* — a 30s timeout with
2 retries and exponential backoff can exceed 90 seconds with no ceiling. A tool-level `timeout` is
the ceiling. "There is no server-level default timeout setting"
([`tools.mdx` L868–870](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)) —
it must be set per tool.

### ⚠️ Descriptions from docstrings — a silent regression this server will hit

This is the least obvious finding in this document and it affects all five tools.

3.4.5 parses docstrings with `griffe`, trying Google/NumPy/Sphinx in order — SOURCE, verbatim from
[`fastmcp_slim/fastmcp/utilities/docstring_parsing.py` L47–65](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/utilities/docstring_parsing.py):

```python
    for parser in _PARSERS:
        docstring = Docstring(doc, lineno=1, parser=parser)
        sections = docstring.parse()

        description: str | None = None
        parameters: dict[str, str] = {}

        for section in sections:
            if section.kind == DocstringSectionKind.text and description is None:
                description = section.value
            elif section.kind == DocstringSectionKind.parameters:
                for param in section.value:
                    parameters[param.name] = param.description

        if parameters:
            return ParsedDocstring(description=description, parameters=parameters)

    # No parser found parameters — return the full docstring unchanged.
    return ParsedDocstring(description=doc)
```

Read the control flow carefully:

- `description` takes **only the first text section** (note `and description is None`).
- The full docstring survives **only if no parser finds parameters**.
- The docs confirm the intent: "Sections like `Returns`, `Raises`, and `Example` are excluded from
  the description" ([`tools.mdx` L341](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).

Every docstring in `server.py` has an `Args:` section documenting `params`, so a parser **will**
find parameters, and the `Returns:` and `Examples:` blocks will be dropped from the description.

**The "before" state is OBSERVED** — I ran the repo's own server against its installed `mcp` 1.26.0
and dumped `list_tools()`:

```
== discover_search_scholars            | description chars: 1846
   contains Args: True | contains Returns: True | contains Examples: True
== discover_get_scholar                | description chars: 1379   (same flags)
== discover_get_scholar_publications   | description chars: 1213   (same flags)
== discover_get_scholar_grants         | description chars:  951   (same flags)
== discover_get_filter_options         | description chars: 1232   (same flags)
```

Today the model sees the entire docstring. After migration it sees roughly the leading paragraph.

What gets lost is not filler. It is the **`Examples:` blocks** — `server.py` L229–232, L340–342,
L446–448, L550–551, L641–644 — which are precisely the few-shot usage guidance that teaches a model
how to chain these tools ("Find ML researchers in Engineering" → `query=…, department_filter=…`).
Losing them will degrade tool-selection quality, silently, with no error.

**This is INFERRED, not OBSERVED** — `griffe` is not installed and I was instructed not to install
anything. It is the highest-risk prediction here; see [§12](#12-what-i-could-not-verify) for how to
check it in one command.

**The fix is easy once you know.** Move the durable guidance out of dropped sections:

- Put usage examples in the **leading prose** (they stay), or pass `description=` explicitly to the
  decorator, which bypasses docstring parsing for the description entirely
  ([`tools.mdx` L72–74](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
- Delete the `Returns:` JSON blocks — §1's typed models make them redundant *and* machine-checked.
- Per-parameter text belongs in `Field(description=...)`, which already exists on every field and
  takes precedence over the docstring
  ([`function_parsing.py` L258–268](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py)).

Net effect: docstrings get *shorter* and the tool surface gets *richer*, because the schema carries
what the prose used to assert.

### Flat parameters vs. the `params` wrapper model

Not deprecated — but worth reconsidering, because **every example in `tools.mdx` uses flat
parameters**, and none uses a single wrapper model
([L222–231, L262–272, L375–391](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
The documented idiom is `Annotated[T, Field(...)]` on individual arguments:

```python
@mcp.tool(name="discover_get_scholar", timeout=30.0, annotations={...})
async def discover_get_scholar(
    scholar_id: Annotated[str, Field(
        description="Numeric scholar ID (e.g. '17964') or full URL ID ('17964-michael-guerzhoy')",
        min_length=1,
    )],
    ctx: Context,
) -> ScholarProfile:
```

Benefits: the five `BaseModel` classes at L89–177 collapse into signatures; the schema flattens from
`{"params": {…}}` to top-level named arguments, which is what LLM clients see most often and handle
best; and the `Args:` docstring sections that cause the truncation above become unnecessary.

**This is a client-visible breaking change** — any saved prompt or agent call site passing
`{"params": {"query": "…"}}` must become `{"query": "…"}`. It is genuine idiom alignment, not
cosmetics, so it belongs in a reviewed step of its own with the breakage called out.

⚠️ **This deliberately breaks the one thing the prior pass verified as stable.** That pass observed
the live `{"params": {…}}` envelope and identified envelope stability as the prediction most worth
watching — its conclusion was that the wrapper *keeps working* across the migration. That is true,
and it is why this is safe to defer. But B6 is the change that ends it on purpose: every saved call
site, stored prompt, and prior `discover_*` invocation shape changes. Do not let a reader who
trusts the prior pass discover this from a diff.

**Good news on strictness — OBSERVED.** `ConfigDict(extra="forbid")` (L90 etc.) currently rejects
unknown keys, and that behaviour survives flattening for free. FastMCP builds input schemas via
`TypeAdapter(fn).json_schema()`
([`function_parsing.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py)),
so I ran that exact primitive against this repo's installed pydantic on a representative flat
signature:

```json
{
  "additionalProperties": false,
  "properties": {
    "scholar_id": {"description": "Numeric scholar ID", "minLength": 1, "type": "string"},
    "page":       {"default": 1, "type": "integer"},
    "sort":       {"default": "dateDesc", "pattern": "^(dateDesc|dateAsc)$", "type": "string"}
  },
  "required": ["scholar_id"],
  "type": "object"
}
```

Three things confirmed at once: `additionalProperties: false` is emitted **automatically** (so no
strictness is lost), the schema **flattens to top-level named properties** as claimed, and
`Field(min_length=…, pattern=…)` constraints **survive** the move out of the model. The only
casualty is the `params` envelope itself.

### `meta`, tags, and tool transformation

- **`meta`** — static metadata "passed through to the MCP client as the `meta` field"
  ([`tools.mdx` L112–116](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
  Optional polish; a `{"upstream": "discover.research.utoronto.ca"}` provenance stamp is the only
  plausible use. Not load-bearing.
- **`tags`** — categorisation used for filtering/visibility, driving `mcp.enable(tags={...},
  only=True)` / `mcp.disable(tags={...})`
  ([`tools.mdx` L899–930](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
  With five always-on tools there is nothing to filter. **SKIP** until there's a reason.
- **Tool transformation** — `server.add_transform(...)`, the replacement for the removed
  `tool_transformations` kwarg ([`server/server.py` L164](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)).
  It exists to re-shape tools you **don't own** (generated OpenAPI tools, mounted third-party
  servers). You own all five of these — edit the function. **SKIP.**

---

## 9. Testing idioms

### The in-memory client

`Client(mcp)` connects directly to the server object — no transport, no port, no subprocess. The
documented fixture, SOURCE, [`docs/servers/testing.mdx` L29–47](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/testing.mdx)
(byte-identical to `docs/patterns/testing.mdx` — OBSERVED via `diff`):

```python
import pytest
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from my_project.main import mcp

@pytest.fixture
async def main_mcp_client():
    async with Client(transport=mcp) as mcp_client:
        yield mcp_client

async def test_list_tools(main_mcp_client: Client[FastMCPTransport]):
    list_tools = await main_mcp_client.list_tools()
    assert len(list_tools) == 5
```

The repo's `asyncio_mode = "auto"` (`pyproject.toml` L21) already matches what the docs require
("We recommend configuring pytest to automatically handle async tests by setting the asyncio mode
to `auto`", [`testing.mdx` L19–25](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/testing.mdx)).
**No pytest config change needed.** `pytest-asyncio` is already a dev dep.

### What you assert on

`CallToolResult` — SOURCE, verbatim from
[`fastmcp_slim/fastmcp/client/client.py` L119–127](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/client/client.py):

```python
@dataclass
class CallToolResult:
    """Parsed result from a tool call."""

    content: list[mcp.types.ContentBlock]
    structured_content: dict[str, Any] | None
    meta: dict[str, Any] | None
    data: Any = None
    is_error: bool = False
```

`result.data` is the deserialised object — and once §1 lands it becomes a **typed** object rather
than a JSON string, so tests read naturally (`result.data.total == 3`). This is a direct payoff of
the typed-return change.

### Asserting failure — the test that cannot be written today

`call_tool` raises `ToolError` on error by default (`raise_on_error: bool = True`, SOURCE
[`client/mixins/tools.py` L240–253, L420–426](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/client/mixins/tools.py)).
Both idioms, SOURCE, verbatim from
[`tests/tools/tool/test_results.py` L95–124](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/tests/tools/tool/test_results.py):

```python
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("failing", {})
```
```python
        async with Client(mcp) as client:
            result = await client.call_tool("failing", {}, raise_on_error=False)

        assert result.is_error is True
        assert result.content[0].text == "upstream boom"
```

**This is the regression test for the §2 bug**, and it is worth writing *first*: today a 404 from
upstream produces a successful result, so `pytest.raises(ToolError)` fails. That is the failing
test that drives the error-handling fix.

### How it composes with `pytest-httpx`

The two mock **different layers** and belong together:

| Layer | Tool | Proves |
| --- | --- | --- |
| Upstream HTTP | `pytest-httpx` | request payloads are right (the `values`/`selectedValues` regression, commit `549e230`) |
| MCP surface | `Client(mcp)` | tools register, schemas/annotations are right, errors surface as errors, typed data round-trips |

The existing four tests (`tests/test_server.py` L21–87) are upstream-payload regression tests and
should be **kept**. One caveat: they call the decorated functions directly with a
`SearchScholarsInput(...)` object. Two redesign items break those call sites — flat parameters (§8)
changes the signature, and the shared lifespan client (§4) means the client no longer exists at
call time unless the lifespan has run. Going through `Client(mcp)` fixes both, since it drives the
real server and exercises the lifespan.

### Recommended structure for these five tools

```
tests/
  conftest.py          # client fixture + shared FAKE_* payload fixtures
  test_upstream_payloads.py   # pytest-httpx: what we SEND (today's 4 tests, migrated)
  test_mcp_surface.py         # Client(mcp): registration, schemas, annotations
  test_errors.py              # 404 / 429 / timeout / malformed-shape -> ToolError
  test_parsing.py             # pure _format_* functions, no HTTP, no MCP
```

The `test_parsing.py` split is worth calling out: `_format_scholar_summary` (L62–84) and the inline
publication/grant parsing (L474–494, L577–589) are **pure functions of an upstream dict**. They are
where scraper bugs actually live, they need neither HTTP nor MCP to test, and today they have zero
coverage. Extracting them (§7) makes them trivially testable — the strongest practical argument for
the module split.

Current coverage is 1 of 5 tools and 0 of 3 failure modes (OBSERVED — `tests/test_server.py` is 87
lines, all four tests call `discover_search_scholars`).

---

## 10. Anti-patterns and deprecations

### Present in this server today

| # | Pattern in `server.py` | Status in 3.4.5 |
| --- | --- | --- |
| 1 | Returning `"Error: …"` strings (L47–59 + 5 call sites) | Anti-pattern. Docs are explicit for the analogous middleware case: "Do not return error values… raise exceptions for proper error propagation" ([`middleware.mdx` L671](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/middleware.mdx)) |
| 2 | `json.dumps(...)` + `-> str` (L290, L397, L504, L599, L700) | Superseded by structured output (§1). This is hand-rolled serialisation; `ToolResult` is the sanctioned escape hatch and isn't needed here |
| 3 | `Optional[str]` / `List[str]` (L11) | Dated. Every example at the tag uses `str | None` and `list[str]` (e.g. [`tools.mdx` L266–269](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)). Cosmetic; `requires-python = ">=3.12"` makes the modern form free |
| 4 | New `httpx.AsyncClient()` per call (L267, L348, L460, L563, L667) | Anti-pattern — see §4 |
| 5 | Single wrapper `params: SomeModel` argument | Not deprecated, but against the grain of every documented example — see §8 |
| 6 | Blanket `except Exception` | Swallows `ToolError`; see §2 |

### Deprecated / removed APIs — none of which this server uses

Removed from the `FastMCP()` constructor in v3 (each raises `TypeError` with a hint) — SOURCE,
[`server/server.py` L148–166](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py):

```python
_REMOVED_KWARGS: dict[str, str] = {
    "host": "Pass `host` to `run_http_async()`, or set FASTMCP_HOST.",
    "port": ..., "sse_path": ..., "message_path": ..., "streamable_http_path": ...,
    "json_response": ..., "stateless_http": ..., "debug": ..., "log_level": ...,
    "on_duplicate_tools": "Use `on_duplicate=` instead.",
    "on_duplicate_resources": "Use `on_duplicate=` instead.",
    "on_duplicate_prompts": "Use `on_duplicate=` instead.",
    "tool_serializer": "Return ToolResult from your tools instead. ...",
    "include_tags": "Use `server.enable(tags=..., only=True)` after creating the server.",
    "exclude_tags": "Use `server.disable(tags=...)` after creating the server.",
    "tool_transformations": "Use `server.add_transform(ToolTransform(...))` after creating the server.",
}
```

Also deprecated: `exclude_args` (use `Depends()`); `decorator_mode="object"`; `transport="sse"`;
`import_server` (use `mount`); `mount(prefix=)` (use `namespace=`). And `enabled=` on `@mcp.tool`
is not merely deprecated but **absent** — see §8.

> ⚠️ **A stale page in the 3.4.5 docs.** `docs/servers/tools.mdx` L1093–1111 ("Duplicate Tools")
> still tells you to write `FastMCP(name="StrictServer", on_duplicate_tools="error")`. That kwarg
> is in `_REMOVED_KWARGS` and now raises `TypeError`. **The shipped docs contradict the shipped
> source.** Where they disagree, the source is authoritative — a useful calibration for anything
> else you take from these docs.

---

## 11. Verdicts that differ from the prior pass

Three flips and two refinements. Each is a change of *conclusion*, not just emphasis.

### Flip 1 — Middleware: SKIP → **ADOPT** (caching + retry)

The prior pass wrote: *"Plausible later home for caching/rate-limiting against the upstream portal;
no current need."* That treated middleware as scaffolding you would have to build on. **In 3.4.5,
`ResponseCachingMiddleware` and `RetryMiddleware` ship in the box** — `caching.py` and
`error_handling.py` under `fastmcp_slim/fastmcp/server/middleware/` (OBSERVED). The cost is two
imports, not an implementation. For a read-only scraper whose tools already declare
`idempotentHint=True`, response caching is arguably the highest-leverage feature available. See §6.

*Sub-correction:* the framing "rate-limiting **against an upstream portal**" does not match what
`RateLimitingMiddleware` does — it limits **inbound** MCP clients, which on a single-user stdio
server means nothing. That piece stays SKIP, but for a different reason than the one given.

### Flip 2 — Tool metadata: "already adopted, zero work" → **work required**

The prior pass concluded the existing annotations need no change — true — and therefore that this
area was done. Two things were missed:

- **`@mcp.tool(timeout=...)`** exists (v3.0.0) and this server has no execution ceiling — a gap that
  *widens* once retry middleware is added (§8).
- **Docstring handling changed.** 3.4.5 parses docstrings with `griffe` and keeps only the first
  text section; the prior pass stated "the long docstrings in `server.py` carry over." Per the
  parser source, the `Returns:` and `Examples:` blocks are **dropped** from every tool description —
  an OBSERVED 951–1846 chars today, shrinking to roughly the leading paragraph. A silent quality
  regression across all five tools (§8).

### Flip 3 — Lifespan: "follow-up, orthogonal, not migration scope" → **core idiom**

Correct as *migration* triage; wrong for a redesign. Owning the `httpx.AsyncClient` in a lifespan is
the documented pattern for shared state and removes five duplicated `async with` blocks (§4). The
prior pass also did not surface the trap that makes this worth writing down: **`Depends()` looks
like the right mechanism and is not** — its resolution is explicitly *per-request*, so it would
construct a fresh client on every tool call.

### Refinement 1 — Resources: same SKIP, much stronger evidence

The prior pass dismissed resources under "composition — nothing to compose," which conflates two
different features. The real reasons: FastMCP **changed its own OpenAPI default away from
GET→Resource "solely for client compatibility reasons"**, and resources cannot carry structured
output at all, which would directly undo §1 (§5).

### Refinement 2 — `ToolError`: same ADOPT, but a **correctness fix**, not an improvement

The prior pass sequenced `ToolError` as step 7 of 10, after "migration complete." Given §6 the
ordering is now load-bearing: **`ResponseCachingMiddleware` caches whatever the tool returns, with
no `is_error` check.** Adopt caching before fixing errors and one transient timeout gets cached and
replayed as a success for an hour. Error handling ships first.

---

## 12. What I could not verify

Stated plainly rather than filled in.

1. **FastMCP 3.4.5 was never installed or executed** — the task forbade installing. Every FastMCP
   behavioural claim is read from source/docs at the tag. No end-to-end run, no `fastmcp inspect`.
2. **The docstring-truncation prediction (§8) is INFERRED and is the riskiest claim here.** I read
   `parse_docstring` and traced the control flow, but `griffe` is not installed, so I could not run
   it against this repo's actual docstrings. The "before" state (951–1846 chars, all sections
   present) **is** OBSERVED against `mcp` 1.26.0. Verify the "after" in one command post-install:
   ```
   uv run python -c "from fastmcp.utilities.docstring_parsing import parse_docstring; \
   import server; print(parse_docstring(server.discover_search_scholars).description)"
   ```
   If that prints the full 1,846-char docstring, §8's warning is wrong and the `Examples:` blocks
   are safe. If it prints only the leading paragraph, act on it.
3. ~~`extra="forbid"` under flat parameters — not verified.~~ **Resolved: OBSERVED.** Running
   `TypeAdapter(fn).json_schema()` — the exact primitive FastMCP uses — on a representative flat
   signature emits `additionalProperties: false` automatically and preserves `min_length` / `pattern`
   constraints (§8). Strictness is not lost by flattening. *Residual gap:* I confirmed the pydantic
   schema-generation half, not FastMCP's end-to-end enforcement of it at call time, and did not test
   the interaction with `strict_input_validation=True`.
4. **Whether a *raised* error is cached (§6) is INFERRED.** I traced that `on_call_tool` reaches its
   `put` only after `call_next` returns normally, and confirmed `is_error=True` is set nowhere in
   the server-side source (OBSERVED via grep). I did not execute the middleware chain. The
   converse — that today's **returned** `"Error: …"` strings would be cached — follows directly from
   their being ordinary successful results, and I am confident in it.
5. **`Shared()`'s scope without `fastmcp[tasks]` is genuinely ambiguous** — two source comments
   disagree (§4). I did not resolve it; the recommendation routes around it.
6. **No exception-propagation test through the full middleware stack was run**, so the interaction
   between `ToolError(...) from e` and `RetryMiddleware._should_retry` (§2/§6) is read from source,
   not demonstrated. The httpx-vs-builtin exception mismatch motivating it **is** OBSERVED.
7. **Real-world client support for resources** rests on FastMCP's own documented rationale (§5), not
   on my testing any MCP client.
8. **No CHANGELOG sweep** of individual 3.4.x patch releases; coverage comes from the tagged docs,
   upgrade guides, and source.
9. **Three docs/source contradictions found at this tag** (`on_duplicate_tools` §10, `enabled` §8,
   stale `fastmcp.json` examples §7), plus one docs-internal one
   (`ErrorHandlingMiddleware.transform_errors` default, §6). Treat the 3.4.5 prose as approximately,
   not exactly, current — I preferred the signature wherever they disagreed.

---

## 13. Mapping recommendations onto the existing code

| `server.py` today | Lines | Idiomatic form in 3.4.5 | § |
| --- | --- | --- | --- |
| `_handle_error` returns `"Error: …"` strings; 5 call sites `return _handle_error(e)` | 47–59; 292, 399, 506, 601, 702 | Raise `ToolError(...) from e`; distinguish 404 / 429 / timeout / parse-shape. Delete the blanket `except Exception` — it would swallow `ToolError` | 2 |
| All five tools declared `-> str`, ending in `json.dumps(result, indent=2)` | 290, 397, 504, 599, 700 | Return typed Pydantic envelope models → automatic `structuredContent` **plus** text blocks (no client breakage) | 1 |
| Result dicts hand-assembled | 283–289, 374–396, 496–503, 591–598, 695–699 | Already the right shapes — just name them (`ScholarSearchResult`, `ScholarProfile`, …) | 1 |
| `Returns:` docstring blocks documenting JSON shape in prose | 208–227, 317–338, 424–444, 536–548, 628–639 | Delete — replaced by generated output schema, and dropped from the description anyway | 1, 8 |
| `Examples:` docstring blocks (few-shot usage guidance) | 229–232, 340–342, 446–448, 550–551, 641–644 | ⚠️ Will be **silently dropped**. Move into leading prose or an explicit `description=` | 8 |
| `async with httpx.AsyncClient()` per call | 267, 348, 460, 563, 667 | One client owned by a `@lifespan`, reached via `ctx.lifespan_context["client"]` | 4 |
| `BASE_URL` / `API_URL` / `TIMEOUT` / `HEADERS` / `DEFAULT_FILTERS` globals | 19–36 | Fine as-is; move to `config.py` only if splitting | 7 |
| No execution timeout on any tool | — | `@mcp.tool(timeout=45.0)` — matters more once retries exist | 8 |
| No caching; identical repeat queries re-hit the portal | all 5 | `ResponseCachingMiddleware(call_tool_settings=CallToolSettings(ttl=900))` — **only after** the error fix | 6 |
| No retry on transient upstream failure | all 5 | `RetryMiddleware(retry_exceptions=(httpx.TimeoutException, httpx.ConnectError))` — defaults do **not** match httpx | 6 |
| Five `BaseModel` input wrappers; tools take `params: XInput` | 89–177 | Flat `Annotated[str, Field(...)]` parameters. **Client-visible breaking change** | 8 |
| `annotations={readOnlyHint: True, …}` on all five | 184–190, 298–304, 406–411, 513–518, 608–613 | **Correct already — keep.** These justify the caching verdict | 8 |
| `Optional[...]` / `List[...]` imports | 11 | `str \| None` / `list[str]` (3.12 already required) | 10 |
| No logging anywhere | — | `ctx.warning(...)` when the upstream shape looks wrong | 3 |
| `_strip_html`, `_format_scholar_summary`, inline pub/grant parsing | 39–44, 62–84, 474–494, 577–589 | Pure functions — extract to `_discover/`; unit-test without HTTP or MCP | 7, 9 |
| `discover_get_filter_options` returns an unbounded option list | 690–699 | Bound it, and/or add `ResponseLimitingMiddleware` as a backstop | 6 |
| `page` / `per_page` / `has_more` hand-rolled | 234, 450–503, 553–598 | **Correct — keep.** FastMCP has no upstream-pagination helper | 7 |
| Tests call decorated functions directly with `XInput(...)` | `tests/test_server.py` 21–87 | Keep the payload assertions; drive through `Client(mcp)` so lifespan + flat params work | 9 |
| `main.py` prints a greeting, not on the run path | `main.py` 1–6 | Make it `__main__.py` calling `mcp.run()`, or delete | 7 |

---

## 14. Prioritized redesign list

Ordered so the highest-value, lowest-risk work lands first. **Effort** assumes familiarity with the
code; **risk** is the chance of breaking a working consumer.

### A. Correctness fixes — do these first

| # | Change | Why | Effort | Risk |
| --- | --- | --- | --- | --- |
| **A1** | **Raise `ToolError` instead of returning `"Error: …"`.** Rewrite `_handle_error` to raise; delete the five blanket `except Exception` handlers; use `raise … from e`. | Failures currently reach clients as **successes** — the model cannot tell a 404 from a result. A bug, not a style question. | ~30 min | **Medium** — client-visible by design. Write the `pytest.raises(ToolError)` test first (§9); it fails today. |
| **A2** | **A regression test per failure mode** (404, 429, timeout, malformed payload). | Zero coverage of failure paths today; A1 is unverifiable without it. | ~30 min | None |
| **A3** | **Bound `discover_get_filter_options`**, and/or add `ResponseLimitingMiddleware`. | Enumerates every department/tag with no limit, straight into the context window. | ~15 min | Low |

### B. Idiom alignment — the substance of the redesign

| # | Change | Why | Effort | Risk |
| --- | --- | --- | --- | --- |
| **B1** | **Typed Pydantic return models; drop `json.dumps` and `-> str`.** | Turns five opaque JSON strings into schema'd `structuredContent`. Text blocks still emitted → **no client breakage**. Deletes ~100 lines of hand-written `Returns:` prose. | ~1–1.5 h | **Low** — additive on the wire |
| **B2** | **Shared `httpx.AsyncClient` via `@lifespan`.** | Removes five duplicated blocks; restores connection/TLS reuse. Use `lifespan`, **not** `Depends()`. | ~30 min | Low–Medium — changes what `pytest-httpx` intercepts; pair with B3 |
| **B3** | **Add `Client(mcp)` MCP-layer tests; migrate the existing four to run through it.** | Locks in registration, schemas, annotations, and A1's error behaviour. Prerequisite for B2 and B6. | ~1 h | None |
| **B4** | **`ResponseCachingMiddleware` (TTL ~15 min) + `RetryMiddleware` with httpx exception types.** | Both built in. Large upstream-load and resilience win for an idempotent read-only scraper. ⚠️ **Must follow A1**; defaults don't match httpx. | ~30 min | **Medium** — stale reads if TTL too long; start conservative |
| **B5** | **Fix docstrings: move `Examples:` into leading prose (or `description=`), delete `Returns:` blocks.** | Prevents silent loss of few-shot guidance from all five descriptions. | ~45 min | Low — but **verify the premise (§12) before acting** |
| **B6** | **Flatten `params: XInput` wrappers to `Annotated[...]` parameters.** | The documented idiom; flattens the schema LLM clients see; removes the `Args:` sections driving B5. Strictness survives (OBSERVED, §8). | ~1 h | **High — and it is the one change that deliberately breaks the `{"params": {…}}` argument envelope the prior pass verified as stable.** Every saved call site and stored prompt changes shape. Standalone, announced, and only worth doing because the goal is idiom over minimal-diff. |
| **B7** | **Add `@mcp.tool(timeout=…)`.** | No execution ceiling today; unbounded once B4's retries exist. | ~10 min | Low |
| **B8** | **`ctx: Context` + `ctx.warning(...)` on suspicious upstream shapes.** | Restores the diagnostics A1 stops discarding. Logging only — skip progress/sampling/elicitation. | ~30 min | Low |

### C. Optional polish

| # | Change | Why | Effort | Risk |
| --- | --- | --- | --- | --- |
| **C1** | **Extract `_discover/` (transport + parsing) into modules.** | Makes the bug-prone pure parsing functions testable without HTTP. Note 707 lines is **within** FastMCP's own 1,000-line gate — justify by testability, not length. | ~1.5 h | Low, but a large diff |
| **C2** | **Modernise typing** (`Optional[X]` → `X \| None`, `List` → `list`). | Dated style; free on 3.12. Fold into another change rather than doing alone. | ~10 min | None |
| **C3** | **Resolve `main.py`** → `__main__.py` calling `mcp.run()`, or delete it. | A stub that prints a greeting and is not on the run path. | ~10 min | None |
| **C4** | **Add `instructions=` to `FastMCP(...)`.** | Server-level description of what this server is for; currently absent. | ~10 min | None |
| **C5** | **`fastmcp.json`.** | "Canonical and preferred" project config — but `mcp.json` already works. Copy `examples/atproto_mcp/fastmcp.json`; several shipped examples are invalid. | ~20 min | None |

### Suggested sequencing

**A1 → A2 → B1 → B3 → B2 → B7 → B4** is the high-value spine, and the order matters twice: A1 must
precede B4 (or errors get cached), and B3 must land before B2 (or the tests can't follow the client
into the lifespan). **B5** needs its premise verified (§12) before you spend the time. **B6** is the
one genuinely breaking change — do it alone, after everything else is green.

C-items are independent and can be picked up whenever.

### Explicitly NOT recommended

`mount`/`import_server` composition · resources and resource templates · prompts · `ToolResult` ·
tags/visibility · tool transformation · `mask_error_details` · `RateLimitingMiddleware` ·
background tasks (`task=True`) · `Shared()` · sampling · elicitation · progress reporting · auth.

Each is argued in the numbered section above; none is dismissed on "not strictly necessary" grounds
alone.
