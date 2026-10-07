# Release Guard

Deployment safety, with the target factored out.

```bash
./contextcanon guard plan                                     # dry run
./contextcanon guard apply --intent "why"                     # real run
./contextcanon guard apply --intent "why" --skip-backup       # explicitly skip the backup gate
python deploy/release-guard/guard.py plan --config deploy/release-guard/fake_stack/fake_deploy.json
```

## Files

| Path | Purpose |
|---|---|
| `guard.py` | the guard itself; configuration in, transport adapter out |
| `deploy.example.json` | documented config schema with local defaults |
| `fake_stack/fake_service.py` | tiny `127.0.0.1` HTTP service used as a deploy target |
| `fake_stack/fake_backup.py` | fake backup command |
| `fake_stack/fake_migration_test.py` | fake legacy migration test (`FAKE_MIGRATION_FAIL=1` forces failure) |
| `fake_stack/fake_deploy.json` | config that points the guard at the fake stack |
| `../../tests/test_release_guard.py` | tests for every gate, including fail-closed and lock behaviour |

## The ten steps, in order

| # | Step name | Enforces |
|---|---|---|
| 1 | `project_guard` | the project name is a legal compose project name |
| 2 | `mutation_intent` | `apply` requires a stated `--intent` |
| 3 | `lock` | one deployment at a time; stale locks are detected |
| 4 | `integrity` | deployment inputs hash-match a recorded baseline |
| 5 | `backup_gate` | a backup must succeed before anything is replaced |
| 6 | `migration_test` | the legacy migration path runs before rollout |
| 7 | `deploy` | the deploy command, via the transport adapter |
| 8 | `post_health` | configured health endpoints must answer |
| 9 | `smoke` | configured smoke command must pass |
| 10 | `fail_closed` | any failure aborts, names the step, releases the lock |

A failure at step 5 or 6 means step 7 never runs. **This list is the whole scope** —
nothing beyond these ten steps is implemented or claimed here.

## Design rules

- **No constants from any real deployment.** No host, project, container, image, service
  or path is baked into the code. Every value is read from config.
- **Fail before mutating.** Backup and migration tests run before the deploy command.
- **Fail closed.** Any failure aborts, names the failed step and releases the lock.
- **Skipped is not OK.** An unconfigured step is reported `skipped`, never `ok`.
- **Transports are adapters.** `local-shell` and `ssh-shell` only. No Kubernetes, Nomad or
  Swarm in 0.1.1.

## Trying fail-closed

```bash
FAKE_MIGRATION_FAIL=1 ./contextcanon guard apply --intent "prove fail-closed"
```

Expected: `outcome: aborted`, the `migration_test` step missing from the successful list,
`fail_closed: true`, and `deploy` never executed.

## Trying the lock

Run two `apply` commands concurrently; the second aborts with "another deployment holds
the lock". A lock older than one hour is reported as stale and retained for operator inspection.

## Tests

```bash
python -m unittest tests.test_release_guard -v
```

Requires no Docker: the fake stack is a standard-library HTTP server on `127.0.0.1:8787`.

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../../docs/quickstart/local.md).

### Failure and recovery boundaries

Actual order: project_guard, mutation_intent, lock, integrity, backup_gate,
migration_test, deploy, post_health, smoke; fail_closed records any failure.
A plan does not create an integrity baseline or lock. Apply writes a first-use baseline
under the lock. Review that baseline explicitly when deployment inputs intentionally change.
Both CLI entrypoints return nonzero on aborted runs. Lock release is attempted on failure
and KeyboardInterrupt. Abrupt process termination may leave a lock: inspect before removal.
No automatic rollback, backup restoration, or process-tree recovery is implemented.
An aborted health/smoke step can leave deployed services running. stop_command is descriptive
configuration and is not automatically executed. After testing the fake stack, run:
`python deploy/release-guard/fake_stack/fake_service.py --stop`.
