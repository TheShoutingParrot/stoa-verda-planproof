"""Score the released English Junction questions against the installed Planproof routes."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
from itertools import chain
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

import nemotron
from benchmark_swiss_frontier import ROOT, OTHER_SOURCES, start_word_is_english

WORK = ROOT / ".local/evaluation/full-english"
ARCHIVE = ROOT / ".local/evaluation/swiss-frontier/inputs/junction-dataset.zip"
BEDROOM = "How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?"
MEMBER = "junction-dataset/questions.jsonl"
MANIFEST = "0e6322c74561a63f42bac35f5c1be8a2c6a37516b14a81e66ab88b74950a6d1f"


def read_questions(zf):
    raw = zf.read(MEMBER)
    if hashlib.sha256(raw).hexdigest() != MANIFEST:
        raise ValueError("Question manifest differs from the benchmark release")
    rows = {}
    for line in raw.splitlines():
        row = json.loads(line)
        path, question = row["path"], row["question"]
        if start_word_is_english(path.split("/")[1], question):
            zf.getinfo("junction-dataset/" + path)
            key = (path, question)
            if key in rows:
                raise ValueError(f"Duplicate question on {path}")
            rows[key] = row
    return rows


def lines(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def write_line(stream, obj):
    stream.write(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")


def run_hosted_counts(zf, questions, work):
    # Evaluate the configuration that exists on this machine. A future configured
    # endpoint needs its own explicit run so replaying this benchmark stays local.
    base = os.environ.get("NEMOTRON_BASE_URL", "")
    api_key = os.environ.get("NEMOTRON_API_KEY", "")
    if base or api_key:
        raise RuntimeError("This pass reproduces the unconfigured hosted endpoint. Unset NEMOTRON_BASE_URL and NEMOTRON_API_KEY to replay it.")
    groups = defaultdict(list)
    for (path, question), row in questions.items():
        if path.startswith("data/cubicasa5k/") and question != BEDROOM:
            if row["unit"] != "count":
                raise ValueError("Unexpected non-count request on this route")
            groups[path].append(question)
    work.mkdir(parents=True, exist_ok=True)
    out = work / "hosted-rows.jsonl.gz"
    temp = out.with_suffix(".partial")
    with tempfile.TemporaryDirectory(dir=work) as scratch, gzip.open(temp, "wt", encoding="utf-8") as dest:
        image = Path(scratch) / "drawing.png"
        for path, prompts in groups.items():
            image.write_bytes(zf.read("junction-dataset/" + path))
            for question in prompts:
                report = nemotron.run(image, question, base, nemotron.MODEL, api_key)
                if report["status"] != "unavailable" or report["latency_ms"] is not None or "image_sha256" not in report:
                    raise ValueError(f"Unexpected hosted result for {path}")
                write_line(dest, dict(path=path, question=question, answer=report["answer"],
                                      status=report["status"], reason=report["reason"],
                                      image_sha256=report["image_sha256"]))
    temp.replace(out)
    print(f"Hosted count route: {sum(map(len, groups.values())):,} questions on {len(groups):,} images", flush=True)


STATES = ("correct", "wrong", "abstained", "service_unavailable", "unsupported", "error")


def check_fingerprints(hashes):
    for name, digest in hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Product changed since the route was evaluated: {name}")


def swiss_predictions(directory):
    summary = json.loads((directory / "summary.json").read_bytes())
    if summary["questionFile"] != MANIFEST:
        raise ValueError("Unexpected Swiss question manifest")
    check_fingerprints(summary["hashes"])
    for r in lines(directory / "rows.jsonl.gz"):
        status = r["status"]
        normalized = {
            "correct": "correct", "abstained": "abstained", "wrong_scope": "wrong",
            "wrong_evidence": "wrong", "wrong_value": "wrong", "extraction_error": "error",
        }[status]
        path = f"data/swiss_dwellings/{r['stem']}.pdf"
        yield dict(path=path, question=r["question"], prediction=r["answer"], status=normalized,
                   route="swiss_dxf", detail=status, evidence=r["evidence"], expected=r["gold"],
                   scope_ok=r["scopeOK"], evidence_ok=r["evidenceOK"])


def finnish_predictions(directory, questions):
    config = json.loads((directory / "config.json").read_bytes())
    summary = json.loads((directory / "summary.json").read_bytes())
    if config["questions_sha256"] != MANIFEST or config["question"] != BEDROOM or summary["remaining"] != 0:
        raise ValueError("Finnish bedroom pass is incomplete or uses different questions")
    check_fingerprints({"scripts/local_parse.py": config["local_parse_sha256"]})
    for r in lines(directory / "rows.jsonl"):
        path = r["path"]
        if r["status"] == "answered":
            nemotron.parse_count(json.dumps(r))
            if r["answer"] == 0:
                raise ValueError("Local bedroom label reader requires visible evidence for an answer")
            status = "correct" if r["answer"] == questions[(path, BEDROOM)]["answer"] else "wrong"
        else:
            status = {"unknown": "abstained", "unavailable": "error"}[r["status"]]
        yield dict(path=path, question=BEDROOM, prediction=r["answer"], status=status,
                   route="local_bedroom_labels", detail=r["method"], evidence=r["evidence"],
                   image_sha256=r["image_sha256"], expected=r["gold"])


def other_predictions(work, hosted_run, questions):
    summary = json.loads((work / "non-swiss-cad/summary.json").read_bytes())
    if summary["archiveQuestionFileSha256"] != MANIFEST:
        raise ValueError("Unexpected CAD audit manifest")
    check_fingerprints(summary["codeHashes"])
    for r in lines(work / "non-swiss-cad/routes.jsonl.gz"):
        if r["scope"] != "no supported source route" or r["scan"] != "Supply a PNG or JPEG drawing.":
            raise ValueError("Unexpected input routing result")
        yield dict(path=r["file"], question=r["question"], prediction=None,
                   status="unsupported", route="document_input", detail=r["scan"])
    # Reporting an authenticated run can include partial service coverage. Keep the
    # baseline reason for each question still waiting for its first completion.
    live = {}
    if hosted_run:
        for r in lines(hosted_run):
            key = (r["path"], r["question"])
            if key in live:
                raise ValueError(f"Duplicate hosted completion: {key}")
            live[key] = r
    for r in lines(work / "hosted-rows.jsonl.gz"):
        key = (r["path"], r["question"])
        if key in live:
            result = live.pop(key)
            if r["image_sha256"] != result["image_sha256"]:
                raise ValueError(f"Different image on hosted run: {key}")
            if result["status"] == "unavailable":
                validated = dict(answer=None, evidence=[], reason=result["reason"])
                status = "service_unavailable"
            else:
                validated = nemotron.parse_count(json.dumps(result))
                status = "abstained"
                if validated["answer"] is not None:
                    status = "correct" if validated["answer"] == questions[key]["answer"] else "wrong"
            value = validated["answer"]
            yield dict(path=r["path"], question=r["question"], prediction=value, status=status,
                       route="hosted_image_count", detail=validated.get("reason", result["status"]),
                       evidence=validated["evidence"], image_sha256=r["image_sha256"],
                       provider_host=result["provider_host"], model=result.get("served_model") or result["model"])
            continue
        if r["status"] != "unavailable" or r["answer"] is not None:
            raise ValueError("Unexpected inference service result")
        yield dict(path=r["path"], question=r["question"], prediction=None, status="service_unavailable",
                   route="hosted_image_count", detail=r["reason"], image_sha256=r["image_sha256"])
    if live:
        raise ValueError("Hosted completions exist outside the non-bedroom CubiCasa questions")


def percentage(count, denominator):
    return round(100 * count / denominator, 4) if denominator else None


def metrics(counts):
    total = sum(counts.values())
    answered = counts["correct"] + counts["wrong"]
    return dict(questions=total, answered=answered, **{s: counts[s] for s in STATES},
                correct_pct_all=percentage(counts["correct"], total), answer_pct=percentage(answered, total),
                correct_pct_answered=percentage(counts["correct"], answered))


def score_all(zf, questions, args):
    work = args.work
    if args.swiss_dir:
        swiss = args.swiss_dir
    else:
        directories = list((work / "swiss/versions").glob("*/all"))
        if len(directories) != 1:
            raise ValueError("Supply --swiss-dir pointing to the intended version's all/ directory")
        swiss = directories[0]
    seen = set()
    hashes = {}
    by_source = {s: Counter() for s in OTHER_SOURCES}
    by_type, by_route = defaultdict(Counter), defaultdict(Counter)
    drawings = defaultdict(set)
    predictions = chain(swiss_predictions(swiss), finnish_predictions(work / "finnish", questions),
                        other_predictions(work, args.hosted_rows, questions))
    out = work / "rows.jsonl.gz"
    temp = out.with_suffix(".partial")
    with gzip.open(temp, "wt", encoding="utf-8") as stream:
        for prediction in predictions:
            path, question = prediction["path"], prediction["question"]
            key = (path, question)
            if key in seen:
                raise ValueError(f"Duplicate prediction: {key}")
            seen.add(key)
            r = questions[key]
            gold, value, status = r["answer"], prediction["prediction"], prediction["status"]
            if prediction.pop("expected", gold) != gold:
                raise ValueError(f"Scorer used a different gold answer on {key}")
            if (value is not None) != (status in ("correct", "wrong")):
                raise ValueError(f"Inconsistent prediction: {key}")
            if value is not None:
                numeric_ok = value == gold
                if r["type"] in ("length", "area", "volume"):
                    number, target = Decimal(str(value)), Decimal(str(gold))
                    numeric_ok = abs(number - target) <= abs(target) * Decimal("0.02")
                correct = numeric_ok and prediction.get("scope_ok", True) and prediction.get("evidence_ok", True)
                if correct != (status == "correct"):
                    raise ValueError(f"Score disagrees on {key}")
            if "image_sha256" in prediction:
                if path not in hashes:
                    hashes[path] = hashlib.sha256(zf.read("junction-dataset/" + path)).hexdigest()
                if hashes[path] != prediction["image_sha256"]:
                    raise ValueError(f"An original image differs from inference input on {path}")
            source = path.split("/")[1]
            drawings[source].add(path)
            by_source[source][status] += 1
            by_type[r["type"]][status] += 1
            by_route[prediction["route"]][status] += 1
            write_line(stream, dict(**prediction, source=source, gold=gold, unit=r.get("unit"), type=r["type"]))
    if seen != questions.keys():
        raise ValueError(f"Missing {len(questions.keys() - seen)} English questions")
    temp.replace(out)
    total = sum(by_source.values(), Counter())
    summary = dict(
        archive_bytes=args.archive.stat().st_size, archive_members=len(zf.infolist()), question_file_sha256=MANIFEST,
        swiss_version=swiss.parent.name, local_scan=json.loads((work / "finnish/summary.json").read_bytes()),
        drawing_paths=sum(map(len, drawings.values())), overall=metrics(total),
        by_source={s: {**metrics(c), "drawing_paths": len(drawings[s])} for s, c in by_source.items()},
        by_type={k: metrics(v) for k, v in by_type.items()},
        by_route={k: metrics(v) for k, v in by_route.items()})
    summary_path = work / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["overall"], indent=2))
    print(summary_path, out, sep="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--hosted-rows", type=Path, help="Overlay saved image model completions on the offline baseline")
    parser.add_argument("--swiss-dir", type=Path, help="Swiss result directory containing all scored rows")
    parser.add_argument("action", choices=["hosted", "score"])
    args = parser.parse_args()
    with ZipFile(args.archive) as zf:
        questions = read_questions(zf)
        if args.action == "hosted":
            run_hosted_counts(zf, questions, args.work)
        else:
            score_all(zf, questions, args)


if __name__ == "__main__":
    main()
