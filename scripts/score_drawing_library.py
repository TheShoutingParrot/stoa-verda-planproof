"""Join the frozen 2026-11-13 English drawing-library evaluation without model calls.

Supply baseline rows from the full-English benchmark, the working Swiss rerun, native
IFC results, and the stopped 1,560-question hosted export. See --help for paths.
The output directory holds a compact scorecard plus auditable per-question records.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

from benchmark_full_english import ARCHIVE, BEDROOM, MANIFEST, OTHER_SOURCES, ROOT, read_questions, write_line
from nemotron import MODEL, parse_count

WORK = ROOT / ".local/evaluation"
ARCHIVE_HASH = "506dddc7537d992bc6797c9617e9b747c754d28406f181f2b23887b01a231692"
HOSTED_EXPORT_HASH = "0f48227e9b81a854b2eef6b5045412b8a98500f5e8697ca96d687b2cfd8ebaf6"
STATES = ("correct", "wrong", "unknown", "unsupported", "unrun", "service_unavailable", "error")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_rows(path, swiss=False):
    rows, h = {}, hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for line in stream:
            h.update(line)
            r = json.loads(line)
            drawing = "data/swiss_dwellings/" + r["stem"] + ".pdf" if swiss else r["path"]
            key = (drawing, r["question"])
            require(key not in rows, f"Duplicate result in {path.name}: {key}")
            rows[key] = r
    return rows, h.hexdigest()


def score(value, ref, valid=True):
    if ref["type"] == "count":
        require(type(value) is int and value >= 0, "Invalid count")
        numeric = value == ref["answer"]
    else:
        require(ref["type"] in {"area", "length", "volume"}, "Unexpected answer type")
        actual, gold = Decimal(str(value)), Decimal(str(ref["answer"]))
        require(actual.is_finite() and gold.is_finite(), "Nonfinite measurement")
        numeric = abs(actual - gold) <= abs(gold) * Decimal(".02")
    return "correct" if numeric and valid else "wrong"


def measure(counts):
    total = sum(counts.values())
    answered = counts["correct"] + counts["wrong"]
    return dict(questions=total, answered=answered, **{s: counts[s] for s in STATES},
                correct_pct_all=round(100 * counts["correct"] / total, 3) if total else None,
                correct_pct_answered=round(100 * counts["correct"] / answered, 3) if answered else None)


def require_gold(row, ref):
    require(row["gold"] == ref["answer"] and row.get("unit", ref["unit"]) == ref["unit"],
            "Prediction gold or units differ from the original manifest")


def scan(row, ref, zf, hashes, hosted):
    path = ref["path"]
    if path not in hashes:
        hashes[path] = hashlib.sha256(zf.read("junction-dataset/" + path)).hexdigest()
    require(row["image_sha256"] == hashes[path], "Drawing fingerprint mismatch")
    status, value = row["status"], row.get("answer") if hosted else row["prediction"]
    evidence = row.get("evidence", [])
    if hosted:
        require(row["image"] == Path(path).name and row["model"] == MODEL
                and row["provider_host"] == "integrate.api.nvidia.com"
                and row["coordinate_system"] == "xyxy_top_left_0_to_1000", "Unexpected hosted provider or input")
    elif status in {"correct", "wrong", "abstained"}:
        status = "unknown" if status == "abstained" else "answered"
    if status in {"answered", "unknown"}:
        checked = parse_count(json.dumps(dict(status=status, answer=value, evidence=evidence)))
        require(checked["answer"] == value and len(checked["evidence"]) == len(evidence), "Malformed scan evidence")
        result = score(value, ref) if status == "answered" else "unknown"
    else:
        require(value is None and not evidence and status in {"unavailable", "error"}, "Invalid scan status")
        result = "service_unavailable" if status == "unavailable" else "error"
    require((row["correct"] == (result == "correct")) if hosted
            else row["status"] == {"unknown": "abstained"}.get(result, result), "Scan score mismatch")
    record = dict(status=result, prediction=value, route="hosted_image_count" if hosted else "local_bedroom_labels",
                  evidence=evidence, image_sha256=hashes[path])
    for key in ("model", "served_model", "reason", "detail"):
        if key in row:
            record[key] = row[key]
    return record


def swiss(row, ref):
    value, ids = row["answer"], row["evidence"]
    if value is not None:
        require(isinstance(ids, list) and len(ids) == len(set(ids))
                and all(isinstance(i, str) and i for i in ids) and (ids or value == 0), "Missing Swiss evidence IDs")
        require(type(row["scopeOK"]) is bool and type(row["evidenceOK"]) is bool, "Missing Swiss scope/evidence checks")
        status = score(value, ref, row["scopeOK"] and row["evidenceOK"])
        require(row["numericOK"] == (score(value, ref) == "correct") and
                (status == "correct") == (row["status"] == "correct"), "Swiss score mismatch")
    else:
        status = {"abstained": "unknown", "extraction_error": "error"}[row["status"]]
    return dict(status=status, prediction=value, route="swiss_dxf", evidence=ids,
                scope_ok=row["scopeOK"], evidence_ok=row["evidenceOK"])


def ifc(row, ref, declarations):
    value, ids = row["prediction"], row["step_ids"]
    require(len(ids) == row["evidence_count"] == len(set(ids))
            and all(type(i) is int and i in declarations for i in ids), "IFC evidence lacks distinct native STEP IDs")
    if value is not None:
        require((len(ids) == value if ref["type"] == "count" else bool(ids))
                and row["method"], "Missing IFC count or area evidence")
        status = score(value, ref)
    else:
        require(not ids and row["reason"], "Unexplained IFC abstention")
        status = "unsupported"
    require(status == row["status"], "Native IFC score mismatch")
    return dict(status=status, prediction=value, route="native_ifc", evidence=ids, method=row["method"], reason=row["reason"])


def run(args):
    require(digest(args.archive) == ARCHIVE_HASH, "Unexpected release archive SHA-256")
    base, baseline_hash = load_rows(args.baseline)
    sw, swiss_hash = load_rows(args.swiss_dir / "rows.jsonl.gz", swiss=True)
    native, ifc_hash = load_rows(args.ifc_dir / "rows.jsonl.gz")
    live, hosted_hash = load_rows(args.hosted)
    require(hosted_hash == HOSTED_EXPORT_HASH and len(live) == 1560, "This scorecard requires the stopped hosted export")
    swiss_summary = json.loads((args.swiss_dir / "summary.json").read_text())
    ifc_summary = json.loads((args.ifc_dir / "summary.json").read_text())
    require(swiss_summary["questionFile"] == MANIFEST, "Swiss source manifest mismatch")
    ifc_reader_hash = digest(ROOT / "scripts/ifc_takeoff.py")
    ifc_benchmark_hash = digest(ROOT / "scripts/benchmark_ifc_takeoff.py")
    require(ifc_summary["reader_sha256"] == ifc_reader_hash and ifc_summary["benchmark_sha256"] == ifc_benchmark_hash,
            "IFC results differ from the current reader or benchmark implementation")
    for name, expected in swiss_summary["hashes"].items():
        require(digest(ROOT / name) == expected, f"Swiss snapshot differs from {name}")
    args.output.mkdir(parents=True, exist_ok=True)
    temp = args.output / "rows.jsonl.gz.partial"
    by_source = {s: Counter() for s in OTHER_SOURCES}
    by_route, source_drawings, by_model = defaultdict(Counter), defaultdict(set), Counter()
    hashes, hosted_drawings = {}, set()
    with ZipFile(args.archive) as zf:
        release = read_questions(zf)
        require(len(release) == 64132 and release.keys() == base.keys(), "Baseline lacks exact full release coverage")
        swiss_keys = {k for k in release if k[0].startswith("data/swiss_dwellings/")}
        ifc_keys = {k for k in release if k[0].startswith("data/ifc_models/") and k[0].endswith(".ifc")}
        hosted_keys = {k for k in release if k[0].startswith("data/cubicasa5k/") and k[1] != BEDROOM}
        require(sw.keys() == swiss_keys and len(sw) == 18792 and native.keys() == ifc_keys and len(native) == 352
                and live.keys() <= hosted_keys and len(hosted_keys) == 39797, "Overlay routing or coverage mismatch")
        with gzip.open(temp, "wt", encoding="utf-8") as out:
            # Source-path order also permits checking IFC IDs without retaining 15 whole models' indices.
            current_ifc = None
            declarations = set()
            for key in sorted(release):
                path, question = key
                source = path.split("/")[1]
                ref, old = release[key], base[key]
                require_gold(old, ref)
                require(source == old["source"] and ref["type"] == old["type"], "Baseline source/type mismatch")
                if key in swiss_keys:
                    require(old["route"] == "swiss_dxf", "Unexpected old Swiss route")
                    require_gold(sw[key], ref)
                    record = swiss(sw[key], ref)
                elif key in ifc_keys:
                    require(old["route"] == "document_input" and old["status"] == "unsupported", "Unexpected old IFC route")
                    if current_ifc != path:
                        raw = zf.read("junction-dataset/" + path)
                        declarations = {int(m[1]) for m in re.finditer(rb"(?m)^\s*#\s*(\d+)\s*=", raw)}
                        del raw
                        current_ifc = path
                    require_gold(native[key], ref)
                    record = ifc(native[key], ref, declarations)
                elif key in hosted_keys:
                    require(old["route"] == "hosted_image_count" and old["status"] == "service_unavailable"
                            and old["prediction"] is None, "Unexpected old hosted route")
                    if key in live:
                        require_gold(live[key], ref)
                        record = scan(live[key], ref, zf, hashes, hosted=True)
                        require(record["image_sha256"] == old["image_sha256"], "Hosted baseline drawing changed")
                        hosted_drawings.add(path)
                        by_model[live[key]["served_model"]] += 1
                    else:
                        record = dict(status="unrun", prediction=None, route="hosted_image_count")
                elif source == "cubicasa5k":
                    require(question == BEDROOM and old["route"] == "local_bedroom_labels", "Unexpected local route")
                    record = scan(old, ref, zf, hashes, hosted=False)
                else:
                    require(old["route"] == "document_input" and old["status"] == "unsupported"
                            and old["prediction"] is None, "Unexpected retained document route")
                    record = dict(status="unsupported", prediction=None, route="document_input")
                by_source[source][record["status"]] += 1
                by_route[record["route"]][record["status"]] += 1
                source_drawings[source].add(path)
                write_line(out, dict(path=path, question=question, source=source, type=ref["type"], unit=ref["unit"],
                                     gold=ref["answer"], **record))
    totals = sum(by_source.values(), Counter())
    require(by_route["native_ifc"]["correct"] == ifc_summary["correct"]
            and sum(by_route["native_ifc"].values()) == ifc_summary["total"]
            and by_route["swiss_dxf"]["correct"] == swiss_summary["splits"]["all"]["total"]["correct"],
            "Per-route summary disagrees with joined records")
    report = dict(
        observed_date="2026-11-13", scope="Released English questions; development evaluation, including previously inspected drawings.",
        drawing_paths=sum(map(len, source_drawings.values())), overall=measure(totals),
        by_source={s: dict(drawing_paths=len(source_drawings[s]), **measure(counts)) for s, counts in by_source.items()},
        by_route={r: measure(counts) for r, counts in sorted(by_route.items())},
        stopped_hosted=dict(completed=len(live), eligible=len(hosted_keys), image_paths=len(hosted_drawings),
                            requested_model=MODEL, returned_model_ids=dict(by_model)),
        evidence_checks=[
            "Swiss scores require the assessed form scope, evidence scope and numeric agreement.",
            "Native IFC evidence IDs must resolve in the original model; count evidence must be distinct and match the returned count.",
            "Scan answers require the hash of the original image and one valid normalized box per counted item. Box semantics were not independently annotated.",
            "The 1,560 hosted completions are a stopped partial run, not a representative random sample. Other eligible hosted rows are unrun.",
            "Unknown combines reader abstention, invalid model evidence and truncated model output. Unsupported identifies quantities or files the available routes cannot resolve.",
        ],
        inputs=dict(archive_sha256=ARCHIVE_HASH, questions_sha256=MANIFEST, baseline_rows_sha256=baseline_hash,
                    swiss_rows_sha256=swiss_hash, swiss_code_sha256=swiss_summary["hashes"],
                    ifc_rows_sha256=ifc_hash, ifc_reader_sha256=ifc_reader_hash,
                    ifc_benchmark_sha256=ifc_benchmark_hash,
                    hosted_rows_sha256=hosted_hash),
        reproduction={
            "baseline": "Use the original full-English per-question rows from the offline pass documented in docs/full-english.md.",
            "swiss": "python3 scripts/benchmark_swiss_frontier.py --archive PATH_TO_RELEASE --revision working --split all --jobs 4",
            "ifc": "python3 scripts/benchmark_ifc_takeoff.py --archive PATH_TO_RELEASE",
            "hosted": "Use the archived stopped export or rebuild it offline from its original 1,560-row checkpoint with python3 scripts/benchmark_hosted_counts.py --export --work PATH_TO_STOPPED_CHECKPOINT. Stochastic responses and an exact private checkpoint are not reproducible from the release ZIP alone.",
            "join": "python3 scripts/score_drawing_library.py --archive PATH_TO_RELEASE --baseline PATH_TO_BASELINE_ROWS --swiss-dir PATH_TO_SWISS_ALL --ifc-dir PATH_TO_IFC_OUTPUT --hosted PATH_TO_STOPPED_ROWS",
            "artifacts": "All row fingerprints hash decompressed JSONL bytes. The join writes summary.json and rows.jsonl.gz below .local/evaluation/drawing-library-2026-11-13/ by default.",
        },
    )
    temp.replace(args.output / "rows.jsonl.gz")
    summary = args.output / "summary.json"
    summary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["overall"], indent=2), summary, sep="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--baseline", type=Path, default=WORK / "full-english/rows.jsonl.gz")
    parser.add_argument("--swiss-dir", type=Path, default=WORK / "swiss-frontier/versions/98e85fea44e64770/all")
    parser.add_argument("--ifc-dir", type=Path, default=WORK / "ifc-takeoff")
    parser.add_argument("--hosted", type=Path, default=WORK / "hosted-cubicasa/hosted-rows.jsonl.gz")
    parser.add_argument("--output", type=Path, default=WORK / "drawing-library-2026-11-13")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
