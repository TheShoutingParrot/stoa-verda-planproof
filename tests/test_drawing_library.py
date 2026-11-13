"""Exercise the drawing library through the local server and an answer-free test ZIP."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import sys
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from zipfile import ZipFile

from server import PUBLIC, Workspace, ThreadingHTTPServer
from scripts import drawing_library
from scripts.drawing_library import DrawingError, DrawingLibrary

SWISS = "data/swiss_dwellings/floor-two.pdf"
IFC = "data/ifc_models/example.ifc"
IFC2 = "data/ifc_models/second.ifc"
SCAN = "data/cubicasa5k/scan1.png"


def release(path):
    source = PUBLIC / "data/swiss/site1102_bldg2242_floor10281.dxf"
    with ZipFile(path, "w") as archive:
        for key, data in (
            (SWISS, b"%PDF-1.4"), (SWISS[:-4] + ".dxf", source.read_bytes()),
            (IFC, b"IFC model one"), (IFC2, b"IFC model two"),
            ("data/ifc_models/LICENSE.md", b"| example.ifc | Native model example | credits | url | license |"), (SCAN, b"\x89PNG\r\n\x1a\n"),
            ("data/swiss_dwellings/orphan.pdf", b"orphan"), ("data/ifc_models/picture.png", b"not a scan"),
            ("data/ifc_models/../escape.ifc", b"unsafe"), ("data/ifc_models/x\\y.ifc", b"unsafe"),
            ("data/ifc_models/file\nname.ifc", b"unsafe"), ("questions.jsonl", b"never open this manifest"),
        ):
            archive.writestr("junction-dataset/" + key, data)


class QuietWorkspace(Workspace):
    def log_message(self, *args):
        pass


@contextmanager
def serve(library):
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietWorkspace, directory=str(PUBLIC))) as server:
        server.drawing_library = library
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        archive = Path(self.scratch.name) / "release.zip"
        release(archive)
        self.library = DrawingLibrary(archive)
        self.addCleanup(self.library.close)

    def test_metadata_only_source_mix_filter_pagination(self):
        with patch.object(self.library._archive, "open", side_effect=AssertionError("Metadata read source data")):
            self.assertEqual(self.library.search()["total"], 4)
            self.assertEqual([r["kind"] for r in self.library.search(limit=3)["drawings"]], ["swiss", "ifc", "scan"])
            self.assertEqual(self.library.search("FLOOR TWO")["drawings"][0]["path"], SWISS)
            self.assertEqual(self.library.search(source="ifc_models", limit=1, offset=1)["drawings"][0]["path"], IFC2)
            self.assertEqual(self.library.search(source="cubicasa5k")["drawings"][0]["path"], SCAN)
            self.assertEqual(self.library.details(IFC)["geometry"], None)
        for kwargs in ({"source": "x"}, {"offset": -1}, {"limit": 201}, {"q": "q" * 221}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DrawingError):
                self.library.search(**kwargs)
        for name in ("questions.jsonl", "data/ifc_models/../escape.ifc", "data/ifc_models/x\\y.ifc",
                     "data/ifc_models/file\nname.ifc", "data/swiss_dwellings/orphan.pdf", "data/ifc_models/picture.png",
                     "/etc/passwd", "../questions.jsonl", "junction-dataset/" + SWISS):
            with self.subTest(name=name), self.assertRaises(DrawingError):
                self.library.read_bytes(name)

    def test_missing_archive_and_file_stream_integrity(self):
        library = DrawingLibrary(Path(self.scratch.name) / "absent.zip")
        self.assertFalse(library.search()["available"])
        invalid = Path(self.scratch.name) / "not-a-dataset.zip"
        with ZipFile(invalid, "w") as z:
            z.writestr("notes.txt", "Only unrelated files")
        self.assertFalse(DrawingLibrary(invalid).search()["available"])
        with self.assertRaises(DrawingError) as exc:
            library.metadata(SWISS)
        self.assertEqual(exc.exception.status, 503)
        self.assertEqual(self.library.read_bytes(SWISS), b"%PDF-1.4")
        with self.assertRaises(DrawingError):
            self.library.metadata(SWISS[:-4] + ".dxf")
        with self.library.open_file(IFC) as (stream, size, mime):
            self.assertEqual((stream.read(), size, mime), (b"IFC model one", 13, "application/octet-stream"))

    def test_parallel_geometry_load_uses_one_extraction_and_independent_original_reads(self):
        with patch.object(drawing_library, "extract_rooms", wraps=drawing_library.extract_rooms) as extraction:
            with ThreadPoolExecutor(6) as pool:
                details = list(pool.map(self.library.details, [SWISS] * 6))
            self.assertEqual(extraction.call_count, 1)
        geometry = details[0]["geometry"]
        self.assertEqual(geometry["sheet"]["id"], "floor-two")
        self.assertEqual(geometry["sheet"]["dxfUrl"], self.library.metadata(SWISS)["dxfUrl"])
        self.assertEqual(sum(room["label"] == "Stanza" for room in geometry["rooms"]), 9)
        with ThreadPoolExecutor(6) as pool:
            self.assertEqual(list(pool.map(self.library.read_bytes, [SWISS, IFC] * 8)), [b"%PDF-1.4", b"IFC model one"] * 8)

    def test_ifc_answer_reuses_selected_model_under_concurrency(self):
        parses = []
        def fake_parse(raw, title=None):
            time.sleep(.01)
            parses.append((raw, title))
            return raw
        fake = types.SimpleNamespace(build_model=fake_parse, answer=lambda model, question: {"method": model.decode(), "question": question})
        with patch("scripts.ifc_takeoff", fake, create=True):
            with ThreadPoolExecutor(4) as pool:
                response = list(pool.map(lambda _: self.library.ifc_answer(IFC, "How many doors?"), range(4)))
            self.assertEqual(len(parses), 1)
            self.assertEqual(response[0]["result"]["method"], "IFC model one")
            self.assertEqual(self.library.ifc_answer(IFC2, "How many walls?")["result"]["method"], "IFC model two")
            self.assertEqual(parses, [(b"IFC model one", "Native model example"), (b"IFC model two", None)])
            self.assertEqual(self.library.search("Native model example")["drawings"][0]["path"], IFC)

    def test_http_contract_and_request_guards(self):
        with serve(self.library) as port:
            def call(method, url, body=None, headers=None):
                client = HTTPConnection("127.0.0.1", port, timeout=2)
                try:
                    client.request(method, url, body, headers or {})
                    response = client.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    client.close()

            self.assertEqual(call("GET", "/api/drawings?source=ifc_models&limit=1")[0], 200)
            for query in ("limit=0", "limit=5&limit=5", "source=no", "q=ok&u=no", "offset=-1", "limit=bad"):
                self.assertEqual(call("GET", "/api/drawings?" + query)[0], 400)
            for name in ("/api/drawing-file", "/api/drawing"):
                self.assertEqual(call("GET", name + "?" + urlencode({"path": "../../questions.jsonl"}))[0], 404)
            status, headers, data = call("GET", "/api/drawing-file?" + urlencode({"path": SWISS}))
            self.assertEqual((status, headers["Content-Type"], data), (200, "application/pdf", b"%PDF-1.4"))
            self.assertEqual(call("GET", "/api/scan")[0], 200)
            headers = {"Content-Type": "application/json", "X-Planproof-Run": "1",
                       "Origin": f"http://127.0.0.1:{port}"}
            body = json.dumps({"path": IFC, "question": "How many walls?"})
            self.assertEqual(call("POST", "/api/drawing-answer", body, {**headers, "Origin": "https://elsewhere.invalid"})[0], 403)
            self.assertEqual(call("POST", "/api/drawing-answer", body, {**headers, "X-Planproof-Run": "0"})[0], 403)
            self.assertEqual(call("POST", "/api/drawing-answer", " " * 17000, headers)[0], 413)
            for bad in ("[", "null", "{}", '{"path":42,"question":false}'):
                self.assertEqual(call("POST", "/api/drawing-answer", bad, headers)[0], 400)
            with patch("scripts.ifc_takeoff", types.SimpleNamespace(build_model=lambda raw, title=None: raw,
                       answer=lambda model, question: {"status": "answered", "answer": 0}), create=True):
                status, _, data = call("POST", "/api/drawing-answer", body, headers)
                self.assertEqual((status, json.loads(data)["result"]["answer"]), (200, 0))
            self.assertEqual(call("POST", "/api/drawing-answer", json.dumps({"path": SWISS, "question": "doors?"}), headers)[0], 422)
            scan = types.ModuleType("scripts.scan_library")
            scan.scan_info = lambda library, path: {"path": path}
            scan.scan_answer = lambda library, path, question: {"question": question, "path": path}
            with patch.dict(sys.modules, {"scripts.scan_library": scan}):
                self.assertEqual(call("GET", "/api/scan-drawing?" + urlencode({"path": IFC}))[0], 422)
                status, _, desc = call("GET", "/api/scan-drawing?" + urlencode({"path": SCAN}))
                self.assertEqual((status, json.loads(desc)["path"]), (200, SCAN))
                status, _, result = call("POST", "/api/scan-drawing", json.dumps({"path": SCAN, "question": "count?"}), headers)
                self.assertEqual((status, json.loads(result)["question"]), (200, "count?"))

            from scripts.scan_library import RUN_LOCK
            with patch.dict(os.environ, {"NEMOTRON_BASE_URL": "https://example.invalid/v1", "NEMOTRON_API_KEY": "test",
                                        "PLANPROOF_SCAN_LOCAL": self.scratch.name,
                                        "PLANPROOF_SCAN_CHECKPOINT": str(Path(self.scratch.name) / "absent"),
                                        "PLANPROOF_SCAN_RESULTS": self.scratch.name}), RUN_LOCK:
                self.assertEqual(call("POST", "/api/scan", "{}", headers)[0], 409)
                question = json.dumps({"path": SCAN, "question": "How many windows?"})
                self.assertEqual(call("POST", "/api/scan-drawing", question, headers)[0], 409)


if __name__ == "__main__":
    unittest.main()
