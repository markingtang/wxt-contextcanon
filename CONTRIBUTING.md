# Contributing

English | [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for considering it. A few rules keep this repository publishable.

## Before you start

```bash
python tests/run_all.py            # must pass
python tools/scan_secrets.py       # must print GATE: PASS
python tools/prove_isolation.py    # static/config gate only
mkdir synthetic-watch
python tools/accept_clean_home.py --watch synthetic-watch
python tools/check_quickstart.py
python tools/check_install.py
```

## Hard rules

1. **No private data, ever.** No real names, devices, hosts, IP addresses, phone numbers,
   absolute paths from someone's machine, tokens, keys, project codenames, or customer
   information. If you need an example, invent one and mark it `SYNTHETIC`.
2. **No real configuration.** Hosts in examples are `localhost` or `127.0.0.1`. Paths are
   relative or `./data`. Device ids look like `demo-device`.
3. **No new runtime dependencies without strong justification.** The project currently
   needs nothing beyond the Python standard library and SQLite. That is a feature —
   a stranger can run it in ten minutes. A new dependency must earn its place.
4. **No vendored code.** If you copy a snippet from another project, say so in
   `docs/THIRD_PARTY_NOTICES.md` with its license. Undeclared copied code blocks release.
5. **No new MCP tools without discussion.** The surface is intentionally 8 tools. Put
   logic in the CLI or the service layer instead.
6. **Tests for behaviour, not for implementation.** If you change a business rule, add a
   case in `tests/` and — if it is user-visible — in `benchmark/cases/cases.json`.

## Style

- Python 3.9+ compatible, standard formatting, type hints on new public functions.
- Prefer small pure functions in the service layer over clever SQL.
- Comments explain *why*, not *what*.

## Benchmark contributions

Cases must be:

- **synthetic** — no real data,
- **deterministic** — no randomness, no wall-clock dependence in the expectation,
- **exact-match** — no LLM judge by default,
- **honest** — if the Markdown baseline passes your case, that is a valid result and
  it should be reported, not hidden.

## Pull requests

One logical change per PR. Describe what changed, why, and how you verified it. If your
change touches storage or the event log, say what happens to existing data.

## Licensing

The project is **Apache-2.0** (see [`LICENSE`](LICENSE)). By opening a pull request you
agree that your contribution is licensed under Apache-2.0, and that you have the right to
license it that way.

Two practical consequences:

- **Do not add runtime dependencies** without updating `docs/THIRD_PARTY_NOTICES.md` with
  the dependency, its licence and its redistribution terms. Apache-2.0 §4 has obligations
  around third-party notices; the project currently has none because it has no
  dependencies.
- **Do not copy code** from another project. If you must, declare it in
  `docs/THIRD_PARTY_NOTICES.md` with the upstream licence before the change can merge.

The Apache-2.0 grant covers code only. It does not transfer the name — see
[`TRADEMARKS.md`](TRADEMARKS.md) for what contributors may and may not do with it.

## Naming

The public surface is pinned by `tests/test_brand_consistency.py`:

| Thing | Value |
|---|---|
| Project name | `WXT ContextCanon` |
| Repository slug | `wxt-contextcanon` |
| CLI command | `contextcanon` |
| MCP server name | `wxt-contextcanon` |
| Skill name | `wxt-contextcanon` |
| Environment prefix | `WXT_CONTEXTCANON_` |

If a change touches any of those, that test is the place to look. Renaming any of them is
a deliberate, discussed decision — not a drive-by edit.

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](docs/quickstart/local.md).

CI checks Windows and Linux on Python 3.9 and 3.13 after an actual GitHub checkout
with origin. Full-history scans are separate from working-tree scans. MCP compatibility
uses pinned optional clients; see docs/MCP_TOOLS.md. There is no deployment job or secret
requirement. Original release history is preserved; normal branches, remotes and merges
are expected. Run output, not a frozen count in prose, is the authoritative test total.

A watch comparison only covers the named directory. Use synthetic fixtures in CI; it
cannot prove that real production systems were observed or untouched.
