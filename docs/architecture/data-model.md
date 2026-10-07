# Data model

Two SQLite databases, both created on first use inside `./data`.

## Profile Core — `data/profile.db`

### `facts`

| Column | Type | Notes |
|---|---|---|
| `fact_id` | TEXT PK | `f_<sha1-16>`, deterministic when a nonce is supplied |
| `subject` | TEXT | e.g. `demo:alex-chen` |
| `key` | TEXT | dotted namespace, e.g. `tooling.editor` |
| `value` | TEXT | JSON-encoded, so any JSON value works |
| `status` | TEXT | `active` · `superseded` · `rejected` · `expired` |
| `sensitivity` | TEXT | `public` · `personal` · `sensitive` · `restricted` |
| `durability` | TEXT | `durable` · `temporary` · `scheduled` |
| `certainty` | REAL | 0.0–1.0 |
| `valid_from` / `valid_until` | TEXT | ISO-8601 UTC, nullable |
| `provenance` | TEXT | JSON: `source`, `ref`, `method`, `observed_at`, `confidence` |
| `revision` | INTEGER | 1-based per `(subject, key)` |
| `supersedes` / `superseded_by` | TEXT | revision chain |
| `conflicts_with` | TEXT | set when a claim was rejected |
| `created_at` / `updated_at` | TEXT | ISO-8601 UTC |

Indexes: `(subject, key)`, `(subject, status)`, `(valid_from, valid_until)`.

### `fact_events`

Append-only audit trail: `event_id`, `fact_id`, `subject`, `event_type`, `actor`, `at`,
`payload`. Event types: `fact.created`, `fact.reasserted`, `fact.superseded`,
`fact.rejected`, `fact.expired`, `fact.conflict_kept`.

### `sources`

`source_id`, `kind`, `trust`, `note`. Maintained as facts are written, so you can ask
"which facts came from a low-trust source?".

## Registry Core — `data/registry/shared.db`

| Table | Purpose |
|---|---|
| `devices` | device identity: `device_id`, `role`, `label` |
| `events` | append-only ledger: `seq`, `event_id` (unique), `device_id`, `stream`, `kind`, `ts`, `payload` |
| `outbox` | local work queued while offline: `outbox_id`, `device_id`, `kind`, `payload`, `status`, `attempts` |
| `applied` | idempotency ledger: which `event_id` has already been projected |
| `shared_index` | the projection: `object_key`, `device_id`, `state`, `version` |
| `manifests` | what a device says it holds, with a checksum |
| `checkpoints` | `last_good_rebuild` timestamp |

### Event kinds

`task.begin`, `task.end`, `file.upsert`, `file.write`, `file.update`, `file.delete`,
`file.remove`, `file.move`, `manifest.published`.

Projection rules: `file.upsert|write|update` → `status: present`; `file.delete|remove` →
`status: deleted`; `file.move` → `status: moved`; anything else uses `payload.state`.
Events without an `object_key` are recorded but do not affect the index.

## Invariants

1. At most one `active` fact per `(subject, key)`.
2. Every non-active fact is reachable from an active or later fact via `supersedes` /
   `superseded_by`, or via `conflicts_with` if rejected, or by `valid_until` if expired.
3. `events` is append-only: no `UPDATE`, no `DELETE` outside a demo reset.
4. `shared_index` is derived: deleting it entirely and rebuilding must be lossless.
5. Applying an event twice is a no-op.
