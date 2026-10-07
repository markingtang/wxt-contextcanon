# Five-minute local Quickstart

Requirements: Git and Python 3.9+ with SQLite. Check `python --version` on Windows;
Linux/macOS may call it `python3`. No package installation, Docker, account, or API key
is needed. Use a new clone for the synthetic demo; `--reset` replaces demo state.

## Get the code (all shells)

```text
git clone https://github.com/markingtang/wxt-contextcanon.git
cd wxt-contextcanon
```

## Run in your shell

Choose ONE complete block below. Each starts from the repository directory.
PowerShell needs `.\`; CMD can use the filename; Bash needs `./`.
The Bash launcher selects `python3` or `python` automatically.

## Windows PowerShell

```powershell
.\contextcanon.cmd doctor
.\contextcanon.cmd demo seed --reset
.\contextcanon.cmd profile get --subject demo:alex-chen --key tooling.editor
.\contextcanon.cmd profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
.\contextcanon.cmd profile history --subject demo:alex-chen --key tooling.editor
.\contextcanon.cmd profile as-of --subject demo:alex-chen --days-ago 30
.\contextcanon.cmd registry demo --reset
.\contextcanon.cmd benchmark smoke
.\contextcanon.cmd guard plan
```

## Windows CMD

```cmd
contextcanon.cmd doctor
contextcanon.cmd demo seed --reset
contextcanon.cmd profile get --subject demo:alex-chen --key tooling.editor
contextcanon.cmd profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
contextcanon.cmd profile history --subject demo:alex-chen --key tooling.editor
contextcanon.cmd profile as-of --subject demo:alex-chen --days-ago 30
contextcanon.cmd registry demo --reset
contextcanon.cmd benchmark smoke
contextcanon.cmd guard plan
```

## Windows Git Bash

```bash
./contextcanon doctor
./contextcanon demo seed --reset
./contextcanon profile get --subject demo:alex-chen --key tooling.editor
./contextcanon profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
./contextcanon profile history --subject demo:alex-chen --key tooling.editor
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
./contextcanon registry demo --reset
./contextcanon benchmark smoke
./contextcanon guard plan
```

## Linux / macOS

```sh
./contextcanon doctor
./contextcanon demo seed --reset
./contextcanon profile get --subject demo:alex-chen --key tooling.editor
./contextcanon profile set --subject demo:alex-chen --key demo.score --value 42 --source user-stated
./contextcanon profile history --subject demo:alex-chen --key tooling.editor
./contextcanon profile as-of --subject demo:alex-chen --days-ago 30
./contextcanon registry demo --reset
./contextcanon benchmark smoke
./contextcanon guard plan
```

## Expected results

- Doctor: `ok: true`.
- Seed: fictional `demo:alex-chen`, no imported personal data.
- Current editor: `zed`; history: `vscode` then `zed`.
- Writing `demo.score` creates the number 42, with a source.
- Thirty days ago: editor `vscode`. The relative date keeps working in future years.
- Registry: `idempotent: true`, pending outbox 0. Both devices are logical IDs in one database.
- Benchmark: 7/7 for ContextCanon; the deliberately simple Markdown baseline scores 3/7.
- Guard: `outcome: planned`. No deployment, baseline write, or lock creation.

Default data is under `./data` relative to the working directory. Existing
`contextcanon.json` or `WXT_CONTEXTCANON_*` overrides can select other paths; inspect
`config show` before using real data. Facts and audit records are stored in plaintext.
Sensitivity labels do not hide data from connected agents.

## Optional installation

Inside a virtual environment, `python -m pip install .` installs the `contextcanon`
command and its demo/benchmark/guard assets. Editable development installation is
`python -m pip install -e .`. No runtime packages are required; pip fetches the build
backend. The source launchers above need neither pip nor an activated environment.
Use a fresh working directory to choose where installed commands keep their local data.

## Connect an Agent

Follow [MCP client setup](../MCP_TOOLS.md#client-configuration). MCP waits for protocol
messages on stdin, so launching `mcp` by hand appears idle; it is not an interactive prompt.
The client must use the same explicit database paths to see the facts you seeded.
No ChatGPT chat history or other platform history is automatically imported.

## Verify this tutorial

`python tools/check_quickstart.py` executes the applicable blocks in isolated synthetic
storage and asserts the results. Windows checks PowerShell, CMD and Git Bash; Unix checks
Bash. A missing shell is reported as SKIP, not PASS. macOS is not part of CI.
