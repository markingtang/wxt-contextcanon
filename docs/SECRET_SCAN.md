# Secret and private-identifier scanning

This is a hard gate. The repository is not publishable while
`REAL_SECRET > 0` or `PRIVATE_IDENTIFIER > 0`.

## Running it

```bash
python tools/scan_secrets.py            # working tree
python tools/scan_secrets.py --history  # every git object reachable from all refs
```

Commits, releases and any publishing decision must include a passing run **of both
modes**. The working-tree scan only sees the files that survive today; `--history` walks
every object reachable from all refs, so a credential that was committed and then deleted
is still caught. A release gate that runs only the working-tree scan can pass on a
repository whose history is unsafe.

## Classification

Every finding is one of:

| Class | Meaning | Blocks? |
|---|---|---|
| `REAL_SECRET` | A credential: private key, bearer token, JWT, API key, password assignment | **Yes** |
| `PRIVATE_IDENTIFIER` | A person, device, host, private IP, phone number, MAC address, email address, or absolute path from a private machine | **Yes** |
| `SAFE_EXAMPLE` | A **line explicitly annotated** as an allowed example (see below) | No |
| `FALSE_POSITIVE` | Matched text that is not what the pattern looks like | No |

### The only way a line is exempted

A regex match is downgraded to `SAFE_EXAMPLE` **only** when the *same line* contains the
explicit marker for that exact pattern:

```
WXT_SCAN_ALLOW:<pattern-id>
```

The marker names one pattern id and exempts that one pattern — it cannot exempt a line
wholesale. A line containing `e.g.`, `example`, `fake`, `synthetic`, `placeholder` or
`DEMO` is **not** exempted: a real credential that happens to share a line with the word
"example" is still a `REAL_SECRET`. There are no whole-file exemptions — not for
`SECURITY.md`, not for this document, not for the scanner itself.

If you genuinely need to document a credential *shape* in prose, write the marker on the
same line, naming the one pattern it exempts — and expect a reviewer to see it:

```
<your text>            WXT_SCAN_ALLOW:<pattern-id>
```

The marker exempts the one pattern whose id it names, on that one line, and nothing
else. Remove the marker and the line blocks the gate again. `tests/test_scan_secrets.py`
proves both halves: an allow-marked line passes, and a line whose marker names a
*different* pattern is still blocked.

## What is committed vs. what is not

The committed pattern set (`tools/scan_secrets.py`) is **generic only**:

- private key blocks, SSH public keys, `sk-`-style keys, bearer tokens, JWTs,
  credential assignments
- AWS access key ids (`AKIA...`), GitHub tokens (`ghp_`/`github_pat_`), Slack tokens
  (`xox...`), Google API keys (`AIza...`)
- private IPv4 ranges (`10./172.16-31./192.168.`), mobile-number shapes, MAC addresses,
  email addresses, Windows user paths, Unix `/home/<user>` and `/Users/<user>` paths,
  absolute drive paths, Google Sheet URLs, `/data_*` mount shapes

Site-specific private identifiers — a person's name or handle, a device model or serial,
a specific NAS project name, a specific port, a real phone number, a real Windows
username — are **deliberately not committed**, because publishing the list would leak the
identifiers themselves. They are supplied at scan time from a file outside the
repository:

```bash
python tools/scan_secrets.py \
  --extra-patterns /path/outside/repo/private-patterns.json
```

The extra file has the shape:

```json
{ "patterns": [ { "id": "...", "regex": "...", "class": "PRIVATE_IDENTIFIER" } ] }
```

## Verifying the scanner is not a no-op

The adversarial tests in `tests/test_scan_secrets.py` do this automatically. They assert,
among other things, that a real API key on a line containing "e.g." is still
`REAL_SECRET`, that a private IP on a line containing "example" is **not** auto-safe, that
the common token shapes are detected, and that a secret committed and then deleted is
still caught by `--history`. If any of those ever passes trivially, the scanner is broken
— do not trust a clean run.

When in doubt the scanner errs toward `REAL_SECRET` / `PRIVATE_IDENTIFIER`: a false
positive costs a reviewer a minute, a missed credential costs a leak.

## Git history is part of the surface

A secret deleted in the working tree still exists in history. This repository therefore
starts from a clean initial commit: **no history was imported from any private
repository**, and no code was cherry-picked across. If a secret is ever committed, the
fix is to rewrite history, not to add a new commit that deletes it.

## Related

- `tools/prove_isolation.py` — proves no configuration can reach a private host
- `tools/accept_clean_home.py` — proves a stranger can install from scratch
- `docs/THIRD_PARTY_NOTICES.md` — dependency and copied-code audit
