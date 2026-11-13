#!/usr/bin/env python3
"""Serve the Planproof workspace and run one configured scan at a time."""
import argparse
import json
import os
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.drawing_library import DEFAULT_ARCHIVE, DrawingError, DrawingLibrary
from scripts.nemotron import MODEL, QUESTION, run
from scripts.scan_library import RUN_LOCK

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
SAMPLE = PUBLIC / "data/finnish/high_quality_architectural-13066.png"
RESULT = SAMPLE.with_name("run.json")


class Workspace(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api_params(self, allowed):
        try:
            params = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=6)
        except ValueError as exc:
            raise DrawingError(400, "Invalid drawing query.") from exc
        if params.keys() - set(allowed) or any(len(values) != 1 for values in params.values()):
            raise DrawingError(400, "Supply each supported drawing parameter once.")
        return {key: values[0] for key, values in params.items()}

    def drawing_get(self, route):
        library = self.server.drawing_library
        if route == "/api/drawings":
            params = self.api_params(("q", "source", "limit", "offset"))
            try:
                limit, offset = int(params.get("limit", 20)), int(params.get("offset", 0))
            except ValueError as exc:
                raise DrawingError(400, "Limit and offset must be integers.") from exc
            return self.send_json(200, library.search(params.get("q", ""), params.get("source", ""), limit, offset))
        path = self.api_params(("path",)).get("path")
        if not path:
            raise DrawingError(400, "Supply a drawing path.")
        if route == "/api/drawing":
            return self.send_json(200, library.details(path))
        if route == "/api/scan-drawing":
            from scripts.scan_library import scan_info
            if library.metadata(path)["kind"] != "scan":
                raise DrawingError(422, "Select a CubiCasa PNG scan for this reader.")
            return self.send_json(200, scan_info(library, path))
        with library.open_file(path) as (stream, size, mime):
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Type", mime)
            disposition = "inline" if mime in ("application/pdf", "image/png") else "attachment"
            self.send_header("Content-Disposition", f'{disposition}; filename="{Path(path).name}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route in ("/api/drawings", "/api/drawing", "/api/drawing-file", "/api/scan-drawing"):
            try:
                return self.drawing_get(route)
            except DrawingError as exc:
                return self.send_json(exc.status, {"message": exc.message})
            except (BrokenPipeError, ConnectionResetError):
                return
        if route != "/api/scan":
            return super().do_GET()
        saved = json.loads(RESULT.read_text()) if RESULT.exists() else None
        self.send_json(200, {
            "configured": bool(os.getenv("NEMOTRON_BASE_URL") and os.getenv("NEMOTRON_API_KEY")),
            "report": saved,
        })

    def answer_request(self, route):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise DrawingError(400, "Supply a JSON request with a content length.")
        try:
            length = int(self.headers["Content-Length"])
        except ValueError as exc:
            raise DrawingError(400, "Invalid request length.") from exc
        if length < 0 or length > 16384:
            raise DrawingError(413, "Drawing question is too large.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise DrawingError(400, "Supply a valid JSON question.") from exc
        keys = set(data) if isinstance(data, dict) else set()
        valid_request = keys == {"path", "question"} or (
            route == "/api/scan-drawing" and keys == {"path", "question", "refresh"}
            and isinstance(data["refresh"], bool))
        if (not valid_request
                or not isinstance(data["path"], str) or not isinstance(data["question"], str)
                or not data["question"].strip() or len(data["question"]) > 2000):
            raise DrawingError(400, "Supply a drawing path and a question of 1–2,000 characters.")
        path, question = data["path"], data["question"]
        library = self.server.drawing_library
        if route == "/api/scan-drawing":
            from scripts.scan_library import scan_answer
            if library.metadata(path)["kind"] != "scan":
                raise DrawingError(422, "Select a CubiCasa PNG scan for this reader.")
            result = (scan_answer(library, path, question, refresh=True) if data.get("refresh")
                      else scan_answer(library, path, question))
        else:
            result = library.ifc_answer(path, question)
        return self.send_json(200, result)

    def do_POST(self):
        if self.path not in ("/api/scan", "/api/drawing-answer", "/api/scan-drawing"):
            return self.send_json(404, {"message": "Unknown operation."})
        origin = self.headers.get("Origin")
        if (origin != f"http://127.0.0.1:{self.server.server_port}"
                or self.headers.get_content_type() != "application/json"
                or self.headers.get("X-Planproof-Run") != "1"):
            return self.send_json(403, {"message": "Run this operation from the local workspace."})
        if self.path != "/api/scan":
            try:
                return self.answer_request(self.path)
            except DrawingError as exc:
                return self.send_json(exc.status, {"message": exc.message})
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
    parser.add_argument("--archive", type=Path, default=os.environ.get("PLANPROOF_ARCHIVE") or DEFAULT_ARCHIVE,
                        help="Local Junction dataset ZIP (default PLANPROOF_ARCHIVE or the benchmark copy).")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Workspace, directory=str(PUBLIC))) as server:
        server.drawing_library = DrawingLibrary(args.archive)
        print(f"Planproof: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        finally:
            server.drawing_library.close()
