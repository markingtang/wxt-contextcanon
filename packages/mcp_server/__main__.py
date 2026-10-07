"""Entry point: `python -m mcp_server` (stdio MCP server).

Run with PYTHONPATH pointing at the repository's `packages/` directory, or
after `pip install -e .`.
"""

import sys

from .server import build_server


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    server = build_server(config_path)
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
