"""Fake deployment target used by the release-guard tests.

A tiny HTTP service on 127.0.0.1 that answers /health. It exists so the guard
can be exercised end to end - lock, backup gate, migration test, deploy, health,
smoke, fail-closed - without Docker, a network, or any real infrastructure.

    python fake_service.py --start    # start in the background
    python fake_service.py --smoke    # exit 0 if /health answers
    python fake_service.py --stop
    python fake_service.py --serve    # run in the foreground
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 8787
HERE = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(HERE, "fake_service.pid")
URL = "http://%s:%d/health" % (HOST, PORT)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/health"):
            body = json.dumps({"status": "ok", "service": "fake-api"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def serve() -> int:
    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()
    return 0


def wait_healthy(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as response:
                if 200 <= response.status < 400:
                    return True
        except Exception:  # noqa: BLE001 - still starting up
            time.sleep(0.3)
    return False


def start() -> int:
    if wait_healthy(1.0):
        print("already running")
        return 0
    args = [sys.executable, os.path.abspath(__file__), "--serve"]
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, **kwargs)
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(process.pid))
    if not wait_healthy():
        return 1
    print("fake service healthy at %s" % URL)
    return 0


def stop() -> int:
    if os.path.exists(PID_FILE):
        with open(PID_FILE, "r", encoding="utf-8") as handle:
            pid = int(handle.read().strip() or 0)
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"] if os.name == "nt" else ["kill", str(pid)],
                    capture_output=True,
                )
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        os.remove(PID_FILE)
    print("stopped")
    return 0


def smoke() -> int:
    if not wait_healthy(5.0):
        print("smoke failed: no health response")
        return 1
    print("smoke ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.serve:
        return serve()
    if args.start:
        return start()
    if args.stop:
        return stop()
    if args.smoke:
        return smoke()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
