# WXT ContextCanon Architecture

English | [简体中文](ARCHITECTURE.zh-CN.md)

Describes what is actually built, not what was planned.

---

## 1. Positioning

WXT ContextCanon is a **new, independent repository** built from a clean initial commit. It is
not a copy of a private repository with names removed, and not a renamed fork. Every file
in it was written for this repository.

The four-noun problem it solves:

```
one personal context  +  one file-state ledger  +  many agents  +  many devices
```

**What that means in 0.1.1, precisely:**

| Claimed by the tagline | Actually shipped in 0.1.1 |
|---|---|
| one personal context | **real** — Profile Core, multi-agent, shared store |
| one file-state ledger | **real** — Registry Core, append-only, rebuildable |
| many agents | **real** — several agents read and write the same profile |
| many devices | **simulated** — a second *logical* device in the same local database. Ledger mechanics are exercised; **no network transport between machines exists yet**. |
| 0.1.1 runtime | **single-machine** — one host, one local SQLite per store |

## 2. Technology choices and why

| Choice | Reason | Cost |
|---|---|---|
| **Python 3.9+, standard library only** | A stranger runs it in ten minutes with no install step. No dependency means no dependency audit, no version conflicts, no supply-chain surface. | Less idiomatic MCP (protocol hand-rolled) |
| **SQLite** | Ships with Python, no server, handles single-machine concurrency. | Multi-writer across machines needs a later transport |
| **MCP over stdio, hand-rolled JSON-RPC** | ~80 lines instead of an SDK dependency. | Must track spec changes manually |
| **JSON config, not YAML** | No parser dependency. | Slightly less friendly to hand-edit |
| **Docker optional** | Storage is a local file; containers add nothing to the core value. | "Production-like" path is less exercised |

**No** vector database, graph database, Redis, PostgreSQL (in 0.1.1), SaaS, cloud, paid
component, dashboard, multi-tenancy, permission backend, mobile app, ingestion
connectors, or LLM calls at runtime.

## 3. Package map

```
packages/
  contextcanon_config/     configuration loader; defaults are all local and synthetic
  profile_core/    model · store · service
  registry_core/   store · service
  mcp_server/      stdio JSON-RPC server, 8 tools
  contextcanon_cli/        context · demo · cli  (the `contextcanon` command)
```

Layering rule: **business rules live only in the service layer.** The store layer executes
SQL and nothing else; MCP and CLI call services and never touch SQL. This is what makes a
future PostgreSQL backend a store swap rather than a rewrite.

## 4. Profile Core

### Model

A fact is a versioned, sourced, time-bounded **claim**, not a string.

```
fact_id · subject · key · value
status        active | superseded | rejected | expired
sensitivity   public | personal | sensitive | restricted
durability    durable | temporary | scheduled
certainty     real
valid_from / valid_until   ISO-8601 UTC, nullable
provenance    { source, ref, method, observed_at, confidence }
revision · supersedes · superseded_by · conflicts_with
created_at / updated_at
```

### Lifecycle

```
  write ──► active ──► superseded      (a newer revision replaced it)
              │
              ├──────► expired        (valid_until passed; swept, never deleted)
              │
              └── (incoming contradiction) ──► rejected  (stored, not merged)
```

### Conflict policies

`on_conflict` on `profile_upsert`: `supersede` (default) · `reject` · `keep`.
Rejection is the load-bearing one — a low-confidence inference must not silently
overwrite a trusted value. It becomes a *record* instead of a *mutation*.

### Temporal reads

`as_of(subject, T)` returns, per key, the highest revision with
`valid_from <= T < valid_until`. It uses validity windows, **not** row creation time, so
back-dated and scheduled facts resolve correctly. This is the single largest capability
gap versus plain text.

### Audit

`fact_events` is append-only: `fact.created`, `fact.reasserted`, `fact.superseded`,
`fact.rejected`, `fact.expired`, `fact.conflict_kept`. Every write records an actor.

## 5. Registry Core

A **file-state ledger** — it stores what each device believes about object keys, never
file contents.

| Table | Role |
|---|---|
| `devices` | identity: `device_id`, `role` |
| `events` | append-only: `seq`, `event_id` (unique), `device_id`, `stream`, `kind`, `ts`, `payload` |
| `outbox` | work queued offline, drained on reconnect |
| `applied` | idempotency ledger |
| `shared_index` | **derived** projection: `object_key`, `device_id`, `state`, `version` |
| `manifests` | what a device holds, with a checksum |
| `checkpoints` | `last_good_rebuild` |

