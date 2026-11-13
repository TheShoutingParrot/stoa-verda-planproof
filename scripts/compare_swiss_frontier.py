"""Compare two saved full-corpus frontier runs on identical prompts, IDs and gold."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from benchmark_swiss import FROZEN
from benchmark_swiss_frontier import SPLIT, read_json


def load_run(folder):
    summary = read_json(folder / "summary.json")
    with gzip.open(folder / "rows.jsonl.gz", "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    return summary, rows


def paired_counts(before, current):
    counts = Counter()
    if len(before) != len(current):
        raise ValueError("Runs cover different numbers of rows")
    for a, b in zip(before, current, strict=True):
        if any(a[k] != b[k] for k in ("stem", "question", "gold", "unit", "family", "target")):
            raise ValueError("The paired source/target/gold differs between runs")
        left, right = a["status"] == "correct", b["status"] == "correct"
        if left:
            counts["retained" if right else "regressed"] += 1
        else:
            counts["gained" if right else "stillMissed"] += 1
    return {key: counts[key] for key in ("retained", "gained", "regressed", "stillMissed")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--numeric-original", type=Path, help="Write fixed 60-site numeric-only rows (local JSONL)")
    args = parser.parse_args()
    old, a = load_run(args.baseline)
    new, b = load_run(args.current)
    if old["questionFile"] != new["questionFile"] or old["inventory"] != new["inventory"]:
        raise ValueError("Different source corpora")
    splits = {"original60": {s["stem"] for s in read_json(FROZEN)["sites"]},
              "fresh120": set(read_json(SPLIT)["fresh"]), "all": {r["stem"] for r in a}}
    out = {"baselineHashes": old["hashes"], "currentHashes": new["hashes"],
           "questionFileSha256": new["questionFile"], "inventory": new["inventory"],
           "scoring": "A strict pass requires correct numeric value, scope and displayed source-linked evidence.",
           "splits": {}}
    for name, stems in splits.items():
        before = [r for r in a if r["stem"] in stems]
        current = [r for r in b if r["stem"] in stems]
        out["splits"][name] = {
            "sheets": len(stems), "baseline": old["splits"][name],
            "current": new["splits"][name], "paired": paired_counts(before, current),
        }
    if args.numeric_original:
        # Match the model runner's order: frozen manifest site order, then sponsor JSONL order.
        original_order = {s["stem"]: i for i, s in enumerate(read_json(FROZEN)["sites"])}
        chosen = [(left, right) for left, right in zip(a, b, strict=True) if left["stem"] in original_order]
        chosen.sort(key=lambda pair: original_order[pair[0]["stem"]])
        indexes = Counter()
        payload = []
        for left, right in chosen:
            stem, question = left["stem"], left["question"]
            indexes[stem] += 1
            key = hashlib.sha256((stem + "\0" + question).encode()).hexdigest()
            payload.append(dict(rowId=key, stem=stem, questionIndex=indexes[stem],
                                unit=left["unit"], family=left["family"], gold=left["gold"],
                                baselineValue=left["answer"], baselineNumeric=left["numericOK"],
                                currentValue=right["answer"], currentNumeric=right["numericOK"]))
        if len({r["rowId"] for r in payload}) != 1080:
            raise ValueError("Expected 1,080 distinct model-independent questions")
        args.numeric_original.parent.mkdir(parents=True, exist_ok=True)
        args.numeric_original.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in payload))
        print("Frozen numeric row file", args.numeric_original)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    for name, group in out["splits"].items():
        print(name, group["paired"])


if __name__ == "__main__":
    main()
