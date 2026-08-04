# discover-research-mcp

An MCP server over the [University of Toronto Discover Research portal](https://discover.research.utoronto.ca).

It gives an AI assistant five read-only tools for finding U of T scholars and
pulling their profiles, publications and research grants — useful for
collaborator search, faculty recruitment shortlists, and expertise lookups.

The portal exposes a public JSON API. This server wraps it, flattens the
responses into stable shapes, and publishes a schema for each so a model can
read fields directly instead of parsing prose.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Connecting a client

Copy the entry from [`mcp.json`](mcp.json) into your MCP client's
configuration. No clone and no absolute path — uvx fetches, builds and runs it:

```json
{
  "mcpServers": {
    "discover-research-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/UofT-Carte/discover-research-mcp",
        "discover-research-mcp"
      ]
    }
  }
}
```

This repository is private, so git needs credentials with access to the
`UofT-Carte` organisation — the same auth you would use to clone it.

### Running from a local clone

For development, or to run a version you are editing:

```bash
git clone https://github.com/UofT-Carte/discover-research-mcp
cd discover-research-mcp
uv sync
```

Then point the client at your clone instead. The path must be absolute, because
an MCP client starts the server from its own working directory:

```json
{
  "mcpServers": {
    "discover-research-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/discover-research-mcp",
        "discover-research-mcp"
      ]
    }
  }
}
```

## Tools

All five are read-only, annotated as such, and take flat named arguments.
Scholar tools accept either the numeric ID (`"17964"`) or the URL-style ID
(`"17964-michael-guerzhoy"`); both work everywhere.

### `discover_search_scholars`

Search by name, subject, discipline, or topic.

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | string | *required* | Name, topic, or keyword |
| `search_by` | string | `"text"` | `"text"` for keywords, `"name"` for names |
| `department_filter` | string | – | Exact value from `discover_get_filter_options` |
| `tag_filter` | string | – | Exact value from `discover_get_filter_options` |
| `availability_filter` | string | – | Exact value from `discover_get_filter_options` |
| `page` | integer | `1` | 1-indexed |
| `per_page` | integer | `20` | 1–100 |

Returns `total`, `page`, `per_page`, `has_more`, and `scholars` — each with
`id`, `url_id`, `name`, `positions`, `tags`, `bio_excerpt`, `availability`,
and `profile_url`.

The filters match on exact strings, so guessed values return nothing. Call
`discover_get_filter_options` first.

### `discover_get_scholar`

Full profile for one scholar.

| Argument | Type | Default |
| --- | --- | --- |
| `scholar_id` | string | *required* |

Returns bio, contact details, `orcid`, positions, academic appointments,
degrees, research topics, availability, personal websites, and counts of
linked publications, grants and professional activities.

### `discover_get_scholar_publications`

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `scholar_id` | string | *required* | |
| `page` | integer | `1` | 1-indexed |
| `per_page` | integer | `25` | 1–100 |
| `sort` | string | `"dateDesc"` | `"dateDesc"` or `"dateAsc"` |

Returns `total`, `has_more`, and `publications` — each with `title`, `type`,
`year`, `authors`, `journal`, `abstract`, `doi`, and `url`.

### `discover_get_scholar_grants`

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `scholar_id` | string | *required* | |
| `page` | integer | `1` | 1-indexed |
| `per_page` | integer | `25` | 1–100 |

Returns `total`, `has_more`, and `grants` — each with `title`, `type`,
`funder`, `start_year`, `end_year`, and `amount`.

### `discover_get_filter_options`

Discover the exact values the search filters accept.

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | string | `""` | Scope options to a search; empty for all |
| `filter_type` | string | `"tags"` | `tags`, `department`, or `customFilterThree` |

`tags` are research topics, `department` covers faculties and units, and
`customFilterThree` is availability (for example "Media enquiries"). Returns
`options`, each with the exact `value` to pass as a filter and a `count` of
matching scholars.

## Behaviour worth knowing

**Failures are failures.** A portal outage, a 404, a rate limit or a timeout
comes back as a failed tool call, not as a successful result containing an
error message. A caller can tell "the portal is down" from "no matches".

**Successful results are cached for 15 minutes**, keyed on the tool and its
arguments. Failures are never cached, so a transient blip is not replayed.

**Connection faults are retried** twice with backoff. Slow responses are not:
if the portal accepts a request and then stalls, retrying would only re-pay the
wait. Definitive answers like 404 are never retried.

**Requests are bounded** — 5s to connect, 30s to read, and a 35s ceiling on
anything a tool does. Worst case for an unreachable host is roughly 15s.

## Development

```bash
uv run pytest          # 48 tests
uvx ruff check .       # lint
uvx ruff format .      # format
```

Tests drive the tools through FastMCP's in-memory client — the same path a real
client takes — and mock the portal at the HTTP boundary with `pytest-httpx`.
Nothing in the suite touches the live portal.

### Layout

| File | Contents |
| --- | --- |
| `src/discover_research_mcp/server.py` | Server construction, middleware, the five tool definitions, and the `main()` entry point |
| `src/discover_research_mcp/portal.py` | Portal addresses, the shared HTTP client and its lifetime, retry policy, payload and error translation |
| `src/discover_research_mcp/models.py` | Output models that drive the published schemas, and shared parameter types |

`server.py` imports the other two; neither imports back.

The console script `discover-research-mcp` is declared in `pyproject.toml` and
resolves to `main()`, which serves over stdio.

Background on the FastMCP migration and the design choices behind it is in
[`docs/research/`](docs/research/).

## Data

All data comes from the University of Toronto Discover Research portal and
belongs to the University. This server only reads it.
