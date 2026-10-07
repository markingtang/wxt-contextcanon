# Demo persona: Alex Chen

> **DEMO / SYNTHETIC.** Alex Chen is a fictional person. Nothing in this folder
> refers to a real individual, device, company, address, account, or identifier.
> It exists so a new user can see what a populated Profile Core looks like
> without importing anything personal.

## What this persona demonstrates

| Capability | Where to look |
|---|---|
| Durable facts | `role`, `timezone`, `communication.style`, `tooling.notes` |
| Temporary facts | `travel.current_city`, `project.current_focus`, `availability.status` |
| Scheduled facts | `routine.weekly_review`, `routine.backup_window`, `event.conference_attendance` |
| Provenance / source | every fact carries `provenance.source`, `ref`, `method`, `confidence` |
| Sensitivity levels | `public` → `personal` → `sensitive` (`accessibility.needs`, budget) → `restricted` (`secrets.policy`) |
| Supersede | `tooling.editor`: `vscode` → `zed`; the old value remains as a superseded revision |
| Rejected conflict | `timezone`: an inferred `America/New_York` was rejected rather than overwriting the trusted value |
| Expired | `travel.parking_permit`: window has passed, marked `expired`, never deleted |

## Seeding

```bash
./contextcanon demo seed --reset
./contextcanon profile list --subject demo:alex-chen
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
```

Dates in the persona are expressed as offsets from "now" (for example
`valid_until_offset_days: -2`), so the demo behaves correctly whenever it is
cloned.

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../../docs/quickstart/local.md).
