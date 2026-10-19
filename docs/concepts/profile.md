# Profile Core concepts

## A fact is a claim, not a string

A fact records *what* was claimed, *who or what* said it, *when* it started being true,
*when* it stops, how *sensitive* it is, and how much to *trust* it. Six fields exist
because each one answers a question you will eventually ask.

| Field | The question it answers |
|---|---|
| `value` | What do we believe? |
| `provenance` | Where did it come from? |
| `revision` / `supersedes` | What did we believe before? |
| `valid_from` / `valid_until` | When was it true? |
| `sensitivity` | May I repeat this out loud? |
| `certainty` | How sure are we? |

## Lifecycle

```
            ┌──────────────► rejected  (a contradicting claim was refused)
            │
  (write) ──┴──► active ──► superseded   (a newer revision replaced it)
                   │
                   └──────► expired      (its valid_until passed)
```

- **Nothing is deleted.** `expired`, `superseded` and `rejected` facts remain queryable
  with `--all` / `include_inactive`. Auditability beats tidiness.
- `expire` is a sweep, not a background job: `contextcanon profile expire` moves every fact whose
  `valid_until` has passed to `expired`. Run it from cron if you want it automatic.

## Durability

| Kind | Meaning | Example |
|---|---|---|
| `durable` | True until corrected | `communication.style` |
| `temporary` | True for a bounded window | `travel.current_city` |
| `scheduled` | Recurring or planned | `routine.weekly_review` |

Durability is metadata about intent. It does not change storage; it tells future readers
whether they should expect the fact to go stale.

## Conflict policies

When a write targets a `(subject, key)` that already has a *different* active value:

| `on_conflict` | Behaviour | Use when |
|---|---|---|
| `supersede` (default) | Old value becomes a superseded revision | A correction |
| `reject` | Incoming claim stored as `rejected`, active value untouched | A low-confidence guess contradicts a trusted value |
| `keep` | Existing value wins, nothing written | You want to preserve the first observation |

Rejecting is the important one. Silently overwriting a trusted value because an inference
looked plausible is how profiles rot. WXT ContextCanon makes the contradiction a *record* instead of
a *mutation*.

## Temporal reads

`profile_as_of(subject, timestamp)` returns, for each key, the highest revision whose
`valid_from <= T < valid_until` (treating a null `valid_until` as infinity). It uses
validity windows, **not** row creation time, so back-dated and scheduled facts resolve
correctly.

```bash
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
```

## Writing validity windows

`valid_from` and `valid_until` must be ISO timestamps **with a timezone**
(`2026-10-13T12:00:00Z`). A malformed timestamp is rejected with an error naming the
offending field. The window rules themselves are:

- **With `valid_from`:** `valid_until` must be later than `valid_from`. Both may be in
  the past — that is how a back-dated window for `as_of` queries is recorded, and it
  stays supported.
- **Without `valid_from`:** `valid_until` must be in the future. A `valid_until` that has
  already passed is rejected, and the error says the time is already past (it does not
  blame `valid_from`).

To record a fact that has already ended, pass a complete back-dated window
(`valid_from` before `valid_until`) or write the fact without `valid_until`, note the end
in provenance, and let `contextcanon profile expire` move it to `expired`. WXT
ContextCanon does not import history as already-expired rows on write.

## Sensitivity

`public` → `personal` → `sensitive` → `restricted`.

It is a label, not an access control. It exists so that a caller — a skill, a summariser,
a log pipeline — can decide what it is allowed to surface. Use `restricted` for anything
you would not want in a transcript.

## Provenance

```json
{
  "source": "user-stated",
  "ref": "onboarding-chat-01",
  "method": "explicit-answer",
  "observed_at": "2026-03-01T10:00:00Z",
  "confidence": 1.0
}
```

`source` values used in this project: `user-stated`, `observed`, `inferred`, `document`,
`agent-stated`, `demo-seed`. A fact with `source: unknown` should be treated as
unverified — the honest default is to distrust it.

## Audit

Every write appends to `fact_events` with an actor and a payload. `contextcanon profile audit`
gives you the trail; `contextcanon profile history` gives you the revision chain for one key.
Together they answer "who changed this, when, from what, and why".

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../quickstart/local.md).
