# Quickstart — local, no Docker

Target: running in about 10 minutes, understanding it in 10 more. If this page fails on
your machine, that is a bug — please open an issue.

## 0. Requirements

- Python 3.9 or newer (`python --version`)
- SQLite (bundled with Python)
- Git

That is all. No `pip install` is required.

## 1. Get the code

```bash
git clone https://github.com/markingtang/wxt-contextcanon.git wxt-contextcanon
cd wxt-contextcanon
```

## 2. Pick your launcher

| Platform | Command |
|---|---|
| macOS / Linux / Git Bash | `./contextcanon <args>` |
| Windows cmd / PowerShell | `contextcanon.cmd <args>` |
| Anywhere | `PYTHONPATH=packages python -m contextcanon_cli <args>` |

The wrappers only set `PYTHONPATH`. Use the explicit form if a wrapper misbehaves.

## 3. Verify

```bash
contextcanon doctor
```

You should see your Python version, SQLite version, and the paths where state will live
(all inside the repository). If `ok` is `false`, read the `problems` list.

## 4. Load the demo persona

```bash
contextcanon demo seed --reset
```

This creates `demo:alex-chen`, a **fictional** subject with 20+ synthetic facts. It
includes, on purpose:

- durable, temporary and scheduled facts
- one supersede (`tooling.editor`: `vscode` → `zed`)
- one rejected conflict (a low-confidence inference about `timezone`)
- one expired fact (a permit whose window passed)
- provenance and sensitivity on every fact

## 5. Read and write

```bash
contextcanon profile get    --subject demo:alex-chen --key tooling.editor     # zed
contextcanon profile history --subject demo:alex-chen --key tooling.editor    # vscode -> zed
contextcanon profile search --subject demo:alex-chen --query editor
contextcanon profile set    --subject demo:alex-chen --key demo.note --value "\"it works\""
contextcanon profile lifecycle --subject demo:alex-chen
```

## 6. Time travel

```bash
contextcanon profile as-of --subject demo:alex-chen --at 2026-01-01T00:00:00Z
```

Durable facts in the demo are back-dated, so a timestamp in the past returns the
superseded `vscode` rather than today's `zed`. This is the single biggest difference from
a text file.

## 7. Registry demo

```bash
contextcanon registry demo --reset
```

Runs a scripted story: a device registers, declares a task, writes files, a second
**logical** device (same process, same local database — not a second computer) queues
work while "offline", both reconnect, the same work is delivered twice and is skipped the
second time, and the index is rebuilt from the event log.

## 8. Benchmark

```bash
contextcanon benchmark smoke          # 7-case subset of the full 9
contextcanon benchmark run            # all 9 cases, compares against a Markdown baseline
```

Full suite: WXT ContextCanon 9/9, Markdown 3/9. Smoke subset: WXT ContextCanon 7/7, Markdown 3/7. Deterministic
and synthetic. No LLM judge. The Markdown baseline is expected to pass the simple cases.

## 9. MCP

```bash
contextcanon mcp                      # stdio server; Ctrl-C to exit
```

Add it to your MCP client with the snippet in `README.md`.

## 10. Release guard (optional)

```bash
contextcanon guard plan                                   # dry run, always safe
contextcanon guard apply --intent "first fake deployment"  # runs the fake stack locally
```

`plan` never changes anything. `apply` requires an `--intent` string, takes a lock, and
aborts on any failed step.

## Starting over

```bash
rm -rf data
contextcanon demo seed --reset
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: contextcanon_cli` | Use `PYTHONPATH=packages python -m contextcanon_cli ...` |
| `demo persona not found` | Run from the repository root |
| `another deployment holds the lock` | A previous guard run crashed; delete `data/*.lock` |
| Health check fails in `guard apply` | The fake service did not start; check port 8787 is free |
| Permission error creating `./data` | Clone somewhere your user can write |

## Where state lives

```
data/
  profile.db
  registry/shared.db
  *.lock                 (only during a guard run)
```

Nothing outside the repository is read or written.
