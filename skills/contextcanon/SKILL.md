---
name: wxt-contextcanon
description: >
  Use WXT ContextCanon when an agent needs to recall, update, or search a shared personal
  context (Profile Core), or when it is about to create/modify/delete files and
  needs mutation intent and a shared file-state ledger (Registry Core).
version: 0.1.0
---

# WXT ContextCanon - shared context and file-state ledger

WXT ContextCanon gives many agents **one** personal context and **one** file-state ledger.
Use it instead of re-deriving facts every session, and instead of silently
editing files without a declared intent.

**Scope check before you rely on it.** In this build every agent and every
device id lives in **one local store on one machine**. Multi-agent is real.
The "second device" is a logical device in the same database — real ledger
mechanics, no network between machines. Do not tell a user their laptop and
their desktop are synchronised; that transport does not exist yet.

## When to do what

| Situation | Do this |
|---|---|
| Starting work for a person | `profile_search` / `profile_get` before asking questions |
| You learned something durable | `profile_upsert` with a `source` and a `durability` |
| You need to know what was true at time T | `profile_as_of` |
| Two facts disagree | `profile_upsert` with `on_conflict=reject`, then review |
| You corrected a fact | `profile_upsert` (the old value stays as a superseded revision) |
| About to create/modify/delete files | `contextcanon registry begin --task-id ... --intent ...` |
| Finished touching files | `contextcanon registry end --task-id ... --result ok` |
| Need to know where a file is / its state | `registry_query` |
| Came back after being offline | `contextcanon registry recover` |

## Rules (keep them short on purpose)

1. **Recall before asking.** If the profile may already have the answer, read
   it first. Do not re-interview the person.
2. **Only write what you actually learned.** Never infer a durable fact from a
   single weak signal. If you must record a guess, set a low `confidence` and
   `source: inferred`.
3. **Never overwrite silently.** A correction supersedes; the old value stays
   auditable. A contradiction is rejected, not merged.
4. **Declare mutation intent before writing files.** `begin` … `end` around any
   batch of file changes.
5. **Prefer `valid_until` over deletion.** Time-limited facts expire on their
   own and stay auditable.
6. **Sensitivity is a first-class field.** If a fact is `sensitive` or
   `restricted`, do not surface it in summaries or logs.

## Minimal usage

```bash
contextcanon profile get    --subject demo:alex-chen --key timezone
contextcanon profile search --subject demo:alex-chen --query "editor"
contextcanon profile set    --subject demo:alex-chen --key tooling.editor --value zed \
                    --source user-stated --durability durable
contextcanon profile as-of  --subject demo:alex-chen --at 2026-01-01T00:00:00Z

contextcanon registry begin --task-id t-1 --intent "reorganise notes" --targets notes/a.md
contextcanon registry event --kind file.upsert --object-key notes/a.md --checksum abc123
contextcanon registry end   --task-id t-1 --result ok --changed notes/a.md
contextcanon registry query --object-key notes/a.md
contextcanon registry recover
```

## The 8 MCP tools

`profile_get`, `profile_search`, `profile_upsert`, `profile_as_of`,
`profile_history`, `profile_audit`, `registry_query`, `registry_event`.

Supersede and conflict resolution are parameters of `profile_upsert`
(`on_conflict: supersede | reject | keep`), not separate tools.

## What this skill deliberately does NOT contain

No governance charters, no schema dumps, no deployment rules. Those live in
`docs/` and in the CLI. If you need a rule that is not in the six above, it
belongs in the codebase, not in this file.
