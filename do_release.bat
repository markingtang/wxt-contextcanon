@echo off
cd /d "E:\Public Core\wxt-contextcanon-public-final"
git pull origin main
git add -A
git commit -m "fix: v0.1.2 — preserve file version metadata in registry projection; distinguish expired vs malformed valid_until

- registry_core/service.py: file.upsert/write/update events now carry version/updated_by/date
  into the shared_index state, while the numeric version column remains the ledger event counter.
- profile_core/service.py: split timestamp validation so malformed valid_from/valid_until name
  the offending field; a past valid_until without valid_from now raises a clear 'already in the
  past' error instead of a generic message. valid_from<valid_until rule unchanged.
- mcp_server/server.py: surface ValueError messages verbatim as isError results (curated, safe).
- cli.py: print ValueError messages to stderr with exit 1.
- docs: explain the validity-window rules and registry file metadata projection.
- tests: add registry metadata projection + rebuild, profile valid_until error cases, MCP error clarity.
- version bumps 0.1.1 -> 0.1.2 across public metadata, config example, CLI/SKILL/mcp client probes.

No history rewrite; append-only ledger unchanged."
git push origin main
