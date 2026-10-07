# Security policy

## Scope

WXT ContextCanon — the packages under `packages/`, the CLI, the MCP server, the
release guard, and the benchmark runner.

## Supported versions

`0.1.1` is the current patch release; the original `0.1.0` history is preserved. There is no supported-version
matrix yet, and the public repository is https://github.com/markingtang/wxt-contextcanon.

## Reporting

Open an issue **without** including any personal data, and describe:

1. what you did,
2. what you expected,
3. what happened,
4. whether it involved data you consider private.

If the report involves data you cannot share, describe the mechanism instead of the data.

## Security model — what this project does and does not protect

**Does:**

- Keep all data local by default (a SQLite file inside the working directory).
- Record provenance, sensitivity and revision history for every fact.
- Never delete facts implicitly — expired, superseded and rejected facts remain auditable.
- Fail closed in the release guard: any failed step aborts the deployment and releases
  the lock.
- Ship a scanner (`tools/scan_secrets.py`) that fails when a credential or a
  private identifier appears in the repository. `python tools/scan_secrets.py` scans the
  working tree; adding `--history` also scans every object reachable from every git ref,
  which is what catches a secret that was committed and later deleted. The scan only
  passes when **zero** findings are exempt, so a clean result is a real result.

**Does not:**

- Encrypt the database at rest. If you need that, use full-disk encryption or a database
  with encryption enabled.
- Authenticate anything. There is no server, no accounts, no network listener in 0.1.1. The
  MCP server speaks JSON-RPC over stdio to a client that already runs as you.
- Sandbox agents. An agent able to call `profile_upsert` can write any fact for any
  subject. Treat MCP access as equivalent to shell access.
- Protect against a compromised host. Anything running as your user can read `./data`.

## Handling sensitive facts

- Use `sensitivity: restricted` for anything you would not want in a log or a summary.
- The `restricted` level is a label, not an access control. Nothing enforces it yet.
- Do not put credentials in facts. Store a *reference* to a secret manager, never the
  secret. The demo persona models exactly this with its `secrets.policy` fact.

## Out of scope

- Denial of service against a local SQLite file.
- Issues that require you to already have arbitrary code execution on the host.
- The fictional demo persona (`demo:alex-chen`) — it is synthetic by construction.

## Output and retention boundaries

CLI/MCP success responses and audit events contain the requested fact values, including
restricted values. Do not send them to public logs. Internal MCP errors omit raw exception
text, but custom Guard commands may emit sensitive stderr; review deployment output locally.
The registry does not read file contents, but callers can put arbitrary data into event
payloads. It cannot prevent a caller from storing a credential. Sensitivity, actor, source,
and device identifiers are caller-supplied metadata, not authentication or authorization.

The isolation checker is a static/configuration check plus optional metadata comparison.
It is not a sandbox, a network monitor, or proof that a configured command cannot reach
production. Synthetic watch results only describe the watched synthetic directory.
