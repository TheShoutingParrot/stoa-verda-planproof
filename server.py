#!/usr/bin/env python3
"""Serve the Planproof workspace and run one configured scan at a time."""
import argparse
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from scripts.nemotron import MODEL, QUESTION, run

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SAMPLE = PUBLIC / "data/finnish/high_quality_architectural-13066.png"
RESULT = SAMPLE.with_name("run.json")
RUN_LOCK = threading.Lock()


class Workspace(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path != "/api/scan":
            return super().do_GET()
        saved = json.loads(RESULT.read_text()) if RESULT.exists() else None
        self.send_json(200, {
            "configured": bool(os.getenv("NEMOTRON_BASE_URL") and os.getenv("NEMOTRON_API_KEY")),
            "report": saved,
        })

    def do_POST(self):
        if self.path != "/api/scan":
            return self.send_json(404, {"message": "Unknown operation."})
        origin = self.headers.get("Origin")
        if (origin != f"http://127.0.0.1:{self.server.server_port}"
                or self.headers.get_content_type() != "application/json"
                or self.headers.get("X-Planproof-Run") != "1"):
            return self.send_json(403, {"message": "Run this scan from the local workspace."})
        base, key = os.getenv("NEMOTRON_BASE_URL"), os.getenv("NEMOTRON_API_KEY")
        if not base or not key:
            return self.send_json(503, {"message": "Set the inference endpoint and key on the local server first."})
        if not RUN_LOCK.acquire(blocking=False):
            return self.send_json(409, {"message": "A scan is already running."})
        try:
            report = run(SAMPLE, QUESTION, base, os.getenv("NEMOTRON_MODEL", MODEL), key)
            # Preserve the latest actual model response across connection failures.
            if report["status"] != "unavailable" or not RESULT.exists():
                temp = RESULT.with_suffix(".tmp")
                temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                temp.replace(RESULT)
            self.send_json(200, {"report": report})
        finally:
            RUN_LOCK.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4179)
    port = parser.parse_args().port
    with ThreadingHTTPServer(("127.0.0.1", port), partial(Workspace, directory=str(PUBLIC))) as server:
        print(f"Planproof: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
