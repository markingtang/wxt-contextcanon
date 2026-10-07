# MCP tools

**8 tools.** The surface is deliberately small: agents get a stable vocabulary, and
everything else lives in the CLI.

| Tool | Purpose |
|---|---|
| `profile_get` | Read one active fact |
| `profile_search` | Substring search over active keys and values |
| `profile_upsert` | Create or replace a fact (also handles supersede and conflict) |
| `profile_as_of` | What did we believe at time T? |
| `profile_history` | All revisions of one key |
| `profile_audit` | Append-only audit trail for a subject |
| `registry_query` | Read the shared file-state index |
| `registry_event` | Append a file-state event and project it |

## Why supersede and conflict are parameters, not tools

An agent should state a fact, not choose an administrative verb. `profile_upsert` takes
`on_conflict`:

- `supersede` (default) — the previous value becomes a superseded revision.
- `reject` — the incoming claim is stored as `rejected`; the trusted value is untouched.
- `keep` — the existing value wins, nothing is written.

Adding `profile_supersede` and `profile_reject` as separate tools would push policy
decisions into the agent's prompt. Keeping them as parameters keeps the policy in the
service layer where it can be reasoned about and tested.

Task framing (`begin` / `end`) is CLI-only for the same reason: it is a batch-level
concern, not a single-call one. An agent that needs it should shell out to
`contextcanon registry begin`.

## Protocol

Standard MCP over stdio: newline-delimited JSON-RPC 2.0.

- `initialize` → returns `protocolVersion`, `capabilities.tools`, `serverInfo`
- `notifications/initialized` → no response
- `tools/list` → the eight tool specs with JSON schemas
- `tools/call` → `{ content: [{ type: "text", text: "<json>" }], isError: bool }`
- `ping` → `{}`

Errors are returned as a normal result with `isError: true`. The server never crashes the
agent's session on a bad call.

## Schemas

### `profile_get`

```json
{ "subject": "demo:alex-chen", "key": "timezone", "include_inactive": false }
```

### `profile_search`

```json
{ "subject": "demo:alex-chen", "query": "editor", "limit": 20 }
```

### `profile_upsert`

```json
{
  "subject": "demo:alex-chen",
  "key": "tooling.editor",
  "value": "zed",
  "sensitivity": "personal",
  "durability": "durable",
  "valid_from": "2026-09-12T00:00:00Z",
  "valid_until": null,
  "source": "user-stated",
  "confidence": 1.0,
  "on_conflict": "supersede"
}
```

Response: `{ action, fact, supersedes, conflicts_with }` where `action` is one of
`created | superseded | rejected | kept | unchanged`.

### `profile_as_of`

```json
{ "subject": "demo:alex-chen", "timestamp": "2026-01-01T00:00:00Z", "include_rejected": false }
```

### `profile_history`

```json
{ "subject": "demo:alex-chen", "key": "tooling.editor" }
```

### `profile_audit`

```json
{ "subject": "demo:alex-chen", "limit": 50 }
```

### `registry_query`

```json
{ "object_key": "notes/a.md", "device_id": "demo-device" }
```

### `registry_event`

```json
{ "kind": "file.upsert", "payload": { "object_key": "notes/a.md", "checksum": "abc123" } }
```

## Client configuration

```json
{
  "mcpServers": {
    "contextcanon": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "env": { "PYTHONPATH": "/absolute/path/to/wxt-contextcanon/packages" },
      "cwd": "/absolute/path/to/wxt-contextcanon"
    }
  }
}
```

`cwd` matters: relative paths in the default config resolve against it.
