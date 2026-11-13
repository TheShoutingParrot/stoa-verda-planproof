"""Audit PlanProof's input compatibility for IFC Models, IFC Bench and Opening Design.

Usage: python3 scripts/benchmark_non_swiss_cad.py --archive /path/to/junction-dataset.zip
The audit needs only the Python standard library. It never calls a model provider.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from zipfile import ZipFile

import nemotron
from extract_rooms import extract_rooms

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / ".local/evaluation/swiss-frontier/inputs/junction-dataset.zip"
DEFAULT_OUTPUT = ROOT / ".local/evaluation/full-english/non-swiss-cad"
PREFIX = "junction-dataset/"
SOURCES = ("ifc_models", "ifc_bench", "opening_design")
EXTENSIONS = (".dxf", ".dwg", ".ifc", ".svg", ".png", ".jpg", ".jpeg", ".pdf")
APP_FILES = ("scripts/extract_rooms.py", "scripts/nemotron.py", "public/app.js", "public/scan.js", "server.py")


class DocumentBytes:
    """Use the real scan entrypoint while reading each original document only once."""
    def __init__(self, path, data):
        self.name = PurePosixPath(path).name
        self.data = data

    def read_bytes(self):
        return self.data


def deny_network(*args, **kwargs):
    raise AssertionError("This audit cannot send a drawing to an inference endpoint")


def english_questions(raw):
    groups = defaultdict(list)
    for index, line in enumerate(raw.splitlines()):
        row = json.loads(line)
        source = PurePosixPath(row["path"]).parts[1]
        if source not in SOURCES:
            continue
        # The released IFC Models questions alternate translated and English
        # templates. All its English templates begin with What or How. The
        # IFC Bench and Opening Design question files are entirely English.
        if source == "ifc_models" and row["question"].split()[0] not in ("What", "How"):
            continue
        groups[row["path"]].append((index, row))
    return groups


def companions(name, members):
    path = PurePosixPath(name)
    stem = name[:-len(path.suffix)]
    parent = stem.split("_plan-", 1)[0] + ".ifc" if "_plan-" in stem else None
    return {
        "exactStemOtherFormats": [ext for ext in EXTENSIONS if ext != path.suffix and stem + ext in members],
        "ifcParent": parent if parent in members else None,
        "rasterPlan": stem + "_plan.png" if stem + "_plan.png" in members else None,
    }


def probe_dxf(archive, member, groups, temp_dir):
    path = temp_dir / PurePosixPath(member).name
    data = archive.read(PREFIX + member)
    path.write_bytes(data)
    result = {"source": PurePosixPath(member).parts[1], "file": member, "labeled": member in groups}
    try:
        result["outputRooms"] = len(extract_rooms(path)["rooms"])
    except (OSError, UnicodeError, ValueError, KeyError, IndexError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    # Group code 8 names the layer an entity uses. A byte-safe diagnostic also
    # reports the layers of drawings rejected before the extractor reads them.
    lines = data.decode("latin-1").splitlines()
    layers = {value.strip() for code, value in zip(lines[::2], lines[1::2]) if code.strip() == "8"}
    result.update(drawingLayerCount=len(layers), hasSwissRoomLayer="ROOM_OUTLINE" in layers,
                  hasSwissTextLayer="ROOM_TEXT" in layers, exampleLayers=sorted(layers)[:7])
    return result


def route_document(archive, name, entries, related, app_source):
    path = PurePosixPath(name)
    source = path.parts[1]
    data = archive.read(PREFIX + name)
    media = DocumentBytes(name, data)
    header = "PDF" if data.startswith(b"%PDF") else "IFC" if data.startswith(b"ISO-10303-21") else "unknown"
    if path.stem in app_source or ".dxf" in related["exactStemOtherFormats"] or path.suffix == ".dxf":
        raise RuntimeError(f"New candidate for the Swiss drawing workflow: {name}. Reevaluate its actual answers.")
    if header == "unknown":
        raise RuntimeError(f"Unexpected document signature: {name}")
    for index, row in entries:
        result = nemotron.run(media, row["question"], "https://benchmark.invalid/v1", "offline-media-guard",
                              None, opener=deny_network)
        if result["status"] != "unavailable" or "PNG or JPEG" not in result.get("reason", ""):
            raise RuntimeError(f"Scan entrypoint changed for {name}: {result}")
        yield {"index": index, "source": source, "file": name, "question": row["question"],
               "type": row["type"], "header": header, "scope": "no supported source route",
               "swiss": "not_catalogued/no_matching_DXF", "scan": result["reason"], "goldUsedForRouting": False}


def summarize(source, members, rows, by_document):
    docs = {row["file"] for row in rows}
    return {
        "english": len(rows), "labeledFiles": len(docs),
        "archiveFormats": Counter(PurePosixPath(name).suffix for name in members if PurePosixPath(name).parts[1] == source),
        "questionDocumentFormats": Counter(PurePosixPath(row["file"]).suffix for row in rows),
        "documentKindsAtGuard": Counter(row["header"] for row in rows),
        "questionTypes": Counter(row["type"] for row in rows),
        "matchingDXF": sum(".dxf" in by_document[name]["exactStemOtherFormats"] for name in docs),
        "matchingSVG": sum(".svg" in by_document[name]["exactStemOtherFormats"] for name in docs),
        "matchingRasterPlan": sum(by_document[name]["rasterPlan"] is not None for name in docs),
        "parentIFC": sum(by_document[name]["ifcParent"] is not None for name in docs),
        "eligible": 0, "unavailable": len(rows), "externalRequests": 0, "example": rows[0],
    }


def run(archive_path, output):
    output.mkdir(parents=True, exist_ok=True)
    app_source = (ROOT / "public/app.js").read_text()
    # Fail closed if the app gains another document reader. The score concerns
    # the Swiss catalog and the scan endpoint bound to its fixed Finnish sample.
    server = (ROOT / "server.py").read_text()
    if not re.search(r"run\(SAMPLE,\s*QUESTION,", server) or "sheetFiles" not in app_source:
        raise RuntimeError("The product entrypoints have changed; review source dispatch before reporting coverage")
    with ZipFile(archive_path) as archive:
        members = {name[len(PREFIX):] for name in archive.namelist() if name.startswith(PREFIX + "data/")}
        raw = archive.read(PREFIX + "questions.jsonl")
        groups = english_questions(raw)
        related = {name: companions(name, members) for name in sorted(groups)}
        dxfs = sorted(name for name in members if PurePosixPath(name).parts[1] in SOURCES and name.lower().endswith(".dxf"))
        with tempfile.TemporaryDirectory(dir=output) as temp:
            dxf_checks = [probe_dxf(archive, name, groups, Path(temp)) for name in dxfs]
        rows = [r for name, entries in sorted(groups.items())
                for r in route_document(archive, name, entries, related[name], app_source)]
    summary = {
        "sources": {source: summarize(source, members, [r for r in rows if r["source"] == source], related)
                    for source in SOURCES},
        "eligible": 0, "unavailable": len(rows), "archive": archive_path.name,
        "archiveQuestionFileSha256": hashlib.sha256(raw).hexdigest(),
        "codeHashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in APP_FILES},
        "dxfPreflight": dxf_checks,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "companions.json").write_text(json.dumps(related, indent=2) + "\n", encoding="utf-8")
    with gzip.open(output / "routes.jsonl.gz", "wt", encoding="utf-8") as fp:
        for row in sorted(rows, key=lambda r: r["index"]):
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="Original full Junction dataset ZIP")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="Audit output directory")
    args = parser.parse_args()
    result = run(args.archive, args.out)
    for source, stats in result["sources"].items():
        print(f"{source}: {stats['english']} English questions, {stats['eligible']} eligible")
