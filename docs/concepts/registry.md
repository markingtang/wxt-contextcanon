# Registry Core concepts

The registry is a **file-state ledger**, not a file system. It does not store content; it
stores what each device believes about a set of object keys, and the event log that
justifies that belief.

## Device identity

Every writer has a `device_id` and a `role` (`primary`, `secondary`, …). Events are
attributed to a device, which is what makes "two machines disagree" a representable
state instead of a corruption.

```bash
./contextcanon registry init                      # register this machine
WXT_CONTEXTCANON_REGISTRY_DEVICE_ID=laptop-b ...    # or override per device
```

## Append-only events

```
events: seq · event_id (unique) · device_id · stream · kind · ts · payload
```

No row is ever updated. If a belief changes, a new event is appended. `event_id` is
content-derived, which is what makes replay safe.

## Local outbox

Work produced while offline goes into `outbox` first. It is drained when connectivity
returns:

```
outbox(pending) → append event (idempotent by outbox_id) → project into index → done
```

A failing item stays `pending` and is retried. Nothing is dropped.

## Shared index as a projection

`shared_index(object_key, device_id, state, version)` is *derived*. It can be recomputed
from the event log at any time:

```bash
./contextcanon registry rebuild
```

For `file.upsert` / `file.write` / `file.update`, authoring metadata carried in the event
payload — `version` (the file's own tag, e.g. `"v3"`), `updated_by` and `date` — is
preserved in the projected `state` next to `checksum` and `size`, so a query reflects the
file version the writer recorded. The numeric `version` column remains the ledger's event
counter and is never overwritten by a file version tag. Events without those fields
project exactly as before.

## Idempotency

`applied` records every `event_id` that has been projected. Delivering the same work twice
— a network retry, a double sync — changes nothing. `contextcanon registry demo` demonstrates this
explicitly and asserts it.

## Last-good behaviour

A rebuild snapshots the current index first. If the rebuild raises, the snapshot is
restored and the result reports `last_good_used: true`. Degrade, never destroy.

## Offline recovery

```bash
./contextcanon registry recover
```

= `drain_outbox()` + `rebuild_shared_index()`. This is the only call you need after a
period offline.

## Mutation intent

Before an agent touches files, it declares what it is about to do:

```bash
./contextcanon registry begin --task-id t-42 --intent "reorganise notes" --targets notes/a.md
./contextcanon registry event  --kind file.upsert --object-key notes/a.md --checksum abc123
./contextcanon registry end    --task-id t-42 --result ok --changed notes/a.md
```

`contextcanon registry status` lists open tasks. An unfinished `begin` without an `end` is a
signal that an agent was interrupted mid-way — the intent trail tells you where.

## Manifests

A device publishes what it holds, with a checksum:

```bash
./contextcanon registry manifest --scope default --entries notes/a.md,notes/b.md
```

Manifests let two devices compare holdings without shipping content.

## What 0.1.2 does not do

- No real network transport between machines. The second device in `registry demo` is
  simulated locally, inside one process and one SQLite file, to prove the mechanics. Until
  a transport exists, two `device_id`s do not mean two computers.
- No content sync. Only state.
- No conflict resolution policy beyond "the event log order decides, and you can audit it".

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../quickstart/local.md).
