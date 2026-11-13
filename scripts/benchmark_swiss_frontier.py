"""Score the original, fresh and complete Swiss Dwellings English question sets."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from benchmark_swiss import ROOT, FROZEN, partition, sha, compact_json

DEFAULT = ROOT / ".local/evaluation/swiss-frontier"
SPLIT = ROOT / "docs/swiss-frontier-split.json"
SWISS = "junction-dataset/data/swiss_dwellings/"
OTHER_SOURCES = ["cubicasa5k", "ifc_models", "ifc_bench", "opening_design", "finna",
                 "habs", "wikimedia", "europeana", "swiss_dwellings"]


def read_json(path):
    return json.loads(path.read_bytes())


def start_word_is_english(source, question):
    word = question.split(maxsplit=1)[0].lower()
    if source == "ifc_bench":
        return word in {"what", "which", "could", "how", "are", "is", "can", "where",
                        "give", "does", "list", "identify"}
    if source == "opening_design":
        return word == "on"
    return word in {"how", "what"}


def source_questions(raw):
    inventory = {k: {"all": 0, "english": 0, "englishSheets": set()} for k in OTHER_SOURCES}
    swiss = defaultdict(list)
    for line in raw.splitlines():
        row = json.loads(line)
        source = row["path"].split("/")[1]
        counts = inventory[source]
        counts["all"] += 1
        if not start_word_is_english(source, row["question"]):
            continue
        counts["english"] += 1
        counts["englishSheets"].add(row["path"])
        if source == "swiss_dwellings":
            question = row["question"]
            family, target = partition(question)
            if family == "object_count":
                target = question.split()[2].lower()
            if family == "apartment_area":
                target = re.search(r"\bapartment (.+?) in m²", question)[1]
            swiss[Path(row["path"]).stem].append(dict(
                question=question, family=family, target=target, unit=row["unit"], gold=row["answer"]))
    for counts in inventory.values():
        counts["englishSheets"] = len(counts["englishSheets"])
    return dict(swiss), inventory


def validated_source(archive, manifest, split, work):
    with zipfile.ZipFile(archive) as zf:
        files = {Path(e.filename).stem: e for e in zf.infolist()
                 if e.filename.startswith(SWISS) and e.filename.endswith(".dxf")}
        raw = zf.read(manifest["questionsMember"])
        if sha(raw) != manifest["questionsMemberSha256"]:
            raise ValueError("Full question file differs from frozen sponsor data")
        groups, inventory = source_questions(raw)
        if set(groups) != set(files):
            raise ValueError("Drawing stems and labelled PDF stems differ")
        excluded = set(split["previewSites"]) | set(split["additionalExcludedSites"])
        excluded.update(s["stem"].split("_")[0] for s in manifest["sites"])
        eligible = [s for s in files if s.split("_")[0] not in excluded]
        selected = {}
        for stem in sorted(eligible, key=lambda s: sha((split["seed"] + "|" + s).encode())):
            selected.setdefault(stem.split("_")[0], stem)
        if split["eligibleSheets"] != len(eligible) or list(selected.values())[:120] != split["fresh"]:
            raise ValueError("Fresh selection no longer reproduces from the archive")
        prior = [item["stem"] for item in manifest["sites"]]
        rows = [{"sheet": s, "question": r["question"], "answer": r["gold"], "unit": r["unit"]}
                for s in prior for r in groups[s]]
        if sha(compact_json(rows)) != manifest["englishRowsSha256"]:
            raise ValueError("Original paired questions differ")
        drawings = work / "inputs/drawings"
        drawings.mkdir(exist_ok=True, parents=True)
        for stem, entry in files.items():
            path = drawings / (stem + ".dxf")
            contents = zf.read(entry)  # zipfile verifies original member CRC32
            if not path.exists() or path.read_bytes() != contents:
                temporary = path.with_suffix(f".{os.getpid()}.tmp")
                temporary.write_bytes(contents)
                temporary.replace(path)
    return groups, inventory, drawings, {"original60": prior, "fresh120": split["fresh"], "all": sorted(groups)}


def snapshot(work, revision="working"):
    paths = ["public/app.js", "scripts/extract_rooms.py"]
    if revision == "working":
        paths += sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").glob("swiss_*.py"))
        payload = {p: (ROOT / p).read_bytes() for p in paths}
    else:
        paths += subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision,
                                          "--", "scripts/"], cwd=ROOT, text=True).splitlines()
        paths = [p for p in dict.fromkeys(paths) if p in ("public/app.js","scripts/extract_rooms.py")
                 or re.fullmatch(r"scripts/swiss_.*[.]py", p)]
        payload = {p: subprocess.check_output(["git", "show", revision + ":" + p], cwd=ROOT) for p in paths}
    # Apply identical independent form/evidence instrumentation to both product revisions.
    payload["scripts/benchmark_swiss.cjs"] = (ROOT / "scripts/benchmark_swiss.cjs").read_bytes()
    hashes = {path: sha(data) for path, data in sorted(payload.items())}
    path = work / "versions" / sha(compact_json(hashes))[:16]
    path.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        (path / Path(name).name).write_bytes(data)
    return path, hashes


def load_module(version):
    # Leave the snapshot importable for the extractor's lazy Swiss helper imports.
    if str(version) not in sys.path:
        sys.path.insert(0, str(version))
    spec = importlib.util.spec_from_file_location("frontier_extractor", version / "extract_rooms.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def predict_chunk(params):
    draws, version, work, cache_key, items = params
    module = load_module(version)
    result = []
    inputs = []
    position = []
    for stem, questions in items:
        cached = work / "extracted" / cache_key / (stem + ".json.gz")
        error = None
        try:
            if cached.exists():
                with gzip.open(cached, "rb") as f:
                    sheet = json.load(f)
            else:
                sheet = module.extract_rooms(draws / (stem + ".dxf"))
                cached.parent.mkdir(parents=True, exist_ok=True)
                temporary = cached.with_suffix(f".{os.getpid()}.tmp")
                with gzip.open(temporary, "wb", compresslevel=1) as f:
                    f.write(compact_json(sheet))
                temporary.replace(cached)
            inputs.append({"sheet": sheet, "questions": questions})
            position.append((stem, len(questions)))
        except (ValueError, KeyError, OSError, UnicodeError, IndexError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        result.append((stem, {"error": error}))
    outputs = dict(result)
    if inputs:
        run = subprocess.run(["node", str(version / "benchmark_swiss.cjs"), str(version / "app.js")],
                             input=compact_json(inputs), stdout=subprocess.PIPE, check=True)
        rows = iter(json.loads(run.stdout))
        for stem, count in position:
            outputs[stem]["predictions"] = [next(rows) for _ in range(count)]
        if next(rows, None) is not None:
            raise RuntimeError("Unmatched form responses")
    return outputs


def has_location(entity, key):
    center = entity.get("center")
    geom = entity.get(key)
    return bool(geom and center and len(center) == 2 and all(math.isfinite(x) for x in center))


def source_scope(row, output, sheet):
    """Map requested intent to source drawing marks, independently of the form."""
    kind, target = row["family"], row["target"]
    rooms = sheet["rooms"]
    objects = sheet.get("objects", {})
    units = sheet.get("apartments", [])
    scope = output.get("scope") or {}
    metric = "count" if row["unit"] == "count" else "area"
    if output["metric"] != metric:
        return False, False
    if kind in ("label_count", "label_area"):
        scoped = not scope and output["selection"] == target and output["roomId"] is None
        evidence = [r["id"] for r in rooms if r["label"] == target and has_location(r, "polygon")]
    elif kind == "room_area":
        scoped = not scope and output["roomId"] == target
        evidence = [r["id"] for r in rooms if r.get("numbered") and r["id"] == target and has_location(r, "polygon")]
        scoped = scoped and len(evidence) == 1
    elif kind == "object_count":
        scoped = scope.get("kind") == kind and scope.get("target") == target and target in objects
        evidence = [r["id"] for r in objects.get(target, []) if has_location(r, "lines")]
    elif kind == "apartment_count":
        scoped = scope.get("kind") == kind and "apartments" in sheet
        evidence = ["unit:" + u["id"] for u in units if u.get("polygon")]
    elif kind == "apartment_area":
        unit = next((u for u in units if u["id"] == target), None)
        scoped = scope.get("kind") == kind and scope.get("target") == target and unit is not None
        evidence = unit.get("roomIds", []) if unit else []
    elif kind == "floor_area":
        scoped = scope.get("kind") == kind and "indoorRoomIds" in sheet
        evidence = sheet.get("indoorRoomIds", [])
    else:
        raise ValueError(kind)
    returned = output.get("evidence", [])
    expected = set(evidence)
    linked = len(returned) == len(expected) and len(evidence) == len(expected) and set(returned) == expected
    if metric == "count":
        linked = linked and output["value"] == len(expected)
    else:
        areas = [r["area"] for r in rooms if r["id"] in expected and has_location(r, "polygon")]
        linked = linked and bool(areas) and len(areas) == len(expected) and abs(sum(areas) - output["value"]) <= .00501
    return scoped, linked


def score(stem, rows, sheet, result):
    for row, out in zip(rows, result.get("predictions", [{}] * len(rows)), strict=True):
        pred = out.get("value")
        numeric = False
        scoped = linked = False
        if pred is not None and result["error"] is None:
            gold = row["gold"]
            numeric = pred == gold if row["unit"] == "count" else abs(pred - gold) <= abs(gold) * .02
            scoped, linked = source_scope(row, out, sheet)
        state = ("extraction_error" if result["error"] else "abstained" if pred is None else
                 "wrong_scope" if not scoped else "wrong_evidence" if not linked else
                 "wrong_value" if not numeric else "correct")
        yield {**row, "stem": stem, "answer": pred, "scopeOK": scoped, "evidenceOK": linked,
               "numericOK": numeric, "status": state, "evidence": out.get("evidence", [])}


def breakdown(rows):
    counts = Counter(r["status"] for r in rows)
    return dict(rows=len(rows), answered=sum(r["answer"] is not None for r in rows),
                correct=counts["correct"], numeric=sum(r["numericOK"] for r in rows),
                wrongScope=counts["wrong_scope"], wrongEvidence=counts["wrong_evidence"],
                wrongValue=counts["wrong_value"], abstained=counts["abstained"],
                extractionError=counts["extraction_error"])


def summarize(selected, allrows):
    chosen = set(selected)
    rows = [r for r in allrows if r["stem"] in chosen]
    cat = defaultdict(list)
    for row in rows:
        cat[row["family"]].append(row)
        if row["family"] == "object_count":
            cat["object_count/" + row["target"]].append(row)
    return {"sheets": len(chosen), "total": breakdown(rows),
            "missExamples": [
                {"family": family, **{k: missed[k] for k in ("stem", "target", "status", "answer", "gold")}}
                for family, group in sorted(cat.items()) if "/" not in family
                if (missed := next((r for r in group if r["status"] != "correct"), None))
            ],
            "byFamily": {k: breakdown(group) for k, group in sorted(cat.items())},
            "byUnit": {u: breakdown([r for r in rows if r["unit"] == u]) for u in ("count", "m2")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT)
    parser.add_argument("--archive", type=Path, help="Path to the full official ZIP")
    parser.add_argument("--split", choices=["all", "original60", "fresh120"], default="all")
    parser.add_argument("--revision", default="working", help="Git revision to evaluate, or working")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    manifest = read_json(FROZEN)
    archive = args.archive or work / "inputs/junction-dataset.zip"
    if args.jobs < 1 or args.batch < 1:
        parser.error("--jobs and --batch must be positive")
    if not archive.exists():
        raise SystemExit(f"Download the full sponsor ZIP to {archive} first. Source: {manifest['source']}")
    groups, inventory, drawings, splits = validated_source(archive, manifest, read_json(SPLIT), work)
    version, hashes = snapshot(work, args.revision)
    extract_key = sha(compact_json({k: v for k, v in hashes.items() if k.endswith(".py")}))[:16]
    selected = splits[args.split]
    run_dir = version / args.split
    run_dir.mkdir(exist_ok=True)
    print(f"Running {args.split}: {len(selected)} sheets; snapshot {version.name}", flush=True)
    # Only the public question text crosses into the extraction/form subprocesses.
    qs = [(stem, [r["question"] for r in groups[stem]]) for stem in selected]
    chunks = [(drawings, version, work, extract_key, qs[i:i+args.batch]) for i in range(0, len(qs), args.batch)]
    predictions = {}
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for i, found in enumerate(pool.map(predict_chunk, chunks), 1):
            predictions.update(found)
            if i % 10 == 0:
                print(f"  completed {len(predictions)} / {len(qs)} sheets", flush=True)
    allrows = []
    for stem in selected:
        result = predictions[stem]
        if result["error"]:
            sheet = {}
        else:
            with gzip.open(work / "extracted" / extract_key / (stem + ".json.gz"), "rb") as f:
                sheet = json.load(f)
        allrows.extend(score(stem, groups[stem], sheet, result))
    with gzip.open(run_dir / "rows.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in allrows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    results = {k: summarize(s, allrows) for k, s in splits.items() if set(s) <= set(selected)}
    result = {"hashes": hashes, "questionFile": manifest["questionsMemberSha256"], "inventory": inventory,
              "splits": results, "ingestionFailures": {s: r["error"] for s,r in predictions.items() if r["error"]}}
    (run_dir / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for name, stats in results.items():
        print(f"{name}: {stats['total']}")
        for family, item in stats['byFamily'].items():
            print(f"  {family}: {item['correct']}/{item['rows']}, answered {item['answered']}")
        for miss in stats["missExamples"]:
            print("  miss:", miss)
    print(f"  per-row misses: {run_dir / 'rows.jsonl.gz'}\n  summary: {run_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
