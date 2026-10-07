# Benchmark

## What this is

A small, deterministic, synthetic benchmark with a Markdown baseline. It exists to make
one argument honestly:

> On simple recall, a Markdown file is as good as WXT ContextCanon. WXT ContextCanon only adds value where the
> shipped last-write-wins Markdown baseline has nothing to say.

## Running

```bash
contextcanon benchmark smoke     # 7-case SUBSET of the full 9
contextcanon benchmark run       # all 9 cases
contextcanon benchmark list      # list cases without running them
contextcanon benchmark run --out report.md
```

Two scopes, one suite — the numbers are not in conflict:

| Scope | Cases | WXT ContextCanon | Markdown baseline |
|---|---|---|---|
| `contextcanon benchmark run` (full) | **9** | 9/9 | 3/9 |
| `contextcanon benchmark smoke` (subset) | **7** | 7/7 | 3/7 |

`smoke` is the fast gate used by CI and by the clean-home acceptance test. It runs a
strict subset of the same cases, so a subset score is never a second opinion.

Requires nothing beyond the repository. No network, no LLM, no API key.

## Rules

1. **Synthetic only.** Fixtures are fictional (`bench:synthetic`). No real profile data is
   ever used, imported or recorded.
2. **Deterministic.** No sampling, no randomness, no wall-clock dependence in the
   expectations. Offsets are relative to run time; expectations are fixed values.
3. **No LLM judge by default.** Every expectation is an exact value compared with an exact
   answer. An LLM grader would make results unreproducible.
4. **Repeatable.** Equal scores across runs, or it is a bug.
5. **Failure → root cause → optimisation.** A failing case is a defect in the system, not
   something to be re-scored until it passes.

## Cases

| Case | Capability | Markdown baseline |
|---|---|---|
| `simple_recall` | structured read | PASS |
| `simple_update` | write then read | PASS |
| `temporal_as_of` | what was true at time T | FAIL |
| `supersede_chain` | revision chain | FAIL |
| `conflict_reject` | a contradiction is rejected, truth kept | FAIL |
| `provenance_filter` | which facts came from an inference | FAIL |
| `expired_audit` | an expired fact is still auditable | FAIL |
| `shared_store_consistency` | two agents read one shared store | PASS |
| `offline_rebuild` | offline work converges after rebuild | FAIL |

The three Markdown passes are not an oversight — they are the honest part of the result.

## The Markdown baseline

`benchmark/runner/run.py` implements a real baseline: one markdown file, last write wins,
`- key: value` lines. It is not a strawman. It reads and writes the same fixture, and it
fails only where the shipped last-write-wins model genuinely has no representation of the
concept.

## Adding a case

1. Add the case to `benchmark/cases/cases.json` with an `expected` value.
2. Add the method to `ContextCanonSystem` **and** `MarkdownBaseline` in the runner.
3. Map the `kind` in `HANDLERS`.
4. If the Markdown baseline passes, keep it. Report it. Do not redesign the case until it
   fails.

## What this is not

- Not a research-grade evaluation. Nine cases is a sketch, not a paper.
- Not a performance benchmark. No latency, no throughput, no token cost.
- Not a comparison against Mem0, Hindsight, Cognee, Supermemory or any other memory
  system. Those are deliberately out of scope for 0.1.0 (see `../docs/THIRD_PARTY_NOTICES.md`).

## No private results

No historical run data, no private paths and no internal scoreboard are published here.
The only numbers in this repository are ones you can regenerate yourself in a few seconds.
