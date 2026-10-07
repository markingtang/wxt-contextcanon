"""Owned loopback-only synthetic service; never stop a process by a reused PID."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("CONTEXTCANON_FAKE_PORT", "8787"))
PID_FILE = os.environ.get("CONTEXTCANON_FAKE_STATE", os.path.abspath("data/fake-service.json"))
URL = "http://%s:%d" % (HOST, PORT)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def state():
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def probe():
    try:
        with OPENER.open(URL + "/health", timeout=1) as r:
            return json.load(r)
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({"service": "fake-api", "instance": self.server.instance}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/stop" or self.headers.get("X-Instance") != self.server.instance:
            self.send_error(403)
            return
        self.send_response(200)
        self.end_headers()
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):
        pass


def serve(instance):
    with HTTPServer((HOST, PORT), Handler) as server:
        server.instance = instance
        server.serve_forever(poll_interval=0.1)
    return 0


def start():
    previous = state()
    live = probe()
    if live:
        return 0 if previous.get("instance") == live.get("instance") else 1
    instance = uuid.uuid4().hex
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--serve", "--instance", instance], **kwargs)
    for _ in range(50):
        live = probe()
        if live and live.get("instance") == instance:
            os.makedirs(os.path.dirname(os.path.abspath(PID_FILE)), exist_ok=True)
            with open(PID_FILE, "w", encoding="utf-8") as f:
                json.dump({"pid": child.pid, "instance": instance}, f)
            print("fake service started")
            return 0
        if child.poll() is not None:
            break
        time.sleep(0.1)
    if child.poll() is None:
        child.terminate()  # only the child created by this invocation
    child.wait(timeout=5)
    return 1


def stop():
    owned = state()
    live = probe()
    if not live:
        if owned:
            os.remove(PID_FILE)
        return 0
    if not owned or live.get("instance") != owned.get("instance"):
        return 1
    req = urllib.request.Request(URL + "/stop", data=b"", headers={"X-Instance": owned["instance"]})
    with OPENER.open(req, timeout=3):
        pass
    for _ in range(50):
        if probe() is None:
            os.remove(PID_FILE)
            print("fake service stopped")
            return 0
        time.sleep(0.1)
    return 1


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ("serve", "start", "stop", "smoke"):
        group.add_argument("--" + name, action="store_true")
    parser.add_argument("--instance", default="")
    args = parser.parse_args()
    if args.serve:
        return serve(args.instance)
    if args.start:
        return start()
    if args.stop:
        return stop()
    live = probe()
    return 0 if live and live.get("instance") == state().get("instance") else 1


if __name__ == "__main__":
    raise SystemExit(main())
