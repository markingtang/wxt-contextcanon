# Local (no Docker) deployment

中文入门：[5 分钟本地教程](../../docs/quickstart/local.zh-CN.md)。本页保留英文详细说明。

This is the recommended path for the first 30 minutes.

```bash
# from the repository root
python -m contextcanon_cli doctor          # or: ./contextcanon doctor
python -m contextcanon_cli config init     # write a local contextcanon.json (optional)
python -m contextcanon_cli demo seed --reset
python -m contextcanon_cli profile list --subject demo:alex-chen
```

State lives in `./data`:

```
data/
  profile.db            # Profile Core (SQLite)
  registry/shared.db    # Registry Core (SQLite)
  deploy.lock           # release guard lock (only during a deployment)
```

Delete `./data` to start over. Nothing outside the repository is touched.

## Windows

Use the `contextcanon.cmd` wrapper (sets `PYTHONPATH` for you):

```bat
contextcanon.cmd demo seed --reset
contextcanon.cmd profile list --subject demo:alex-chen
```

## macOS / Linux

```bash
./contextcanon demo seed --reset
```

## Production-like

If you later want Postgres or Docker, see `../docker/docker-compose.yml` and
`docs/architecture/overview.md`. WXT ContextCanon does not require either.

Shell examples on this page use Bash from the repository root. For PowerShell use
`.\contextcanon.cmd`; for CMD use `contextcanon.cmd`. The complete platform-specific
steps are in [Quickstart](../../docs/quickstart/local.md).
