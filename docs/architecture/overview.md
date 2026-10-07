# Architecture overview

## The problem shape

```
one personal context  +  one file-state ledger  +  many agents  +  many devices
```

**0.1.0 reality check.** Multi-agent is real and shared. The "many devices" half is
**simulated**: the second device in `contextcanon registry demo` is a logical device inside the
same local database, which exercises outbox replay, idempotency and rebuild without a
network. **Real cross-machine transport is not shipped**, and the 0.1.0 runtime is
single-machine.

Everything in WXT ContextCanon is in service of those four nouns. If a feature does not serve
one of them, it does not belong in 0.1.0.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ Agents / Skills                                              │
│   skills/contextcanon/SKILL.md  ·  Claude/Codex/etc via MCP          │
└───────────────┬──────────────────────────────┬───────────────┘
                │ 8 tools, stdio JSON-RPC      │ full surface
┌───────────────▼───────────────┐  ┌───────────▼───────────────┐
│ MCP server                    │  │ CLI (`contextcanon`)              │
│ packages/mcp_server           │  │ packages/contextcanon_cli         │
└───────────────┬───────────────┘  └───────────┬───────────────┘
                │                              │
┌───────────────▼──────────────────────────────▼───────────────┐
│ Service layer (business rules live here, nowhere else)       │
│   ProfileService          │        RegistryService           │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
┌───────────────▼───────────────┐  ┌───────────▼───────────────┐
│ ProfileStore (SQLite)         │  │ RegistryStore (SQLite)    │
│ facts · fact_events · sources │  │ events · outbox · applied │
│                               │  │ shared_index · manifests  │
└───────────────────────────────┘  └────────────────────────────┘
```

The service layer never talks SQL to callers, and the store layer never encodes business
rules. That split is what lets a PostgreSQL backend arrive later without touching MCP or
the CLI.

## Why SQLite first

The requirement is "a stranger is running in 30 minutes". SQLite ships with Python, needs
no server, and handles single-machine concurrency fine. PostgreSQL is a configuration
change, not a rewrite — the service layer is the only place that would need a new store
implementation.

## Why the MCP surface is small

Eight tools. Agents get a small, stable vocabulary; everything else lives in the CLI.
Supersede and conflict resolution are *parameters* of `profile_upsert`, not separate
tools, because an agent should not have to reason about which administrative verb to
pick — it states a fact and a policy.

## Why the release guard is configuration plus a transport adapter

Deployment safety rules are universal; the target is not. The guard therefore contains
no host, project, container or path. It reads a deploy config and talks to a transport
(`local-shell` or `ssh-shell`). The same guard runs against a fake stack in CI, which is
how the rules stay honest.

## Data flow: an agent corrects a fact

```
profile_upsert(editor = "zed")
    → find active fact for (subject, key)
    → different value?  yes
        → insert new fact (revision n+1, status active, supersedes = old_id)
        → set old fact status = superseded, superseded_by = new_id
        → append fact.created + fact.superseded events
    → commit
```

Nothing is overwritten. The audit trail can reconstruct every state the profile was ever
in.

## Data flow: a device reconnects

```
[offline]  append to local outbox            (no ledger write yet)
[online]   drain_outbox()
              for each pending item:
                already applied?  → skip           (idempotency)
                else              → append event + project into index + mark applied
           rebuild_shared_index()
              snapshot current index as last-good
              recompute from the full event log
              on failure → restore last-good        (degrade, never destroy)
```

## What is deliberately not here

Vector search, graph storage, an HTTP API, a dashboard, multi-tenancy, hosted service,
paid tiers, ingestion connectors. See `README.md` → Current limitations.

## Further reading

- [data-model.md](data-model.md) — tables and fields
- [../concepts/profile.md](../concepts/profile.md) — lifecycle semantics
- [../concepts/registry.md](../concepts/registry.md) — ledger semantics
- [../concepts/release-guard.md](../concepts/release-guard.md) — deployment gates
