# MCP tools

English | [简体中文](MCP_TOOLS.zh-CN.md)

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
- `keep` — the existing value wins; a conflict-kept audit event is recorded.

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

Tool validation/execution failures return `isError: true`. Invalid JSON-RPC envelopes,
unknown methods, and unknown tool names use top-level JSON-RPC errors. Notifications
receive no reply and cannot invoke tools. Bad calls do not terminate the stdio session.

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
{ "subject": "demo:alex-chen", "timestamp": "<UTC timestamp from 30 days before demo seed>", "include_rejected": false }
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

## Protocol compatibility

The server advertises **2024-11-05** and retains its initialization handshake.
It does not advertise 2026-07-28. The
[official versioning rules](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)
distinguish handshake clients from modern per-request metadata clients. A dual-era stdio
client probes `server/discover`; our -32601 response triggers its legacy fallback.
Simply returning a new version string would not implement discovery or per-request metadata.

Verified with official Inspector **2.9.0** in auto mode and official TypeScript client
**2.3.1** in both legacy and auto modes: connection, all 8 tools, synthetic reads and JSON
writes, revision history, temporal reads, and continued operation after an invalid call.
A modern-only client pinned to 2026-07-28 is unsupported. Claude Desktop, Codex and other
AI host GUIs have not been individually tested; this is not an all-clients claim.

## Client configuration

Use a trusted stdio host that supports the legacy protocol or automatic fallback.
Do not rely on a client supporting `cwd`. Supply absolute interpreter, package and database
paths. Replace every example path with your own; on Windows JSON use forward slashes
(with your own drive letter) or escaped backslashes.

```json
{
  "mcpServers": {
    "wxt-contextcanon": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "mcp_server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/wxt-contextcanon/packages",
        "PYTHONIOENCODING": "utf-8",
        "WXT_CONTEXTCANON_PROFILE_DATABASE": "/absolute/path/to/wxt-contextcanon/data/profile.db",
        "WXT_CONTEXTCANON_PROFILE_DATA_DIR": "/absolute/path/to/wxt-contextcanon/data",
        "WXT_CONTEXTCANON_REGISTRY_SHARED_STORE": "/absolute/path/to/wxt-contextcanon/data/registry/shared.db",
        "WXT_CONTEXTCANON_REGISTRY_HOME": "/absolute/path/to/wxt-contextcanon/data/registry"
      }
    }
  }
}
```

Save this as a local `mcp-client.json` outside the public repository. Client configuration
formats vary: the example above is accepted by Inspector, not a promise about every host.
Seed the demo using the Quickstart first, and point the client to that same data directory.

With Node 22.19+ installed, the real Inspector CLI can connect from any shell:

```text
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli --config mcp-client.json --server wxt-contextcanon --protocol-era auto --method tools/list --strict
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli --config mcp-client.json --server wxt-contextcanon --protocol-era auto --method tools/call --tool-name profile_get --tool-arg subject=demo:alex-chen key=tooling.editor
```

Expect 8 tools and editor `zed`. To test writes, call profile_upsert for a **fictional**
subject such as `demo:client`, then profile_get and profile_history for the same key.
Use a generated ISO timestamp (or a demo fact's valid_from) for profile_as_of; do not copy
a fixed calendar date and expect it to stay inside a relative demo window.

For the full reproducible synthetic session used in CI:

```text
npm install --prefix .mcp-test --no-audit --no-fund --ignore-scripts @modelcontextprotocol/inspector@2.9.0 @modelcontextprotocol/client@2.3.1
node tools/check_mcp_client.mjs .mcp-test
```

The check creates isolated temporary data and never uses your real profile. It checks an
invalid call followed by ping and tool discovery on the same SDK connection. A protocol
client test verifies Agent connectivity, not a model's reasoning quality or willingness
to call tools. Sensitivity labels are not permissions; trust every connected Agent.
