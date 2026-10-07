# WXT ContextCanon

English | [简体中文](README.zh-CN.md)

> Canonical context and state for AI agents.

**WXT ContextCanon 0.1.1 — Public release.** Repository:
https://github.com/markingtang/wxt-contextcanon

You run several AI agents. Each one starts fresh, re-learns the same things about you, and
quietly disagrees with the others. WXT ContextCanon gives them **one shared, structured,
time-aware personal context** and **one append-only file-state ledger** — so accepted claims have explicit revisions and validity windows.
It records claims; it does not verify that they are true.

| | |
|---|---|
| Multi-agent — many agents, one machine | **shipped** |
| Shared personal context | **shipped** |
| Temporal facts, provenance, revisions, conflict handling | **shipped** |
| Registry ledger, offline outbox, rebuildable shared index | **shipped** |
| Runtime | **single machine**, SQLite, local-first |
| Runtime dependencies | **zero** — Python standard library only |
| Real cross-machine transport | **not shipped** |

**Real cross-machine transport is not shipped.** A second device is *simulated* in the same
local store to prove the ledger mechanics; nothing here talks over a network. Today's
runtime is single-machine. See [Current limitations](#current-limitations).

It is **not** an agent framework — it does not create, orchestrate or run agents. It is the
substrate your agents read from and write to.

---

## 30 seconds

You have several AI agents. They run in different tools, on different projects, maybe in
a container. Each one starts fresh every time and re-learns the same things about you —
your preferences, your constraints, what you already decided last week. Worse, they
disagree with each other, and when two of them touch the same files, nobody knows what
the current state actually is.

WXT ContextCanon is the missing shared layer:

- **Profile Core** — one structured, sourced, time-aware personal context. Facts have
  provenance, sensitivity, revisions, and validity windows. A correction supersedes; a
  contradiction is rejected; an expired fact stays auditable instead of vanishing.
- **Registry Core** — a file-state ledger. Append-only events per device, a local outbox
  so work continues offline, and a shared index that is a pure projection you can
  rebuild at any time.

Today all of this runs on **one machine** against SQLite. Multiple agents on that machine
is the solved case; a second physical machine is simulated locally, not connected over a
network. No cloud, no NAS, no paid service, no vector database, no LLM required.

---

## Why it exists

Plain text memory works — until it doesn't. The failure mode is never "I forgot a fact".
It is:

- two agents holding **different** versions of the same fact, both confident
- no record of **where** a fact came from or **when** it stopped being true
- a stretch of offline work elsewhere that silently clobbers what you had locally
- no way to answer "what did we believe *before* the correction?"
- file changes made by an agent with no declared intent and no trail

WXT ContextCanon targets exactly those. It does not try to be a smarter chatbot memory; it tries to
be the boring, correct substrate underneath.

---

## Who it is for

- People running **more than one** AI agent today, and who want those agents to agree.
- Developers designing toward multi-device workflows, who want the ledger semantics
  settled before the transport exists.
- Anyone who has outgrown a `MEMORY.md` file but does not want a hosted SaaS memory product.

Not for you if: you use a single assistant and a text file is fine.
That is a genuinely good setup, and this project says so in its own benchmark.

Not for you yet if: you need two real machines to synchronise today. That works in the
design, not in the shipped code.

---

## Architecture

```mermaid
flowchart LR
    subgraph Agents["Agents / Skills"]
        A1["Agent A"]
        A2["Agent B"]
        A3["CLI"]
    end

    subgraph Interface["Agent Interface"]
        MCP["MCP server (8 tools, stdio)"]
        CLI["contextcanon CLI"]
    end

    subgraph Core["WXT ContextCanon"]
        P[("Profile Core<br/>facts · provenance<br/>revisions · lifecycle")]
        R[("Registry Core<br/>events · outbox<br/>shared index")]
    end

    subgraph Devices["Devices (0.1.1: both logical, one local store)"]
        D1["device-a<br/>local SQLite"]
        D2["device-b<br/>logical, same store"]
    end

    A1 --> MCP
    A2 --> MCP
    A3 --> CLI
    MCP --> P
    MCP --> R
    CLI --> P
    CLI --> R
    P --- D1
    R --- D1
    R -. "outbox replay / rebuild" .-> D2

    G["Release Guard<br/>config + transport adapter"] --> CLI
```

Design rules that make this work across devices — **these rules are implemented and tested
in the local runtime; cross-machine synchronization requires further design and testing**:

| Rule | What it buys you |
|---|---|
| Events are append-only | Nothing is silently rewritten |
| The shared index is a projection | Corrupt it, rebuild it |
| Every event has an id | Replay is idempotent |
| Work queues locally first | Offline is normal, not an error |
| A failed rebuild restores last-good | Degrade, never destroy |
| Mutation intent before writes | You know what an agent meant to touch |

---

## Three real scenarios

**1. Two agents, one truth.**
Agent A learns your editor changed to `zed`. Agent B still believes `vscode`. In WXT ContextCanon the
new value supersedes the old one; the old one stays as a revision with its provenance.
Both agents reading the profile get the same answer, and `profile_history` shows what
changed and when.

**2. Two devices, one of them offline.**
A second logical device queues file-state changes into a local outbox while it is
"offline". When it reconnects, the events replay into the ledger, duplicate deliveries are
skipped by event id, and a rebuild reconciles the shared index. Duplicate IDs with different content are rejected. *This is the mechanism you want for a real second machine — 0.1.1 runs the second
device inside one process, so the transport is still to be built.*

**3. "What did we believe in March?"**
Facts carry `valid_from` / `valid_until`. `profile_as_of` answers for any timestamp,
including inside a temporary or scheduled window. The shipped last-write-wins Markdown
baseline does not model validity windows at all.

---

## Quickstart (5 minutes, no Docker)

Requires Git and Python 3.9+ with SQLite. No runtime dependencies or installation needed.

```text
git clone https://github.com/markingtang/wxt-contextcanon.git
cd wxt-contextcanon
```

PowerShell:
```powershell
.\contextcanon.cmd demo seed --reset
.\contextcanon.cmd profile get --key tooling.editor
.\contextcanon.cmd profile as-of --days-ago 30
```

CMD uses `contextcanon.cmd`; Linux/macOS/Git Bash use `./contextcanon`.
See the [complete copy-and-run tutorial](docs/quickstart/local.md) for all four shells,
expected output, installation, and recovery instructions.

Default state is under the current directory's `data/`; configuration and environment
variables can redirect it. Use a fresh clone and synthetic data first. Demo resets are
not intended for a database holding real work.

For a real client, follow [MCP setup and verification](docs/MCP_TOOLS.md#client-configuration).
The server supports the legacy initialization protocol. Inspector 2.9.0 and the official
SDK 2.3.1 are tested; clients requiring modern-only MCP are not supported.

Optional Docker is a one-shot CLI environment, not a running API:
`docker compose -f deploy/docker/docker-compose.yml run --rm contextcanon-api`.
Docker execution is not part of the validated Quickstart.

---

## MCP example

```jsonc
// read
{ "method": "tools/call", "params": { "name": "profile_get",
  "arguments": { "subject": "demo:alex-chen", "key": "timezone" } } }

// write (the previous value becomes a superseded revision)
{ "method": "tools/call", "params": { "name": "profile_upsert",
  "arguments": { "subject": "demo:alex-chen", "key": "tooling.editor",
                 "value": "zed", "source": "user-stated", "durability": "durable" } } }

// reject a contradiction instead of overwriting
{ "method": "tools/call", "params": { "name": "profile_upsert",
  "arguments": { "subject": "demo:alex-chen", "key": "timezone",
                 "value": "America/New_York", "on_conflict": "reject",
                 "source": "inferred", "confidence": 0.25 } } }

// what was true at time T
{ "method": "tools/call", "params": { "name": "profile_as_of",
  "arguments": { "subject": "demo:alex-chen", "timestamp": "<ISO timestamp of interest>" } } }
```

Eight tools: `profile_get`, `profile_search`, `profile_upsert`, `profile_as_of`,
`profile_history`, `profile_audit`, `registry_query`, `registry_event`.
Supersede and conflict handling are parameters of `profile_upsert`, not separate tools —
see [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md).

---

## Registry example

```bash
# declare what you are about to touch, before touching it
./contextcanon registry begin --task-id t-42 --intent "reorganise notes" --targets notes/a.md
./contextcanon registry event  --kind file.upsert --object-key notes/a.md --checksum abc123
./contextcanon registry end    --task-id t-42 --result ok --changed notes/a.md

./contextcanon registry query  --object-key notes/a.md
# [{ "object_key": "notes/a.md", "device_id": "demo-device",
#    "state": { "status": "present", "checksum": "abc123" }, "version": 1 }]

# finished the work queued while offline
./contextcanon registry recover      # drain outbox -> rebuild index -> converged
```

The shared index is derived state. `contextcanon registry rebuild` recomputes it from the event
log at any time, and if the rebuild fails it restores the last known-good index.

In 0.1.1 every device id lives in the same local database. The mechanics are real; the
network between machines is not.

---

## Privacy model

- **Local first.** Default storage is a SQLite file inside the repository. No network
  calls are made by Profile Core or Registry Core.
- **No telemetry, no phone-home, no account.**
- **Sensitivity is a label, not access control.** Every fact carries one of
  `public | personal | sensitive | restricted`. Use it to decide what may be summarised
  or logged. All connected agents can read every sensitivity level.
- **Deletion is not the default.** Expired, superseded and rejected facts are retained so
  history is auditable. There is no complete erasure API; audit records and backups
  may contain prior values.
- **The shipped demo persona is fictional.** `demo:alex-chen` is synthetic data marked
  `DEMO / SYNTHETIC`. No real person, device, host, project or identifier appears anywhere
  in this repository.
- See [SECURITY.md](SECURITY.md) and [docs/concepts/privacy.md](docs/concepts/privacy.md).

---

## Why not just Markdown?

Because on the easy part, Markdown wins, and we are not going to pretend otherwise. Our
own benchmark ships with a Markdown baseline, and here is the honest scoreboard on 9
deterministic synthetic cases:

| | WXT ContextCanon | Markdown baseline |
|---|---|---|
| Simple recall | PASS | **PASS** |
| Write then read back | PASS | **PASS** |
| Two agents read one shared store | PASS | **PASS** |
| What was true at time T | PASS | FAIL |
| Revision chain of a fact | PASS | FAIL |
| Contradiction is rejected, truth kept | PASS | FAIL |
| Which facts came from an inference? | PASS | FAIL |
| Expired fact still auditable | PASS | FAIL |
| Offline work converges after rebuild | PASS | FAIL |

The shipped last-write-wins Markdown baseline has no model of time, conflict, provenance,
or two writers. That is the gap WXT ContextCanon fills. If your problem is "remember my favourite
editor", a text file is fine.

Run it yourself: `contextcanon benchmark run` (no LLM judge, deterministic, synthetic fixtures).
The table above is the **full suite, 9 cases: WXT ContextCanon 9/9, Markdown 3/9**.
`contextcanon benchmark smoke` runs a **7-case subset** of those same cases — WXT ContextCanon 7/7,
Markdown 3/7 — so the two numbers are not in conflict; the smoke run is a subset, not a
second opinion.

---

## Current limitations

Be aware of these before you build on it:

- **0.1.1 is single-machine at runtime.** Multi-agent is real. The second device in
  `contextcanon registry demo` is a logical device inside the same local database, used to prove
  the ledger mechanics. **Real cross-machine transport is not shipped.**
- **SQLite only.** Transactions and SQL currently depend on SQLite; PostgreSQL requires a new implementation.
- **No server process.** There is no HTTP API in 0.1.1; MCP is stdio and everything else is
  the CLI. Docker is an optional one-shot CLI container with no health endpoint.
- **No ingestion.** No email, calendar, health or finance connectors. No automatic chat
  import. Facts enter through the CLI or MCP.
- **No UI.** No dashboard, no web app, no mobile app.
- **No retrieval magic.** No vector search, no graph, no embeddings, no LLM. Facts are
  structured and indexed; search is substring-based.
- **Single user.** No multi-tenancy, no permission backend, no hosted version.
- **Benchmark is small.** 9 cases in the full suite, 7 in the `smoke` subset. It
  demonstrates the shape of the argument, not a research-grade evaluation.

---

## Roadmap (indicative, not committed)

1. Multi-device transport over the existing event log and outbox.
2. PostgreSQL backend behind the same service interface.
3. Conflict review workflow (a human resolves `rejected` candidates).
4. A read-only inspection UI over the audit trail.
5. Selective export / import of a subject, with sensitivity filtering.
6. Larger benchmark with community-contributed cases.

---

## Repository layout

```
packages/
  profile_core/         structured facts, provenance, revisions, lifecycle
  registry_core/        device identity, events, outbox, shared index
  mcp_server/           stdio MCP server, 8 tools, standard library only
  contextcanon_cli/     the `contextcanon` command line interface
  contextcanon_config/  configuration loader (defaults are all local)
deploy/
  docker/               optional container path
  local/                no-Docker instructions
  release-guard/        deployment guard + fake stack
benchmark/              synthetic cases, fixtures, runner, Markdown baseline
skills/contextcanon/    thin agent skill (when to recall / update / declare intent)
examples/               demo persona and example configs
docs/                   architecture, quickstart, concepts, audits
tools/                  secret scanner, isolation proof, clean-home acceptance
tests/                  the gates, including the brand consistency check
LICENSE  NOTICE  TRADEMARKS.md
```

---

## License

**Apache-2.0.** See [LICENSE](LICENSE) for the full text and [NOTICE](NOTICE) for
attribution. The repository has no third-party runtime dependencies (Python standard
library + SQLite only) and contains no vendored third-party source — see
[docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) for the full audit.

Apache-2.0 covers the code only. It does not grant trademark rights and does not let anyone
present a fork as the official project. **WXT ContextCanon is maintained by Xiaotang
(王小堂)** — see [TRADEMARKS.md](TRADEMARKS.md) for the naming and attribution position.

---

## Development

```bash
python tests/run_all.py                       # the full test suite
python tools/scan_secrets.py                  # secret / private-identifier gate (working tree)
python tools/scan_secrets.py --history        # same gate, every git object on every ref
python tools/prove_isolation.py               # static host/config check, not a sandbox
python tools/accept_clean_home.py --watch synthetic-watch  # create this synthetic directory first
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](docs/quickstart/local.md).
