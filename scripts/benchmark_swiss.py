"""Paired, fixed-input evaluation of Swiss DXF extraction and the room question form."""

import argparse
from collections import Counter
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "docs/swiss-benchmark-inputs.json"
BASE = "32b2941"
APP = "public/app.js"
EXTRACTOR = "scripts/extract_rooms.py"
DIRECT_ROOM = re.compile(r"^What is the net floor area of room (.+?) \('(.*)'\) in m²\?$")
COUNT_LABEL = re.compile(r"^How many rooms labelled '(.*)' are there on this floor\?$")
SUM_LABEL = re.compile(r"^What is the total net area in m² of all rooms labelled '(.*)' on this floor\?$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compact_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


class RangeReader(io.RawIOBase):
    """Read-only seekable HTTP ZIP stream. Each read downloads only the requested range."""
    def __init__(self, url):
        self.url = url
        headers = subprocess.check_output(["curl", "-fsSI", url]).decode()
        self.size = int(re.search(r"^content-length:\s*(\d+)", headers, re.I | re.M)[1])
        self.pos = 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = (0, self.pos, self.size)[whence] + offset
        if self.pos < 0:
            raise OSError("Negative seek")
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b""
        data = subprocess.check_output(["curl", "-fsSL", "--retry", "2", "-r",
                                       f"{self.pos}-{self.pos+n-1}", self.url])
        if len(data) != n:
            raise OSError("Server returned an unexpected byte range")
        self.pos += n
        return data


def fetch_inputs(cache, manifest):
    drawings = cache / "drawings"
    drawings.mkdir(parents=True, exist_ok=True)
    files = {manifest["questionsMember"]: (cache / "questions.jsonl", manifest["questionsMemberSha256"])}
    for site in manifest["sites"]:
        name = site["stem"] + ".dxf"
        files["junction-dataset/data/swiss_dwellings/" + name] = (drawings / name, site["dxfSha256"])
    missing = [(member, path, checksum) for member, (path, checksum) in files.items()
               if not path.exists() or sha(path.read_bytes()) != checksum]
    if missing:
        remote = RangeReader(manifest["source"])
        with zipfile.ZipFile(remote) as zf:
            for member, path, checksum in missing:
                payload = zf.read(member)
                if sha(payload) != checksum:
                    raise ValueError(f"Frozen source changed: {member}")
                path.write_bytes(payload)
    return cache / "questions.jsonl", drawings


def partition(question):
    count = COUNT_LABEL.fullmatch(question)
    if count:
        return "label_count", count[1]
    area = SUM_LABEL.fullmatch(question)
    if area:
        return "label_area", area[1]
    lookup = DIRECT_ROOM.fullmatch(question)
    if lookup:
        return "room_area", lookup[1]
    if question.startswith("How many apartments"):
        return "apartment_count", None
    if question.startswith("How many "):
        return "object_count", None
    if question.startswith("What is the net floor area of apartment"):
        return "apartment_area", None
    if question.startswith("What is the total net floor area"):
        return "floor_area", None
    if question.startswith(("How ", "What ", "Which ")):
        raise ValueError(f"Unclassified English question: {question}")
    return None, None


def questions_by_sheet(path, manifest):
    groups = {site["stem"]: [] for site in manifest["sites"]}
    for line in path.read_bytes().splitlines():
        if b"data/swiss_dwellings/" not in line:
            continue
        row = json.loads(line)
        stem = Path(row["path"]).stem
        if stem not in groups:
            continue
        kind, target = partition(row["question"])
        if kind:
            groups[stem].append({"sheet": stem, "question": row["question"], "answer": row["answer"],
                                 "unit": row["unit"], "family": kind, "target": target})
    identity = [{key: row[key] for key in ("sheet", "question", "answer", "unit")}
                for rows in groups.values() for row in rows]
    if len(identity) != 1080 or sha(compact_json(identity)) != manifest["englishRowsSha256"]:
        raise ValueError("The question and answer set differs from the frozen 1,080 English rows")
    return groups


def snapshot(work, version, path):
    if version == "working":
        data = (ROOT / path).read_bytes()
    else:
        data = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{version}:{path}"])
    out = work / ("candidate" if version == "working" else "baseline") / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def percentiles(values):
    if not values:
        return {}
    return {"median": round(statistics.median(values), 4),
            "p95": round(statistics.quantiles(values, n=20, method="inclusive")[18], 4)}


def evaluate(work, version, drawings, groups):
    app = snapshot(work, version, APP)
    extractor = snapshot(work, version, EXTRACTOR)
    if version == "working":
        for sibling in (ROOT / "scripts").glob("swiss_*.py"):
            (extractor.parent / sibling.name).write_bytes(sibling.read_bytes())
    sys.path.insert(0, str(extractor.parent))
    try:
        module_spec = importlib.util.spec_from_file_location("benchmark_extractor", extractor)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        inputs, times = [], []
        for stem, rows in groups.items():
            started = time.perf_counter()
            sheet = module.extract_rooms(drawings / (stem + ".dxf"))
            times.append(1000 * (time.perf_counter() - started))
            inputs.append({"sheet": sheet, "questions": [r["question"] for r in rows]})
    finally:
        sys.path.pop(0)
    task = subprocess.run(["node", str(ROOT / "scripts/benchmark_swiss.cjs"), str(app)],
                          input=compact_json(inputs), stdout=subprocess.PIPE, check=True)
    outputs = json.loads(task.stdout)
    return outputs, {"appSha256": sha(app.read_bytes()), "extractorSha256": sha(extractor.read_bytes()),
                     "extractionMs": percentiles(times),
                     "formMs": percentiles([out["elapsedMs"] for out in outputs])}


def score(row, output):
    value = output["value"]
    if value is None:
        return {"answered": False, "numeric": False, "intent": False}
    expected, kind, target = row["answer"], row["family"], row["target"]
    good_value = value == expected if row["unit"] == "count" else abs(value - expected) <= abs(expected) * .02
    metric = output["metric"]
    if kind in ("label_area", "label_count"):
        scope = output["roomId"] is None and output["selection"] == target and metric == ("count" if kind == "label_count" else "area")
    elif kind == "room_area":
        scope = output["roomId"] == target and output["evidence"] == [target] and metric == "area"
    else:
        scope = False
    return {"answered": True, "numeric": good_value, "intent": scope and good_value}


def tally(pairs, version):
    def counts(rows):
        return dict(rows=len(rows), answered=sum(r[version]["answered"] for r in rows),
                    numeric=sum(r[version]["numeric"] for r in rows),
                    intent=sum(r[version]["intent"] for r in rows))
    return {"all": counts(pairs), "byFamily": {f: counts([r for r in pairs if r["family"] == f])
                                               for f in sorted({r["family"] for r in pairs})},
            "byUnit": {u: counts([r for r in pairs if r["unit"] == u]) for u in ("count", "m2")}}


def transitions(pairs):
    totals = Counter()
    for row in pairs:
        before, after = row["baseline"], row["current"]
        if before["intent"] and after["intent"]:
            totals["retainedCorrect"] += 1
        elif after["intent"]:
            totals["improved"] += 1
        elif before["intent"]:
            totals["regressed"] += 1
        else:
            totals["stillIncorrectOrUnanswered"] += 1
        if before["value"] != after["value"]:
            totals["changedDisplayedValue"] += 1
    return {field: totals[field] for field in (
        "retainedCorrect", "improved", "regressed", "stillIncorrectOrUnanswered", "changedDisplayedValue")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=ROOT / ".local/evaluation/swiss-paired")
    parser.add_argument("--cache", type=Path, help="Reusable directory with drawings/ and questions.jsonl")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(FROZEN.read_text())
    question_file, drawings = fetch_inputs(args.cache or args.work / "inputs", manifest)
    groups = questions_by_sheet(question_file, manifest)
    before, base_timing = evaluate(args.work, BASE, drawings, groups)
    after, current_timing = evaluate(args.work, "working", drawings, groups)
    pairs = []
    for row, old, new in zip((r for rows in groups.values() for r in rows), before, after, strict=True):
        base_score, new_score = score(row, old), score(row, new)
        pairs.append({**row, "baseline": {**old, **base_score}, "current": {**new, **new_score}})
    base = tally(pairs, "baseline")
    current = tally(pairs, "current")
    if (base["all"]["intent"], base["all"]["numeric"]) != (360, 367):
        raise ValueError(f"Baseline failed to replicate the frozen audit: {base['all']}")
    result = {"baselineCommit": BASE, "inputRowsSha256": manifest["englishRowsSha256"],
              "sheets": len(groups), "baseline": base, "current": current,
              "paired": transitions(pairs),
              "pairedByFamily": {f: transitions([r for r in pairs if r["family"] == f])
                                 for f in sorted({r["family"] for r in pairs})},
              "revisions": {"baseline": base_timing, "current": current_timing},
              "runtime": {"machine": platform.machine(), "python": platform.python_version(),
                          "node": subprocess.check_output(["node", "--version"], text=True).strip()}}
    (args.work / "pairs.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=2) + "\n")
    (args.work / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
