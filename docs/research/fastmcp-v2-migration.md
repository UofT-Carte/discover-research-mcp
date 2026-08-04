# Migrating `discover-research-mcp` to standalone FastMCP

**Retrieval date: 2026-08-04.** Every version number, API claim, and quotation below was fetched
from a primary source during this session (PyPI JSON API, the projects' GitHub repos at specific
tags, and the official docs sites). **Version numbers age fast** — both projects shipped major
releases in the week before this was written. Re-check the PyPI JSON endpoints before acting on
anything here if more than a few weeks have passed.

Claims are labelled **OBSERVED** (a command was run and its output read in-session) or
**INFERRED** (reasoned from source code that was read but not executed). Anything that could not
be verified is called out explicitly in [§8](#8-what-could-not-be-verified) rather than guessed.

---

## 0. Important correction to the premise (read first)

The task that produced this document asked about migrating to **"FastMCP v2"**. That target no
longer exists as a current release. The decision to move off the SDK-bundled FastMCP is not being
re-litigated here — it is correct and, as §6 shows, effectively forced. But the *version* target
needs restating:

| What the request assumed | What is actually current (2026-08-04) |
| --- | --- |
| Standalone FastMCP is at v2 | Stable standalone FastMCP is **3.4.5** |
| `mcp` bundles FastMCP under `mcp.server.fastmcp` | True only for `mcp` **1.x**. `mcp` **2.0.0** removed that module entirely |

**This document targets FastMCP 3.4.5**, the current stable release. The filename retains
`fastmcp-v2-migration.md` as specified in the request; the content is 3.4.5.

FastMCP v2 is two major lines back. The v2 → v3 breaking-change list is summarised in
[§7](#7-if-you-had-actually-landed-on-v2) so the gap is visible, but you should not target v2.

---

## 1. Versions and status

### 1.1 Current released versions

| Package | Version | Released | Requires Python | Source |
| --- | --- | --- | --- | --- |
| `fastmcp` (standalone) | **3.4.5** | 2026-07-27 | `>=3.10` | [PyPI JSON API](https://pypi.org/pypi/fastmcp/json) |
| `mcp` (official SDK) | **2.0.0** | 2026-07-28 | `>=3.10` | [PyPI JSON API](https://pypi.org/pypi/mcp/json) |

OBSERVED — `curl https://pypi.org/pypi/fastmcp/json | jq` reported `info.version = "3.4.5"` with
`upload_time_iso_8601 = 2026-07-27T19:19:57Z`; `https://pypi.org/pypi/mcp/json` reported
`info.version = "2.0.0"` with `upload_time_iso_8601 = 2026-07-28T13:45:28Z`.

Two adjacent releases matter for planning:

- **`mcp` 1.29.0** (2026-07-28T13:41:40Z) is the last 1.x release, published four minutes before
  2.0.0. It is the top of the maintenance line this repo currently sits on.
- **`fastmcp` 4.0.0b1** (2026-07-28T21:18:12Z) is a **beta**, not stable. See §1.4.

### 1.2 The repo moved — `jlowin/fastmcp` is now `PrefectHQ/fastmcp`

OBSERVED — `curl -I https://github.com/jlowin/fastmcp` returns `HTTP 301` with
`location: https://github.com/PrefectHQ/fastmcp`. The canonical source repo is
<https://github.com/PrefectHQ/fastmcp>, and PyPI metadata for `fastmcp-slim` lists
`"Repository": "https://github.com/PrefectHQ/fastmcp"`. FastMCP is maintained by
[Prefect](https://www.prefect.io/). Old links still resolve via redirect, but cite the new org.

### 1.3 What each project's maintainers say about the other

**FastMCP's side** — from the [FastMCP README](https://github.com/PrefectHQ/fastmcp/blob/main/README.md):

> "FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024. Today, the actively
> maintained standalone project is downloaded a million times a day, and some version of FastMCP
> powers 70% of MCP servers across all languages."

And from the v3.4.5 upgrade guide,
[`docs/getting-started/upgrading/from-mcp-sdk.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/getting-started/upgrading/from-mcp-sdk.mdx):

> "If your server starts with `from mcp.server.fastmcp import FastMCP`, you're using FastMCP 1.0 —
> the version bundled with v1 of the `mcp` package. Upgrading to the standalone FastMCP framework
> is easy. **For most servers, it's a single import change.**"
>
> "FastMCP 1.0 pioneered the Pythonic MCP server experience, and we're proud it was bundled into
> the `mcp` package. The standalone FastMCP project has since grown into a full framework for
> taking MCP servers from prototype to production."

**The SDK's side** — the official SDK did not deprecate the bundled FastMCP; in v2 it **renamed and
replaced** it. From the [SDK v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/):

> "**FastMCP renamed to MCPServer.** The `FastMCP` class has been renamed to `MCPServer` to better
> reflect its role as the main server class in the SDK."
>
> "All submodules under `mcp.server.fastmcp.*` are now under `mcp.server.mcpserver.*` with the same
> structure."

The guide lists the symptom of migrating without changing imports:
`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`.

And from the [SDK README](https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md):

> "**Not ready to migrate?** v1.x lives on the `v1.x` branch, continues to receive critical bug
> fixes and security patches... Since `pip install mcp` now installs 2.x, keep a `<2` upper bound
> on your requirement (for example `mcp>=1.28,<2`) until you've migrated."

**Net reading of both statements:** the name `FastMCP` inside the official SDK is retired. Anyone
on `from mcp.server.fastmcp import FastMCP` has exactly two forward paths — the SDK's new
`MCPServer` class, or standalone `fastmcp`. Staying put is a maintenance line, not a destination.
This repo has chosen standalone FastMCP.

### 1.4 Why target 3.4.5 and not 4.0.0b1

Beyond 4.0.0b1 being a beta, its dependency graph is a different world. OBSERVED, from the PyPI
JSON for each version's `fastmcp-slim`:

| | `fastmcp` 3.4.5 | `fastmcp` 4.0.0b1 |
| --- | --- | --- |
| Official SDK pin | `mcp<2.0,>=1.24.0` | `mcp<3.0.0,>=2.0.0` |
| HTTP client | `httpx<1.0,>=0.28.1` | `httpx2>=2.5.0` |

FastMCP 4 rides the SDK v2 rewrite and swaps `httpx` for `httpx2`. **This repo depends on `httpx`
directly** (`server.py` uses `httpx.AsyncClient`, and `pytest-httpx` mocks it), so a jump to
FastMCP 4 drags in a second, differently-named HTTP stack alongside your own. Target 3.4.5, which
keeps `httpx<1.0,>=0.28.1` — the exact constraint the repo already satisfies with `httpx>=0.28.1`.

### 1.5 Packaging note: `fastmcp` is now a meta-package

OBSERVED — `fastmcp` 3.4.5's only base requirement is `fastmcp-slim[client,server]==3.4.5`. The
real code lives in the `fastmcp-slim` distribution, which still imports as `fastmcp`. In the source
repo the code is under `fastmcp_slim/fastmcp/…`, not `src/fastmcp/…` — worth knowing when reading
upstream source, since the older path 404s.

You still just write `uv add fastmcp`. Nothing about the import name changes.

---

## 2. API delta for what this server actually uses

Scope note: `server.py` uses a small slice of the framework — one constructor, five
`@mcp.tool(...)` decorators with `name=` and `annotations=`, pydantic input models, `-> str`
returns, and `mcp.run()`. It uses no resources, no prompts, no `Context`, and no lifespan. The
delta below is confined to that slice.

### 2.1 The import — the only strictly required change

```python
# Before — server.py line 15
from mcp.server.fastmcp import FastMCP

# After
from fastmcp import FastMCP
```

Source: [`docs/getting-started/upgrading/from-mcp-sdk.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/getting-started/upgrading/from-mcp-sdk.mdx),
which states "That's it. Your `@mcp.tool`, `@mcp.resource`, and `@mcp.prompt` decorators, your
`mcp.run()` call, and the rest of your server code all work as-is."

`FastMCP`, `Client`, and `Context` are all exported from the top-level package
([`fastmcp_slim/fastmcp/__init__.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/__init__.py)).

### 2.2 The constructor — unchanged for this server

```python
mcp = FastMCP("discover_research_mcp")   # server.py line 17 — works verbatim
```

INFERRED from
[`fastmcp_slim/fastmcp/server/server.py` line 321](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py):
the signature is `def __init__(self, name: str | None = None, instructions: str | None = None, *, …)`.
The first positional parameter is still the server name.

What v3 **removed** from the constructor (all raise `TypeError` with a migration hint via
`_check_removed_kwargs`): `host`, `port`, `log_level`, `debug`, `sse_path`,
`streamable_http_path`, `json_response`, `stateless_http`, `message_path`, `on_duplicate_tools`,
`on_duplicate_resources`, `on_duplicate_prompts`, `tool_serializer`, `include_tags`,
`exclude_tags`, `tool_transformations`. Source:
[`from-fastmcp-2.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/getting-started/upgrading/from-fastmcp-2.mdx).

**This server passes none of them**, so the constructor line needs no edit. Useful new kwargs are
covered in §5.

### 2.3 The tool decorator — `name=` and `annotations=` both survive

The repo's existing form works unchanged:

```python
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
    ...
```

INFERRED from the decorator signature at
[`server/server.py` line 1737](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py):

```python
def tool(
    self,
    name_or_fn: str | AnyFunction | None = None,
    *,
    name: str | None = None,
    ...
    annotations: ToolAnnotations | dict[str, Any] | None = None,
    output_schema: dict[str, Any] | NotSetT | None = NotSet,
    ...
)
```

Two things to note:

- **`annotations` accepts a plain `dict`**, exactly as the repo passes it — the union type is
  `ToolAnnotations | dict[str, Any] | None`, and the implementation coerces via
  `if isinstance(annotations, dict): annotations = ToolAnnotations(**annotations)`. camelCase keys
  (`readOnlyHint`) are correct. The docs use `ToolAnnotations` in examples "for consistency and
  stronger editor/type support" but explicitly say "FastMCP accepts either a plain dict or
  `ToolAnnotations`" ([`docs/servers/tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).
  **No change needed to any of the five tools.**
- Both `@mcp.tool` (bare) and `@mcp.tool(...)` (called) are supported. The docstring lists
  `@server.tool`, `@server.tool()`, `@server.tool("custom_name")`, `@server.tool(name="…")`, and
  the direct call `server.tool(fn, name="…")`. The repo's called form is fine; there is no need to
  churn the decorators.

### 2.4 The decorator now returns the **original function** (this is good news for the tests)

This is the single most consequential behavioural difference, and it goes the *helpful* direction.

In the SDK's bundled FastMCP 1.0, `@mcp.tool` returned a `FunctionTool` object. In FastMCP 3.4.5
the decorator attaches metadata to the function and returns the function itself.

OBSERVED in
[`fastmcp_slim/fastmcp/server/providers/local_provider/decorators/tools.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/providers/local_provider/decorators/tools.py):
the decorator body checks `if fastmcp.settings.decorator_mode == "object":` and only then returns
the tool object; otherwise it sets `target.__fastmcp__ = metadata` and executes `return fn`.
The parallel implementation in
[`fastmcp_slim/fastmcp/tools/function_tool.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_tool.py)
carries the deprecation warning verbatim:

> `"decorator_mode='object' is deprecated and will be removed in a future version. Decorators now
> return the original function with metadata attached."`

Confirmed in the upgrade guide:

> "In FastMCP 1.0, `@mcp.tool` returned a `FunctionTool` object. Now decorators return your
> original function unchanged — so decorated functions stay callable for testing, reuse, and
> composition."

**Consequence for this repo:** `tests/test_server.py` calls the decorated functions directly —
`await discover_search_scholars(SearchScholarsInput(query="AI", tag_filter="Machine learning"))`,
four times. **Those call sites keep working.** No test rewrite is forced by the migration.

> One caveat worth reading carefully before trusting the type checker: the `@overload` stubs on
> `FastMCP.tool` annotate `-> F` (the original function), but the concrete implementation's return
> annotation is `Callable[[AnyFunction], FunctionTool] | FunctionTool | partial[…]`. The overloads
> and the runtime behaviour agree (function is returned); the implementation's annotation appears
> stale. Trust the runtime behaviour and the overloads, not the implementation annotation.

If anything in your code reached for `.name` or `.description` on a decorated result, that breaks —
the escape hatch is the env var `FASTMCP_DECORATOR_MODE=object`, which is itself deprecated.
**Nothing in this repo does that**, so the hatch is not needed.

### 2.5 Input schemas from pydantic models — shape preserved, `$ref` handling changed

**The "before" state, OBSERVED.** Running the repo's own server against its installed
`mcp` 1.26.0 (`.venv/bin/python`, read-only, nothing installed) and calling `mcp.list_tools()`
produced, for all five tools:

```text
discover_search_scholars -> top-level properties: ['params'] | required: ['params']
   params entry: {"$ref": "#/$defs/SearchScholarsInput"}
discover_get_scholar     -> top-level properties: ['params'] | required: ['params']
   params entry: {"$ref": "#/$defs/GetScholarInput"}
… (same shape for publications, grants, filter_options)
```

So today the single-model parameter is **nested** under `params` via a `$ref`, with the model in
`$defs`, and field `title`s present (`"title": "Query"` etc.).

**The "after" state.** FastMCP 3.4.5 builds the input schema with
`input_type_adapter = get_cached_typeadapter(wrapper_fn)` followed by
`input_type_adapter.json_schema()`
([`fastmcp_slim/fastmcp/tools/function_parsing.py` ~line 250](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py)) —
that is, a pydantic `TypeAdapter` over the function itself.

OBSERVED — the underlying pydantic behaviour was checked directly against the repo's own pydantic:

```python
async def f(params: SearchScholarsInput) -> str: ...
TypeAdapter(f).json_schema()
# top-level properties: ['params']
# params: {"$ref": "#/$defs/SearchScholarsInput"}
# required: ['params']
```

**So the nesting under `params` is preserved.** Tool arguments keep the same
`{"params": {...}}` envelope; saved prompts and agent call sites that pass
`{"params": {"query": "…"}}` continue to work. This was the highest-risk unknown and it lands
safely.

Two **cosmetic but client-visible** differences remain — see §6.3 and §6.4: `$ref`s get inlined by
default, and field `title`s are pruned.

### 2.6 Descriptions and docstrings

Tool descriptions still come from the function docstring, so the long docstrings in `server.py`
carry over. FastMCP additionally **parses the docstring's `Args:` section and injects parameter
descriptions into the schema** where a field has no description of its own
([`function_parsing.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py)):

```python
if parsed_docstring.parameters:
    properties = input_schema.get("properties", {})
    for param_name, param_desc in parsed_docstring.parameters.items():
        if param_name in properties and "description" not in properties[param_name]:
            properties[param_name]["description"] = param_desc
```

Note the precedence: explicit `Field(description=...)` wins. Every field in this repo's five input
models already has a `Field(description=...)`, so the docstring injection is a no-op for the model
fields. It applies to the top-level `params` property, which currently has no description.

### 2.7 Error handling — `ToolError` vs. this server's current pattern

**Current behaviour is the thing to understand here.** All five tools wrap their body in
`try/except Exception` and `return _handle_error(e)` — a *string*. On the wire that is a
**successful tool result whose text happens to start with `"Error: "`**. The client is never told
the call failed; `isError` is not set.

FastMCP's model, from
[`docs/servers/tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx):

> "If your tool encounters an error, you can raise a standard Python exception (`ValueError`,
> `TypeError`, `FileNotFoundError`, custom exceptions, etc.) or a FastMCP `ToolError`. By default,
> all exceptions (including their details) are logged and converted into an MCP error response to
> be sent back to the client LLM."
>
> "Error messages from `ToolError` are always sent to clients, regardless of `mask_error_details`
> setting… When `mask_error_details=True`, only error messages from `ToolError` will include
> details, other exceptions will be converted to a generic message."

`ToolError` lives at `fastmcp.exceptions.ToolError` and subclasses `FastMCPError`
([`fastmcp_slim/fastmcp/exceptions.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/exceptions.py)).

Before / after for this server's `_handle_error`:

```python
# Before — server.py, current pattern (error is a *successful* result)
    except Exception as e:
        return _handle_error(e)

# After — surfaces as a real MCP error (isError=true)
from fastmcp.exceptions import ToolError

def _handle_error(e: Exception) -> "NoReturn":
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            raise ToolError("Resource not found. Check that the scholar ID is correct.")
        if e.response.status_code == 429:
            raise ToolError("Rate limit exceeded. Please wait before retrying.")
        raise ToolError(f"API returned status {e.response.status_code}")
    if isinstance(e, httpx.TimeoutException):
        raise ToolError("Request timed out. Please try again.")
    raise ToolError(f"{type(e).__name__}: {e}")
```

**This is a client-visible behaviour change, not a refactor.** It is a genuine improvement — the
current design hides failures from the model — but it changes what callers see and should be its
own reviewed step, not folded into the import swap. See the sequence in §9 (step 6).

Two things must change alongside the function body, or you get a silent regression:

- **The five call sites.** They currently read `return _handle_error(e)`. Since the rewritten
  helper is `-> NoReturn` (it always raises), they must become a bare `_handle_error(e)`. Leaving
  `return` in place is harmless once the helper always raises, but leaving the helper's old
  `return` paths while call sites still `return` would hand the client `None` instead of the
  previous error string.
- **The blanket `except Exception`** would swallow a `ToolError` raised inside the `try` block; if
  you adopt this, `ToolError` must be re-raised explicitly or raised outside the handler (§6.6).

### 2.8 Context and lifespan — not relevant today

Neither is used by this server. For completeness: `Context` is injected by type annotation
(`async def tool(..., ctx: Context)`), documented at
[`docs/servers/context.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/context.mdx),
and `lifespan=` is a constructor kwarg
([`server/server.py` line 333](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py),
docs at [`docs/servers/lifespan.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/lifespan.mdx)).

A lifespan is the natural home for a **shared `httpx.AsyncClient`** — this server currently opens
and closes a fresh `async with httpx.AsyncClient()` on every single tool call, throwing away
connection pooling and TLS session reuse across all five tools. That is a real (if modest)
efficiency win available post-migration, but it is orthogonal to the migration itself and would
also change what `pytest-httpx` intercepts. Treat as follow-up work, not migration scope.

---

## 3. Entrypoint and run story

### 3.1 `mcp.run()` and transports

`mcp.run()` is unchanged and still defaults to stdio. From
[`docs/deployment/running-server.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/deployment/running-server.mdx),
the three transports are:

| Transport | Invocation | Status |
| --- | --- | --- |
| **STDIO** | `mcp.run()` (default) | What Claude Desktop and CLI tools expect |
| **HTTP (Streamable)** | `mcp.run(transport="http", host="127.0.0.1", port=8000)` | Endpoint at `http://localhost:8000/mcp` |
| **SSE** | `mcp.run(transport="sse", host=…, port=…)` | Legacy — "exists only for backward compatibility and shouldn't be used in new projects" |

Host/port are arguments to `run()` now, **not** to the constructor (§2.2). An async variant
`await mcp.run_async(transport="http", port=8000)` and an ASGI factory `mcp.http_app()` also exist.

**This server is stdio and should stay stdio** — it is a local, single-user tool launched by the
MCP client. `server.py`'s existing block needs no edit:

```python
if __name__ == "__main__":
    mcp.run()
```

### 3.2 `main.py` — not on the run path

`main.py` is a 6-line stub that prints `"Hello from discover-research-mcp!"`. It contains no MCP
wiring and is not referenced by `mcp.json`. **Nothing in it must change for the migration.**

It is, however, the conventional entrypoint a reader would look for. If you want to tidy it, the
honest options are (a) delete it, or (b) make it the real entrypoint:

```python
# main.py — optional consolidation
from server import mcp

def main():
    mcp.run()

if __name__ == "__main__":
    main()
```

If you take option (b), update `mcp.json` to `["run", "python", "main.py"]` and consider a
`[project.scripts]` entry in `pyproject.toml`. This is optional cleanup — call it out as such
rather than bundling it into the migration diff.

### 3.3 `mcp.json` — no change required

```json
{
  "mcpServers": {
    "discover-research-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "/Users/alex/code/work/discover-research-mcp"
    }
  }
}
```

`uv run python server.py` continues to work: the transport is still stdio, the module still
executes `mcp.run()` under `__main__`. **No edit needed.**

Optional alternative — FastMCP ships its own CLI (`fastmcp run server.py`, `fastmcp inspect
server.py`, `fastmcp version`), documented in
[`running-server.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/deployment/running-server.mdx).
`fastmcp inspect server.py` is a useful one-shot post-migration check that all five tools still
register. Using the CLI as the *launcher* in `mcp.json` is not necessary and adds a moving part;
the recommendation is to leave `mcp.json` alone.

### 3.4 `pyproject.toml`

```toml
# Before
dependencies = [
    "beautifulsoup4>=4.14.3",
    "httpx>=0.28.1",
    "mcp[cli]>=1.26.0",
]

# After
dependencies = [
    "beautifulsoup4>=4.14.3",
    "httpx>=0.28.1",
    "fastmcp>=3.4.5,<4",
]
```

Rationale for each part:

- **Drop `mcp[cli]` as a direct dependency.** `fastmcp` pulls `mcp` in transitively (§6.1), so the
  import surface is not lost. The `cli` extra was only providing the `mcp` command; FastMCP's own
  CLI replaces it.
- **Add the `<4` upper bound.** Without it, a future `uv lock --upgrade` can pull FastMCP 4, which
  swaps the stack to `mcp>=2.0` and `httpx2` (§1.4). Given this repo uses `httpx` directly, that
  upgrade needs to be a deliberate, tested decision.

`requires-python = ">=3.12"` needs no change — FastMCP 3.4.5 requires `>=3.10`, which 3.12
satisfies (OBSERVED, PyPI `info.requires_python`).

---

## 4. Testing

### 4.1 Yes — v3 ships an in-memory client, and it needs no network or subprocess

`Client(mcp)` connects straight to the server object with no transport, no port, and no
subprocess. From
[`docs/patterns/testing.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/patterns/testing.mdx):

> "Using Pytest Fixtures, you can wrap your FastMCP Server in a Client instance that makes
> interacting with your server fast and easy… enables a tight development loop by allowing you to
> avoid using a separate tool like MCP Inspector during development."

The docs' own fixture pattern:

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

The repo's `asyncio_mode = "auto"` in `pyproject.toml` is already exactly what the FastMCP testing
docs recommend ("We recommend configuring pytest to automatically handle async tests by setting the
asyncio mode to `auto`"), so no pytest config change is needed.

### 4.2 Concrete example for *this* server — and it composes with `pytest-httpx`

This is the important point: the in-memory client and `pytest-httpx` solve **different problems**
and belong together.

- `Client(mcp)` exercises the **MCP layer** — registration, schema, argument envelope,
  serialisation, error mapping.
- `pytest-httpx` mocks the **upstream** `discover.research.utoronto.ca` calls so tests stay
  hermetic and fast.

A test that uses both, written against this server's real tool and real payload contract:

```python
# tests/test_server_mcp.py
import json
import pytest
from fastmcp import Client
from pytest_httpx import HTTPXMock

from server import mcp

FAKE_RESPONSE = {
    "pagination": {"startFrom": 0, "perPage": 20, "total": 1, "totalIsLowerBound": False},
    "sort": "relevance",
    "resource": [],
    "filters": [],
}


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c


async def test_all_five_tools_register(client):
    tools = await client.list_tools()
    assert {t.name for t in tools} == {
        "discover_search_scholars",
        "discover_get_scholar",
        "discover_get_scholar_publications",
        "discover_get_scholar_grants",
        "discover_get_filter_options",
    }


async def test_read_only_annotation_survives_migration(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert tools["discover_search_scholars"].annotations.readOnlyHint is True


async def test_tag_filter_reaches_upstream_through_the_mcp_layer(
    client, httpx_mock: HTTPXMock
):
    """End-to-end: MCP argument envelope -> pydantic model -> upstream payload."""
    httpx_mock.add_response(json=FAKE_RESPONSE)

    result = await client.call_tool(
        "discover_search_scholars",
        {"params": {"query": "AI", "tag_filter": "Machine learning"}},
    )

    # Upstream contract (the bug this repo already regression-tests)
    body = json.loads(httpx_mock.get_requests()[-1].content)
    tags_filter = next(f for f in body["filters"] if f["name"] == "tags")
    assert "selectedValues" not in tags_filter
    assert tags_filter["values"] == ["Machine learning"]

    # MCP contract
    assert result.data is not None
```

Note the `{"params": {...}}` envelope in `call_tool` — that is the nesting confirmed in §2.5.

### 4.3 Does `pytest-httpx` still have a role? Yes — keep it

**Keep `pytest-httpx`.** It mocks `httpx`, which is what `server.py` uses to talk to the upstream
portal. FastMCP's in-memory client does not and cannot replace it: the two operate at opposite ends
of the tool. The existing four tests in `tests/test_server.py` are upstream-payload regression tests
(they encode the `values` vs `selectedValues` bug fixed in commit `549e230`) and are **worth
preserving unchanged** — as established in §2.4, their direct-call style still works.

The recommended end state is both layers:

| Layer | Tool | What it proves |
| --- | --- | --- |
| Upstream payload | `pytest-httpx` + direct function calls (existing tests) | Filter serialisation is correct |
| MCP surface | `Client(mcp)` (new tests) | Tools register, schemas/annotations are right, envelope works |

Given `tests/test_server.py` is only 86 lines and covers one tool of five, the migration is a
natural moment to add the MCP-layer file. That is optional scope, not required by the migration.

---

## 5. Features worth adopting for a read-only, scraper-backed server

| Feature | What it does | Call |
| --- | --- | --- |
| **Tool annotations (read-only hints)** | Advertises `readOnlyHint` / `idempotentHint` / `openWorldHint` so clients can skip confirmation prompts and batch more aggressively | **ALREADY ADOPTED — keep as-is.** All five tools already pass the full annotation set, and dicts remain valid in v3 (§2.3); this needs zero work |
| **Structured output / output schemas** | Returns machine-readable `structuredContent` alongside text, so clients deserialise instead of re-parsing | **ADOPT (deliberately, as its own step).** See below — this is the highest-value change available |
| **`ToolError`** | Turns failures into real MCP errors instead of success-with-`"Error: "`-text | **ADOPT.** The current pattern actively hides failures from the model (§2.7) |
| **Tool result types (`ToolResult`)** | Hand-control over content blocks and metadata per result | **SKIP.** Only needed for mixed media or custom serialisation; returning dicts covers this server |
| **Server composition** (`import_server` / mounting, providers) | Combine multiple servers into one surface | **SKIP.** One 707-line module, five cohesive tools, one upstream API. Nothing to compose |
| **Auth** (OAuth proxy, JWT, token verification) | Authenticates inbound MCP clients | **SKIP.** Local stdio server, single user, and the upstream portal is public and unauthenticated. Auth protects a network boundary that does not exist here |
| **Middleware** | Cross-cutting hooks (logging, timing, rate limiting) | **SKIP for now.** Plausible later home for caching/rate-limiting against the upstream portal; no current need |
| **`mask_error_details=True`** | Suppresses non-`ToolError` exception detail to clients | **SKIP.** Scraping a public portal — leaking a stack trace is not a security concern, and detail helps debugging |

### The structured-output opportunity (and why it is a judgement call)

Every tool here is declared `-> str` and returns `json.dumps(result, indent=2)`. The client
therefore receives a JSON *string* it must parse a second time.

OBSERVED — under the current `mcp` 1.26.0 the tools already advertise a wrapper output schema:

```json
{"properties": {"result": {"title": "Result", "type": "string"}},
 "required": ["result"], "title": "discover_search_scholarsOutput", "type": "object"}
```

That is a schema saying "this returns a string" — technically structured, semantically useless.

FastMCP's rules ([`docs/servers/tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)):

> "**Object-like results** (`dict`, Pydantic models, dataclasses) → Always become structured content
> (even without output schema). **Non-object results** (`int`, `str`, `list`) → Only become
> structured content if there's an output schema to validate/serialize them. **All results** →
> Always become traditional content blocks for backward compatibility."

For primitives FastMCP wraps under a `"result"` key and stamps `"x-fastmcp-wrap-result": true`
(INFERRED from
[`function_parsing.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py),
which builds `_WrappedResult[T]` and sets that key when the schema is non-object).

So the change is mechanically tiny — drop the `json.dumps` and the `-> str`:

```python
# Before
async def discover_search_scholars(params: SearchScholarsInput) -> str:
    ...
    return json.dumps(result, indent=2)

# After
async def discover_search_scholars(params: SearchScholarsInput) -> dict:
    ...
    return result          # dict -> automatic structuredContent + text block
```

**But it changes the wire format for every consumer**, and a richer typed return (a pydantic output
model rather than bare `dict`) would give a genuinely useful output schema instead of an untyped
object. That design choice — bare `dict` now, or typed models — is the judgement call. Do it as a
separate, reviewed step *after* the migration is green (§9, step 7), not inside it.

---

## 6. Gotchas and breaking changes

### 6.1 Coexistence: `fastmcp` **depends on** `mcp` — but caps it below 2.0

OBSERVED — `fastmcp` 3.4.5 → `fastmcp-slim[client,server]==3.4.5` → `mcp<2.0,>=1.24.0` (the `mcp`
pin appears under the `client`, `server`, and `mcp` extras).

Two halves, and the second is the one that bites:

1. **They coexist by construction.** Installing `fastmcp` *installs* `mcp`. Any lingering
   `import mcp.types` keeps working, and a staged migration where some code still touches `mcp.*`
   is fine. The upgrade guide says so explicitly: "FastMCP includes the `mcp` package as a
   dependency, so you don't lose access to anything."
2. **You cannot have `mcp` 2.0 and `fastmcp` 3.4.5 together.** The `<2.0` cap makes them mutually
   exclusive. If anything in the project ever needs SDK v2, that forces FastMCP 4 — and with it
   `httpx2` (§1.4). Plan the two as a single future move, not independently.

### 6.2 ⚠️ The pre-migration repo has a live, unbounded-dependency break

`pyproject.toml` pins `"mcp[cli]>=1.26.0"` — **no upper bound**. `mcp` 2.0.0 is now what
`pip install mcp` / an unconstrained resolve produces, and OBSERVED by listing the wheel contents:

```
$ unzip -l mcp-2.0.0-py3-none-any.whl | grep -i fastmcp
NO fastmcp module in mcp 2.0.0
```

`mcp/server/` in 2.0.0 contains `connection.py`, `session.py`, `stdio.py`, … and **no `fastmcp`
subpackage**. So a bare `uv lock --upgrade` today resolves `mcp` to 2.0.0 and `server.py` line 15
dies with:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

The SDK README states the mitigation directly: "keep a `<2` upper bound on your requirement (for
example `mcp>=1.28,<2`) until you've migrated."

**This is the strongest practical argument for doing the migration now rather than later** — the
current dependency spec is one lockfile refresh away from breaking. (The repo's `.venv` is
currently pinned at `mcp` 1.26.0, OBSERVED, so nothing is broken *right now*.)

### 6.3 🔇 Silent wire-format change: `$ref`s are inlined by default

The `FastMCP.__init__` signature includes `dereference_schemas: bool = True`
([`server/server.py` line 337](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/server/server.py)),
and the constructor body appends a middleware when it is on (line ~450):

```python
if dereference_schemas:
    from fastmcp.server.middleware.dereference import DereferenceRefsMiddleware
    self.middleware.append(DereferenceRefsMiddleware())
```

Per [`docs/servers/tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx):

> "FastMCP automatically dereferences `$ref` entries in tool schemas to ensure compatibility with
> MCP clients that don't fully support JSON Schema references (e.g., VS Code Copilot, Claude
> Desktop). This means complex Pydantic models with shared types are inlined in the schema rather
> than using `$defs` references."

**Effect on this server:** today's `{"params": {"$ref": "#/$defs/SearchScholarsInput"}}` plus a
`$defs` block becomes an inlined object schema. The **nesting under `params` and the accepted
argument shape do not change** (§2.5) — only the schema's internal representation. It is
semantically equivalent and generally an improvement for client compatibility, but it *will* show
up in any snapshot test or golden file of the tool schema. Opt out with
`FastMCP("discover_research_mcp", dereference_schemas=False)` if you need byte-stability.

### 6.4 Field `title`s are pruned from schemas

INFERRED from
[`function_parsing.py`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/fastmcp_slim/fastmcp/tools/function_parsing.py):
`input_schema = compress_schema(input_schema, prune_params=prune_params, prune_titles=True)`, and
similarly `compress_schema(output_schema, prune_titles=True)`.

Today's schemas carry `"title": "Query"`, `"title": "Search By"`, etc. (OBSERVED, §2.5). After
migration those disappear. Cosmetic and token-saving; only matters for schema snapshots.

### 6.5 Input validation is *coercive* by default

`strict_input_validation` defaults to off, meaning "FastMCP uses Pydantic's flexible validation that
coerces compatible inputs" — `"10"` is accepted for an `int`
([`docs/servers/tools.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/servers/tools.mdx)).

Relevant here because `page` / `per_page` are `int` with `ge`/`le` bounds: a model sending
`"page": "2"` succeeds rather than erroring. This is intentional LLM-friendliness and the docs
recommend the default, but it is worth knowing that the `pattern=` and `ge=`/`le=` constraints on
the models are still enforced *after* coercion. Opt into strictness with
`FastMCP(..., strict_input_validation=True)`.

### 6.6 Blanket `except Exception` will swallow `ToolError`

Not a framework breaking change, but a migration trap specific to this code: every tool wraps its
body in `except Exception: return _handle_error(e)`. If you adopt `ToolError` (§2.7) and raise it
*inside* that `try`, the handler catches it and converts it back to a success string. Re-raise
`ToolError` explicitly or restructure the handler.

### 6.7 Minimum Python

FastMCP 3.4.5 requires **Python >= 3.10** (OBSERVED, PyPI `info.requires_python`). The repo
declares `>=3.12`. No conflict, no change.

### 6.8 Deprecations to avoid adopting

- `FASTMCP_DECORATOR_MODE=object` / `fastmcp.settings.decorator_mode = "object"` — deprecated,
  emits `FastMCPDeprecationWarning`, will be removed. Do not use it.
- `exclude_args` on `@mcp.tool` — the signature's own docstring says "Deprecated: Use `Depends()`
  for dependency injection instead."
- `serializer=` on the tool decorator — deprecated (`"The `serializer` parameter is deprecated."`).
- `transport="sse"` — legacy, "shouldn't be used in new projects."

None are used by this repo.

---

## 7. If you had actually landed on v2

For context on how far v2 is from current, the v2 → v3 breaking changes
([`from-fastmcp-2.mdx`](https://github.com/PrefectHQ/fastmcp/blob/v3.4.5/docs/getting-started/upgrading/from-fastmcp-2.mdx)):

- Transport/server settings removed from the `FastMCP()` constructor → moved to `run()` (§2.2).
- `get_tools()` / `get_resources()` / `get_prompts()` renamed to `list_tools()` / etc., **and they
  now return lists instead of dicts** — code indexing by name breaks.
- Component `.enable()` / `.disable()` moved to the server (`server.disable(names={...})`);
  calling them on a component now raises `NotImplementedError`.
- Prompts use `fastmcp.prompts.Message` instead of `mcp.types.PromptMessage`.
- Default OAuth storage moved `DiskStore` → `FileTreeStore` over a pickle-deserialisation
  vulnerability in diskcache ([CVE-2025-69872](https://github.com/PrefectHQ/fastmcp/issues/3166)).
  Clients re-register on first connect after upgrade.

None of these touch this server's code, which is another way of saying the server uses a narrow,
stable slice of the API. But the CVE alone is reason enough not to target v2.

---

## 8. What could **not** be verified

Stated plainly rather than filled in:

- **FastMCP 3.4.5 was not installed or executed.** The instruction was not to install anything, so
  no `uv add fastmcp` and no live run. All FastMCP behavioural claims are read from source at the
  `v3.4.5` tag and from the docs shipped in that tag. The "before" schemas in §2.5 *were* observed
  live against the repo's installed `mcp` 1.26.0; the "after" schemas are INFERRED from the code
  path plus a direct check of the pydantic `TypeAdapter` primitive FastMCP calls. **The end-to-end
  post-migration schema has not been observed.** Confirm with `fastmcp inspect server.py` after
  installing (§9, step 4).
  **This is the prediction in this document most likely to be wrong, so watch it specifically.**
  §9 step 4 tells you to expect *exactly two* categories of schema diff (`$ref` inlining, `title`
  pruning). If the diff instead shows the `params` nesting changed — arguments flattened to
  top-level rather than wrapped — then §2.5's conclusion is wrong, the tool call envelope is a
  breaking change for existing callers, and steps 7–10 need re-planning before you proceed.
- **The exact inlined shape produced by `DereferenceRefsMiddleware`** (§6.3) was not dumped —
  `fastmcp/server/middleware/dereference.py` was not read. The claim that `$ref`s are inlined rests
  on the constructor wiring plus the docs statement; the precise output was not inspected.
- **gofastmcp.com now serves FastMCP 4 docs, not 3.x.** OBSERVED — `https://gofastmcp.com/llms.txt`
  indexes "Upgrading from FastMCP 3: What changes when you upgrade to FastMCP 4, which builds on the
  MCP Python SDK v2". Because of this, **every FastMCP citation in this document points at the
  `v3.4.5` git tag, not the live site or `main`**, and live-site URLs may describe v4 behaviour that
  does not hold for 3.4.5. Treat any gofastmcp.com page you open as v4 unless you check.
- **Why the docs site is ahead of the stable release** (4.0.0b1 is a beta) was not investigated —
  presumably docs deploy from `main`. Not confirmed.
- **No release-notes/CHANGELOG sweep** of individual 3.4.x patch releases was done; breaking-change
  coverage comes from the upgrade guides, which are organised by major version.
- **`mcp` 1.26.0 → 1.29.0 deltas** were not reviewed. Irrelevant if you migrate off `mcp` as a
  direct dependency, but noted.

---

## 9. Recommended migration sequence for this server

Ordered. **[M]** = mechanical, low risk. **[J]** = needs judgement / review.

| # | Step | Files | Kind |
| --- | --- | --- | --- |
| 1 | **Bound the current dependency before anything else.** Even if the migration stalls, get `mcp[cli]>=1.26.0` changed to `mcp[cli]>=1.26.0,<2` so no lockfile refresh can break the server (§6.2). Commit this on its own. | `pyproject.toml` | **[M]** |
| 2 | **Capture a baseline of the current tool surface.** Dump all five tools' `name`, `description`, `inputSchema`, `outputSchema`, and `annotations` from the running `mcp` 1.26.0 server to a file. This is the artifact you diff against in step 4 — without it, silent schema drift (§6.3, §6.4) is invisible. ⚠️ **Do not `uv sync` between steps 1 and 2** — the baseline must come from the currently installed 1.26.0 (OBSERVED in `.venv`), not from whatever a fresh resolve produces (e.g. 1.29.0). If in doubt, do step 2 first; step 1's edit does not change the installed version. | scratch file | **[M]** |
| 3 | **Swap the dependency and the import.** In `pyproject.toml`, **remove the direct `mcp[cli]` dependency line and add `fastmcp>=3.4.5,<4`** (§3.4). Note: this does *not* remove `mcp` from the environment — `fastmcp` pulls it back in transitively (§6.1); you are dropping it as a *direct* dependency only. Dropping the `cli` extra does remove the `mcp` command, which FastMCP's own CLI replaces (§3.3). Then `server.py` line 15: `from mcp.server.fastmcp import FastMCP` → `from fastmcp import FastMCP`. This is the entire required code change. | `pyproject.toml`, `server.py` | **[M]** |
| 4 | **Verify the surface.** Run `uv run fastmcp inspect server.py` and re-dump the schemas; diff against step 2. **Expect exactly two categories of difference:** `$ref`/`$defs` inlined (§6.3) and `title` keys gone (§6.4). Any *other* difference — especially a change to the `params` nesting — means something is wrong; stop and investigate. | — | **[J]** |
| 5 | **Run the existing tests unchanged.** `uv run pytest`. All four should pass without edits, because decorators return the original function (§2.4). If they fail on the call signature, that assumption broke — re-check before proceeding. Then smoke-test the real server through `mcp.json` against the live portal. | `tests/test_server.py` | **[M]** |
| 6 | **— Migration is complete here. Commit. —** Everything below is improvement, not migration, and each item is independently revertable. | — | — |
| 7 | **Adopt `ToolError`.** Rewrite `_handle_error` to raise instead of return, and make sure the blanket `except Exception` re-raises `ToolError` (§6.6). **Client-visible behaviour change**: failures start arriving as MCP errors instead of successful `"Error: …"` strings. | `server.py` | **[J]** |
| 8 | **Adopt structured output.** Change the five `-> str` returns to `-> dict` (or typed pydantic output models) and drop `json.dumps`. **Client-visible wire-format change** (§5). Decide bare `dict` vs. typed models — typed gives a real output schema and is the better end state. | `server.py` | **[J]** |
| 9 | **Add MCP-layer tests** using `Client(mcp)` alongside the existing `pytest-httpx` tests (§4.2). Lock in tool registration, the `readOnlyHint` annotations, and — after steps 7–8 — the new error and output behaviour. Keep `pytest-httpx`. | `tests/` (new file) | **[J]** |
| 10 | **Optional cleanups.** Decide `main.py`'s fate (§3.2). Consider a lifespan-managed shared `httpx.AsyncClient` to replace the per-call client (§2.8) — note this changes what `pytest-httpx` intercepts, so pair it with step 9. | `main.py`, `mcp.json`, `server.py` | **[J]** |

**The migration proper is steps 1–5, and only step 3 touches `server.py` — a one-line import
change.** `main.py` and `mcp.json` require no changes at all. Steps 7–10 are the reason the
migration is worth doing, but they are separate decisions and should be separate commits.
