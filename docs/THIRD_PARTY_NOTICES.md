# Third-party notices and code-provenance audit

Audited for WXT ContextCanon.

## 0. Project licence

The project itself is licensed under **Apache-2.0**. The full, unmodified text is in
[`LICENSE`](../LICENSE) (byte-identical to the official
`apache.org/licenses/LICENSE-2.0.txt`), and attribution is in [`NOTICE`](../NOTICE).

Apache-2.0 is a permissive licence with an express patent grant and a
no-trademark-conditions clause. The naming and attribution position — who may call
themselves the official project — is stated separately in
[`TRADEMARKS.md`](../TRADEMARKS.md), because a code licence cannot answer it.

Maintainer: **Xiaotang (王小堂)**. See `pyproject.toml` for machine-readable metadata.

Because the runtime dependency list is empty (section 1) and no third-party source is
vendored (section 4), there is **no third-party attribution to carry in `NOTICE`**. The
`NOTICE` file therefore contains only this project's own copyright line, which is exactly
what Apache-2.0 §4(d) expects in that situation.

## 1. Runtime dependencies

**None.**

```
[project] dependencies = []         # pyproject.toml
requires-python = ">=3.9"
```

Runtime requirements: the Python standard library and SQLite (bundled with CPython). No
`pip install` is needed to run, seed, query, benchmark or serve MCP.

Consequence: there is no dependency license to honour, no transitive tree, and nothing to
redistribute.

## 2. Test / tooling dependencies

**None.** `tests/run_all.py` uses `unittest`; the scanner, the isolation proof and the
acceptance runner use the standard library.

## 3. Optional build/runtime environment

| Component | Version | License | Redistribution status |
|---|---|---|---|
| Python | 3.9+ (developed on 3.13) | PSF License | Not redistributed; user-provided runtime |
| SQLite | bundled with CPython | Public domain | Not redistributed; user-provided |
| Docker (optional) | any recent | Apache-2.0 | Not redistributed; optional host tool |
| `python:3.11-slim` base image | 3.11 | PSF / Debian licenses | Referenced by name only in `deploy/docker/Dockerfile`; not vendored |

No Docker image is published by this project.

## 4. Vendored or copied code

**None.**

Every file under `packages/`, `tools/`, `benchmark/`, `deploy/` and `tests/` was written
for this repository. There is no `vendor/` directory, no bundled third-party source, and
no copied snippet.

## 5. Design references — IDEA_REFERENCE_ONLY

The following projects were **studied for concepts**. Their design influenced the shape of
this project. **No source code was copied, imported, adapted or derived from any of
them.**

| Project | What was referenced | CODE_COPIED |
|---|---|---|
| Mem0 | the idea of a durable, structured memory layer for assistants | **NO** |
| Hindsight | temporal reasoning and "what did we know then" framing | **NO** |
| Cognee | knowledge-graph-adjacent organisation ideas | **NO** |
| Supermemory | personal-context-store product framing | **NO** |
| Honcho | per-user agent context separation | **NO** |
| Istota | minimal personal-context modelling | **NO** |
| second-brain | markdown-first personal knowledge conventions | **NO** |

Classification for all of the above: **IDEA_REFERENCE_ONLY**.

Reasoning: reading about a design is not a code dependency. Writing `CODE_COPIED=YES`
here would be inaccurate and would impose obligations that do not apply. If any code from
these projects is ever incorporated, this file must be updated *before* the commit, with
the file path, the upstream license and the redistribution terms.

## 6. Protocol references

| Protocol | Reference | Status |
|---|---|---|
| Model Context Protocol | public specification, `protocolVersion 2024-11-05` | Implemented from the specification over stdio; no SDK used |

No MCP SDK is a dependency — the JSON-RPC framing is implemented directly in
`packages/mcp_server/server.py` (~80 lines), which is why the runtime dependency list is
empty.

## 7. Data and fixtures

| Asset | Origin | Status |
|---|---|---|
| `examples/demo-persona/alex-chen.facts.json` | written for this repository; fictional | Safe to publish, marked `DEMO / SYNTHETIC` |
| `benchmark/fixtures/synthetic-persona.json` | written for this repository; fictional | Safe to publish |
| `benchmark/cases/cases.json` | written for this repository | Safe to publish |

No data was imported from any private profile, database, registry, deployment or
benchmark run.

## 8. Fonts, images, media

None. The repository contains no binary assets.

## 9. Before publishing

Re-run this audit if any of these change: `pyproject.toml` gains a dependency; a file is
copied from another project; a Docker image is published; a data fixture is imported.
