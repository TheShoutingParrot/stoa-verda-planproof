"""Evaluate the native IFC reader on every English IFC Models question backed by a raw model."""

import argparse
import gzip
import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from ifc_takeoff import answer, build_model, catalog_titles


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / ".local/evaluation/swiss-frontier/inputs/junction-dataset.zip"
OUTPUT = ROOT / ".local/evaluation/ifc-takeoff"
PREFIX = "junction-dataset/"


def run(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    all_rows = []
    with zipfile.ZipFile(archive) as bundle:
        question_crc = f"{bundle.getinfo(PREFIX + 'questions.jsonl').CRC:08x}"
        for line in bundle.open(PREFIX + "questions.jsonl"):
            row = json.loads(line)
            if (row["path"].startswith("data/ifc_models/") and row["path"].endswith(".ifc")
                    and row["question"].startswith(("How ", "What "))):
                grouped[row["path"]].append(row)
        titles = catalog_titles(bundle.read(PREFIX + "data/ifc_models/LICENSE.md"))
        for path, rows in sorted(grouped.items()):
            model = build_model(bundle.read(PREFIX + path), title=titles[Path(path).name])
            for row in rows:
                prediction = answer(model, row["question"])
                evidence = prediction["evidence"]
                unit = "m2" if row["unit"] in {"m2","m²"} else row["unit"]
                correct = prediction["status"] == "answered" and prediction["unit"] == unit and (
                    prediction["answer"] == row["answer"] if unit == "count"
                    else math.isclose(prediction["answer"], row["answer"], rel_tol=0,
                                      abs_tol=abs(row["answer"])*0.02))
                status = "correct" if correct else "wrong" if prediction["status"] == "answered" else "unsupported"
                all_rows.append({
                    "path":path,"question":row["question"],"gold":row["answer"],"unit":row["unit"],
                    "prediction":prediction["answer"],"status":status,"method":prediction["method"],
                    "reason":prediction["reason"],"schema":model.schema,"evidence_count":len(evidence),
                    "step_ids":[e["step_id"] for e in evidence],
                })
            print(f"{len(rows):3}  {path}", flush=True)
    counts = Counter(row["status"] for row in all_rows)
    by_unit, by_model = defaultdict(Counter), defaultdict(Counter)
    for r in all_rows:
        by_unit[r["unit"]][r["status"]] += 1
        by_model[r["path"]][r["status"]] += 1
    summary = {
        "reader_sha256":hashlib.sha256((ROOT/"scripts/ifc_takeoff.py").read_bytes()).hexdigest(),
        "benchmark_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source":"ifc_models","scope":"English questions whose drawing path is a raw .ifc file",
        "source_questions_crc32":question_crc,
        "models":len(grouped),"total":len(all_rows),"answered":counts["correct"]+counts["wrong"],
        "correct":counts["correct"],"wrong":counts["wrong"],"unsupported":counts["unsupported"],
        "by_unit":dict(by_unit),"by_model":dict(by_model),
    }
    with gzip.open(destination / "rows.jsonl.gz", "wt", encoding="utf-8") as output:
        for row in all_rows:
            output.write(json.dumps(row,ensure_ascii=False)+"\n")
    (destination / "summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k != "by_model"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    run(args.archive,args.output)
