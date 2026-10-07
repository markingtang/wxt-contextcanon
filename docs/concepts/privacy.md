# Privacy model

## Where data lives

```
<repo>/data/profile.db           Profile Core
<repo>/data/registry/shared.db   Registry Core
```

That is the whole footprint. No network calls are made by either core. No telemetry, no
analytics, no account, no hosted component.

## What is stored

- Facts you (or your agents) explicitly write.
- An append-only audit trail of every write, with an actor label.
- File-state events: object keys and checksums — **never file contents**.

## What is not stored

- File contents. The registry tracks *state about* files, not the files.
- Credentials. The demo persona models the right behaviour: store a pointer to a secret
  manager, never the secret.
- Anything you did not write. There is no background ingestion in 0.1.0.

## Sensitivity

Every fact carries `public | personal | sensitive | restricted`. It is a **label**, not an
enforcement mechanism — nothing in 0.1.0 blocks a caller from reading a `restricted` fact.
Its purpose is to give every downstream consumer (a skill, a summariser, a log) a
machine-readable signal about what is safe to repeat.

## Deletion

Expired, superseded and rejected facts are **retained**. This is deliberate: a profile you
cannot audit is a profile you cannot trust. If you need a fact truly gone, delete the rows
directly:

```sql
DELETE FROM facts        WHERE fact_id = '...';
DELETE FROM fact_events  WHERE fact_id = '...';
```

The same applies to the registry event log — it is append-only by design, so removing
history is an explicit, conscious operation.

## Multi-device

Events carry a `device_id`. When two devices have different beliefs, both are visible and
the event log decides the order. No device silently wins.

In 0.1.0 both device ids live in the same local database — the second device is a logical
device, not a second machine. No data leaves the host in either case, which is why this
section is short.

## Threat model

Assumed out of scope: an attacker who already has code execution as your user, and an
attacker with physical access to an unencrypted disk. Use full-disk encryption.

See [SECURITY.md](../SECURITY.md) for the vulnerability reporting process.