Frozen capabilities consumed, unchanged from the private design: device identity,
manifests, append-only events, local outbox, shared-index rebuild, idempotency,
last-good behaviour, offline recovery.

```
offline:  queue → outbox
online:   drain_outbox()  → append event (idempotent by id) → project → mark applied
          rebuild_shared_index() → snapshot last-good → recompute → restore on failure
```

**Mutation intent** is explicit: `registry begin --task-id --intent --targets` … `registry
end`. An unfinished `begin` is a detectable signal that an agent was interrupted.

## 6. Agent interface

### MCP — 8 tools

`profile_get` · `profile_search` · `profile_upsert` · `profile_as_of` ·
`profile_history` · `profile_audit` · `registry_query` · `registry_event`

Supersede and conflict resolution are **parameters** of `profile_upsert`, not separate
tools. Rationale: an agent should state a fact, not choose an administrative verb; policy
belongs in the service layer where it is tested. Task framing (`begin`/`end`) is CLI-only
because it is a batch concern, not a single call.

### CLI — the complete surface

`config` · `demo` · `profile` · `registry` · `benchmark` · `guard` · `mcp` · `doctor`

### Skill — deliberately thin

`skills/contextcanon/SKILL.md` contains six rules, a when-to-do-what table, and minimal usage.
No governance charter, no schema dump, no deployment rules. Those live in `docs/` and
code. Total: under 120 lines.

## 7. Release Guard

```
config (no host, project, container or path)  +  transport adapter (local-shell | ssh-shell)
```

Steps, in order, fail-closed:

```
project_guard → mutation_intent → lock → integrity → backup_gate
  → migration_test → deploy → post_health → smoke
```

Backup and migration run **before** deploy. A failure at any step aborts, names the step,
and releases the lock. `plan` is always dry-run; `apply` requires `--intent`.

WXT ContextCanon ships a **fake stack**: a 127.0.0.1 HTTP service, a fake backup command and a
fake migration test that can be forced to fail. That is how the gates are exercised in CI
with no Docker and no network.

**Scope statement.** The ten steps above are exactly what `guard.py` implements and what
`tests/test_release_guard.py` asserts. Nothing beyond that is claimed for this public
repository — in particular there is no production canary, no journal mode, no
direct-vs-journal comparison, and no multi-host deployment story here.

Kubernetes, Nomad and Swarm are out of scope.

## 8. Benchmark

**Full suite: 9 deterministic synthetic cases** with a real Markdown baseline (one file,
last write wins). No LLM judge. Result: **WXT ContextCanon 9/9, Markdown 3/9** — Markdown passes
simple recall, write-then-read, and two-agents-agree. The report in `README.md` says so
explicitly.

`contextcanon benchmark smoke` runs a **7-case subset** of those same nine:
**WXT ContextCanon 7/7, Markdown 3/7**. The subset number is not a second opinion; it is the same
suite, fewer cases, run as a fast gate (including in the clean-home acceptance test).

## 9. Configuration abstraction

No private constant survives. Sections:

```yaml
profile:  host · port · database · data_dir
registry: device_id · registry_home · shared_store · device_role
deploy:   project_name · compose_binary · compose_files · services · lock_path
          backup_command · migration_test_command · smoke_command · deploy_command
          health_endpoints · transport · ssh{host_alias,workdir}
server:   name · version
```

Example values are `127.0.0.1`, `localhost`, `./data`, `demo-device`,
`wxt-contextcanon`. No host alias ships, so the ssh transport cannot run by accident.

## 10. What is excluded from 0.1.1, on purpose

Hindsight · Mem0 · Supermemory · Cognee · vector DB · graph DB · Redis · SaaS · cloud
version · commercial tier · complex dashboard · multi-tenancy · permission backend ·
mobile app · automatic chat import · email/calendar/health/finance connectors.

## 11. Extension path

| Next step | What it needs | What it does **not** need |
|---|---|---|
| Real cross-machine transport (0.1.1's biggest gap) | a transport over the existing event log + outbox | schema change |
| PostgreSQL | a new store class behind the service interface | API change |
| HTTP API | a thin wrapper over the service layer | core change |
| Conflict review UI | a consumer of `rejected` facts | model change |

## Operational limits

Temporal reads use effective validity time, not a bitemporal record of what the system
knew at each ingestion timestamp. Highest revision wins per key inside its validity
window. An earlier still-valid value becomes visible again after a temporary override
expires. Rejected claims are excluded unless explicitly requested.

Writers use SQLite transactions; no distributed replication or automatic conflict
consensus is implemented. Labels do not restrict reads. Guard stops subsequent steps
on failure but does not automatically roll back a completed deployment or restore data.
