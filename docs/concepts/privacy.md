# Privacy model

## Where data lives

```
<repo>/data/profile.db           Profile Core
<repo>/data/registry/shared.db   Registry Core
```

These are defaults relative to the working directory; environment/configuration can redirect them. No network calls are made by either core. No telemetry, no
analytics, no account, no hosted component.

## What is stored

- Facts you (or your agents) explicitly write.
- An append-only audit trail of every write, with an actor label.
- File-state events: normally object keys and checksums. Arbitrary caller payloads are stored verbatim.

## What is not stored

- File contents. The registry tracks *state about* files, not the files.
- Credentials should not be stored. The service does not enforce this; the demo models the recommended behaviour: store a pointer to a secret
  manager, never the secret.
- Anything you did not write. There is no background ingestion in 0.1.1.

## Sensitivity

Every fact carries `public | personal | sensitive | restricted`. It is a **label**, not an
enforcement mechanism — nothing in 0.1.1 blocks a caller from reading a `restricted` fact.
Its purpose is to give every downstream consumer (a skill, a summariser, a log) a
machine-readable signal about what is safe to repeat.

## Deletion

Expired, superseded and rejected facts are **retained**. This is deliberate: a profile you
cannot audit is a profile you cannot trust. There is no complete erasure API. Removing just a fact row does not remove old values from
related audit events, rejected revisions, backups, or agent transcripts. Plan an explicit
backup/retention review before handling real personal data; do not treat a sample SQL
DELETE as proof of erasure.

## Multi-device

Events carry a `device_id`. When two devices have different beliefs, both are visible and
the event log decides the order. No device silently wins.

In 0.1.1 both device ids live in the same local database — the second device is a logical
device, not a second machine. No data leaves the host in either case, which is why this
section is short.

## Threat model

Assumed out of scope: an attacker who already has code execution as your user, and an
attacker with physical access to an unencrypted disk. Use full-disk encryption.

See [SECURITY.md](../../SECURITY.md) for the vulnerability reporting process.
