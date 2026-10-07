# WXT ContextCanon benchmark report (synthetic)

_All fixtures are fictional. No LLM judge. Deterministic exact-match scoring._

**WXT ContextCanon: 9/9**   |   **Markdown baseline: 3/9**

| Case | Capability | WXT ContextCanon | Markdown |
|---|---|---|---|
| simple_recall | structured read | PASS | PASS |
| simple_update | write then read | PASS | PASS |
| temporal_as_of | temporal lifecycle | PASS | FAIL |
| supersede_chain | revision chain | PASS | FAIL |
| conflict_reject | conflict / supersede | PASS | FAIL |
| provenance_filter | provenance | PASS | FAIL |
| expired_audit | expired auditability | PASS | FAIL |
| shared_store_consistency | shared store consistency | PASS | PASS |
| offline_rebuild | offline recovery / rebuild | PASS | FAIL |

## Why not just Markdown?

Markdown wins or ties on plain recall and write-then-read. That is real,
and pretending otherwise would be dishonest. WXT ContextCanon only pulls ahead where the
shipped last-write-wins Markdown model has nothing to say: time, conflict,
provenance, lifecycle, and a rebuildable projection.

## Where the two diverge

- **temporal_as_of** (temporal lifecycle): WXT ContextCanon `"vscode"` vs Markdown `"unsupported:markdown-baseline"`
- **supersede_chain** (revision chain): WXT ContextCanon `["vscode", "zed"]` vs Markdown `[]`
- **conflict_reject** (conflict / supersede): WXT ContextCanon `{"rejected": 1, "timezone": "Europe/Lisbon"}` vs Markdown `{"rejected": 0, "timezone": "America/New_York"}`
- **provenance_filter** (provenance): WXT ContextCanon `["America/New_York"]` vs Markdown `[]`
- **expired_audit** (expired auditability): WXT ContextCanon `"expired"` vs Markdown `"unsupported:markdown-baseline"`
- **offline_rebuild** (offline recovery / rebuild): WXT ContextCanon `true` vs Markdown `false`
