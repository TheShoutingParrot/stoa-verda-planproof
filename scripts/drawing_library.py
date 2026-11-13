"""Index released drawing members without opening any benchmark questions or labels."""
from collections import OrderedDict
from contextlib import contextmanager
from itertools import zip_longest
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlencode, urlsplit
from zipfile import BadZipFile, ZipFile

from .extract_rooms import extract_rooms

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / ".local/evaluation/swiss-frontier/inputs/junction-dataset.zip"
PREFIX = "junction-dataset/"
SOURCES = {"swiss_dwellings": "swiss", "ifc_models": "ifc", "cubicasa5k": "scan"}
SUFFIXES = {"swiss_dwellings": {".pdf", ".dxf"}, "ifc_models": {".ifc"}, "cubicasa5k": {".png"}}
CONTENT_TYPES = {".pdf": "application/pdf", ".dxf": "application/dxf",
                 ".ifc": "application/octet-stream", ".png": "image/png"}
# Largest original IFC in the release is 85 MB. Cap decompressed members in an operator-selected pack.
MAX_MEMBER = 128 * 1024 * 1024
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().-]{0,230}\.[A-Za-z0-9]+")


class DrawingError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def file_url(path):
    return "/api/drawing-file?" + urlencode({"path": path})


def source_url(value):
    if not value or any(ord(ch) < 32 or ch == '\\' for ch in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return None


class DrawingLibrary:
    def __init__(self, archive_path=None):
        self.archive_path = Path(archive_path) if archive_path else None
        self.available = False
        self.message = "The drawing archive is unavailable. Set PLANPROOF_ARCHIVE or start the local server with --archive."
        self._archive = None
        self._files = {}
        self._records = {}
        self._paths = []
        self._swiss_cache = OrderedDict()
        self._swiss_lock = threading.Lock()
        self._ifc_key = self._ifc_model = None
        self._ifc_lock = threading.Lock()
        if self.archive_path:
            try:
                self._archive = ZipFile(self.archive_path)
                self._index()
            except (BadZipFile, OSError):
                self.close()
                return
            if not self._records:
                self.close()
                self.message = "This archive contains no supported drawing members. Select the Junction dataset ZIP."
                return
            self.available = True
            self.message = ""

    def _index(self):
        candidates = {}
        duplicates = set()
        catalog_entries = []
        for info in self._archive.infolist():
            name = info.filename
            if name == PREFIX + "data/ifc_models/LICENSE.md":
                catalog_entries.append(info)
                continue
            if not name.startswith(PREFIX):
                continue
            path = name[len(PREFIX):]
            parts = path.split("/")
            if len(parts) != 3 or parts[0] != "data" or parts[1] not in SOURCES:
                continue
            source, filename = parts[1:]
            suffix = Path(filename).suffix
            if (not SAFE_NAME.fullmatch(filename) or suffix not in SUFFIXES[source]
                    or info.flag_bits & 1 or not 0 < info.file_size <= MAX_MEMBER):
                continue
            if path in candidates:
                duplicates.add(path)
            candidates[path] = info
        for path in duplicates:
            candidates.pop(path)
        attributions = {}
        if len(catalog_entries) == 1 and not catalog_entries[0].flag_bits & 1 and catalog_entries[0].file_size <= 1024 * 1024:
            from .ifc_takeoff import catalog_titles
            attributions = catalog_titles(self._archive.read(catalog_entries[0]), with_attribution=True)
        groups = {source: [] for source in SOURCES}
        for path in sorted(candidates):
            _, source, filename = path.split("/")
            kind = SOURCES[source]
            if kind == "swiss":
                if not path.endswith(".pdf") or path[:-4] + ".dxf" not in candidates:
                    continue
            record = dict(path=path, source=source, name=filename, title=Path(filename).stem,
                          kind=kind, fileUrl=file_url(path))
            if kind == 'ifc' and filename in attributions:
                credit = attributions[filename]
                record['title'] = credit['work'] or record['title']
                record['attribution'] = {**credit, 'sourceUrl': source_url(credit['sourceUrl'])}
            self._files[path] = candidates[path]
            if kind == "swiss":
                dxf = path[:-4] + ".dxf"
                record["dxfUrl"] = file_url(dxf)
                self._files[dxf] = candidates[dxf]
            self._records[path] = record
            groups[source].append(path)
        self._paths = [p for group in zip_longest(*groups.values()) for p in group if p is not None]

    def close(self):
        if self._archive:
            self._archive.close()
        self._archive = None
        self.available = False

    def search(self, q="", source="", limit=20, offset=0):
        if not isinstance(q, str) or len(q) > 220 or source not in ("", *SOURCES):
            raise DrawingError(400, "Supply a drawing name or a supported source.")
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise DrawingError(400, "Limit must be 1–200 and offset must be nonnegative.")
        terms = q.casefold().split()
        matches = [path for path in self._paths if (not source or self._records[path]["source"] == source)
                   and all(term in (path + " " + self._records[path]["title"]).casefold() for term in terms)]
        return dict(available=self.available, message=self.message, total=len(matches), limit=limit, offset=offset,
                    drawings=[self._records[path].copy() for path in matches[offset:offset + limit]])

    def _require_available(self):
        if not self.available:
            raise DrawingError(503, self.message)

    def metadata(self, path):
        self._require_available()
        if not isinstance(path, str) or path not in self._records:
            raise DrawingError(404, "Drawing was not found in the available library.")
        return self._records[path].copy()

    @contextmanager
    def open_file(self, path):
        self._require_available()
        if not isinstance(path, str) or path not in self._files:
            raise DrawingError(404, "File was not found in the available library.")
        info = self._files[path]
        # ZipExtFile uses the shared ZipFile read lock; names never become local disk paths.
        with self._archive.open(info) as stream:
            yield stream, info.file_size, CONTENT_TYPES[Path(path).suffix]

    def read_bytes(self, path):
        with self.open_file(path) as (stream, _, _):
            return stream.read()

    def details(self, path):
        drawing = self.metadata(path)
        geometry = None
        if drawing["kind"] == "swiss":
            with self._swiss_lock:
                if path in self._swiss_cache:
                    geometry = self._swiss_cache[path]
                    self._swiss_cache.move_to_end(path)
                else:
                    dxf = path[:-4] + ".dxf"
                    with tempfile.TemporaryDirectory() as directory:
                        local = Path(directory) / Path(dxf).name
                        local.write_bytes(self.read_bytes(dxf))
                        try:
                            geometry = extract_rooms(local)
                        except (ValueError, KeyError, IndexError) as exc:
                            raise DrawingError(422, "No supported Swiss room geometry could be extracted from this DXF.") from exc
                    geometry["sheet"].update(pdfUrl=drawing["fileUrl"], dxfUrl=drawing["dxfUrl"])
                    self._swiss_cache[path] = geometry
                    if len(self._swiss_cache) > 8:
                        self._swiss_cache.popitem(last=False)
        return dict(drawing=drawing, geometry=geometry)

    def ifc_answer(self, path, question):
        drawing = self.metadata(path)
        if drawing["kind"] != "ifc":
            raise DrawingError(422, "Select a raw IFC model for this reader.")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise DrawingError(400, "Supply a question of 1–2,000 characters.")
        from . import ifc_takeoff
        # Parse at most one file at a time. A single model can be 85 MB on disk.
        with self._ifc_lock:
            if self._ifc_key != path:
                self._ifc_key = self._ifc_model = None
                try:
                    self._ifc_model = ifc_takeoff.build_model(self.read_bytes(path), title=drawing.get('attribution', {}).get('work'))
                except (ValueError, IndexError, KeyError, RecursionError) as exc:
                    raise DrawingError(422, "This IFC model could not be read.") from exc
                self._ifc_key = path
            result = ifc_takeoff.answer(self._ifc_model, question)
        return dict(drawing=drawing, result=result)
