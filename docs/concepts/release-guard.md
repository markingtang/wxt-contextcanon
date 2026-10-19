# Release Guard concepts

Deployment safety, separated from deployment targets.

The guard contains **no** host, project name, container name, image name or path. It reads
a deploy config and talks through a transport adapter. That is what makes the same code
safe to publish and safe to test.

## Steps

| # | Step | What it enforces |
|---|---|---|
| 1 | `project_guard` | The project name matches `[a-z0-9][a-z0-9_-]*` — syntax validation only; verify the intended target yourself |
| 2 | `mutation_intent` | A real deployment requires `--apply` **and** a stated `--intent` |
| 3 | `lock` | One deployment at a time; stale locks (>1h) require operator inspection |
| 4 | `integrity` | Deployment inputs hash-match a recorded baseline, or the baseline is written on first run |
| 5 | `backup_gate` | A backup must succeed before anything is replaced (skip only with an explicit flag) |
| 6 | `migration_test` | The legacy migration path is exercised before rollout |
| 7 | `deploy` | The deploy command, via the transport adapter |
| 8 | `post_health` | Configured health endpoints must answer |
| 9 | `smoke` | Configured smoke command must pass |
| 10 | `fail_closed` | Any failure aborts, reports the failed step, and releases the lock |

A failure at step 5 or 6 means step 7 never runs. That ordering is the point: **fail
before you mutate, not after**.

## Modes

```bash
./contextcanon guard plan                                  # dry run, makes no changes
./contextcanon guard apply --intent "why this is happening" # real run
```

`plan` prints the steps it *would* take. `apply` without `--intent` aborts — an unlabelled
mutation is not acceptable.

## Configuration

Everything comes from a deploy config JSON (see
`deploy/release-guard/deploy.example.json`):

```jsonc
{
  "project_name": "wxt-contextcanon",
  "compose_binary": "docker compose",
  "compose_files": ["deploy/docker/docker-compose.yml"],
  "services": ["contextcanon-api"],
  "lock_path": "./data/deploy.lock",
  "backup_command": "",
  "migration_test_command": "",
  "smoke_command": "",
  "deploy_command": "",              // overrides the composed command
  "health_endpoints": [],
  "transport": "local-shell",        // or "ssh-shell"
  "ssh": { "host_alias": "", "workdir": "" },
  "integrity_file": "./data/deploy-integrity.json"
}
```

For migration/smoke, empty command strings mean "skip this step" and are reported as `skipped`, never as
`ok`. Apply requires a backup command unless --skip-backup is explicitly supplied.

## Transport adapters

- **local-shell** — runs the command in a subprocess.
- **ssh-shell** — wraps the command as `ssh <alias> "cd <workdir> && <command>"`.
  Refuses to run unless `ssh.host_alias` is configured. **No alias is shipped.**

Kubernetes, Nomad and Swarm are out of scope for 0.1.2.

## Fake stack

`deploy/release-guard/fake_stack/` contains a tiny HTTP service on `127.0.0.1`, a fake
backup command and a fake migration test. This lets the guard be exercised end to end with
no Docker and no network:

```bash
./contextcanon guard plan
./contextcanon guard apply --intent "test the guard"
FAKE_MIGRATION_FAIL=1 ./contextcanon guard apply --intent "prove fail-closed"
```

The final command aborts at `migration_test`, before `deploy`, and releases the lock.
Those two behaviours are asserted in `tests/test_release_guard.py`.

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../quickstart/local.md).

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
