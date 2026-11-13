"""Report committed CubiCasa inference outcomes and pending questions. Offline, one shot."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from zipfile import ZipFile

from benchmark_full_english import ARCHIVE, MANIFEST, ROOT
from benchmark_hosted_counts import population, WORK

STATES = ("correct", "wrong", "abstained", "service_unavailable", "unsupported", "error", "pending")


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 4) if denominator else None


def summarize(counts):
    values = {key: counts.get(key, 0) for key in STATES}
    total = sum(values.values())
    answered = values["correct"] + values["wrong"]
    scored = total - values["pending"]
    return dict(questions=total, completed=scored, answered=answered, **values,
                correct_pct_completed=percent(values["correct"], scored),
                answer_pct_all=percent(answered, total), correct_pct_answered=percent(values["correct"], answered),
                correct_pct_all_to_date=percent(values["correct"], total))


def snapshot(database):
    # Keep the transaction short: read only the numeric data needed for scoring.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        configs = conn.execute("SELECT value FROM config").fetchall()
        if len(configs) != 1:
            raise ValueError("Expected one hosted-run configuration")
        config = json.loads(configs[0][0])
        rows = list(conn.execute("""
          SELECT path, question, json_extract(report,'$.status'), json_extract(report,'$.answer'),
                 json_type(report,'$.answer'), json_extract(report,'$.timestamp'), json_extract(report,'$.latency_ms')
          FROM results
        """))
    return config, rows


def report(database, archive_path, baseline_path):
    baseline = json.loads(baseline_path.read_text())
    config, completed = snapshot(database)
    if baseline["question_file_sha256"] != MANIFEST or config["question_manifest_sha256"] != MANIFEST:
        raise ValueError("The full-English baseline and hosted checkpoint must match the frozen release")
    with ZipFile(archive_path) as archive:
        gold = population(archive)
    n = len(gold)
    replaced = baseline["by_route"]["hosted_image_count"]
    if replaced["questions"] != n or replaced["service_unavailable"] != n or config["population"] != n:
        raise ValueError("Expected the baseline hosted route to consist entirely of unconfigured requests")

    hosted = Counter(pending=n - len(completed))
    if hosted["pending"] < 0:
        raise ValueError("Checkpoint exceeds the frozen hosted population")
    first_start, last_finish, timed = None, None, 0
    for path, question, status, answer, answer_type, timestamp, latency in completed:
        expected = gold[path, question]
        if status == "answered":
            if answer_type != "integer" or answer < 0:
                raise ValueError("Invalid count in committed answered row")
            hosted["correct" if answer == expected else "wrong"] += 1
        elif status in ("unknown", "unavailable"):
            hosted["abstained" if status == "unknown" else "service_unavailable"] += 1
        else:
            raise ValueError(f"Unrecognized prediction status {status!r}")
        if timestamp and latency is not None:
            start = datetime.fromisoformat(timestamp)
            if start.tzinfo is None or latency < 0:
                raise ValueError("Invalid timing in checkpoint")
            end = start + timedelta(milliseconds=latency)
            first_start = min(first_start, start) if first_start else start
            last_finish = max(last_finish, end) if last_finish else end
            timed += 1

    sources = {}
    combined = Counter()
    for source, base in baseline["by_source"].items():
        counts = Counter({k: base.get(k, 0) for k in STATES})
        if source == "cubicasa5k":
            counts["service_unavailable"] -= n
            counts.update(hosted)
        if min(counts.values()) < 0 or sum(counts.values()) != base["questions"]:
            raise ValueError(f"Question totals do not reconcile for {source}")
        sources[source] = summarize(counts)
        combined.update(counts)

    stamp = datetime.now(timezone.utc)
    elapsed = (last_finish - first_start).total_seconds() if first_start else None
    rate = round(60 * timed / elapsed, 3) if timed >= 2 and elapsed and elapsed > 0 else None
    return {
        "as_of_utc": stamp.isoformat(timespec="seconds"), "complete": hosted["pending"] == 0,
        "model": config["model"], "provider_host": config["provider_host"], "release_sha256": MANIFEST,
        "checkpoint": str(database.resolve()), "hosted": summarize(hosted),
        "overall": summarize(combined), "by_source": sources,
        "observed_timing": {
            "timed_committed_rows": timed, "first_request_start_utc": first_start.isoformat() if first_start else None,
            "latest_estimated_finish_utc": last_finish.isoformat() if last_finish else None,
            "elapsed_seconds": round(elapsed, 3) if elapsed is not None else None, "rows_per_minute": rate,
        },
    }


def markdown(data):
    host, overall = data["hosted"], data["overall"]
    description = "Complete" if data["complete"] else "In progress"
    lines = [
        "# Hosted CubiCasa count benchmark", "",
        f"{description} as of {data['as_of_utc']}. {data['model']} on {data['provider_host']}.", "",
        f"The checkpoint contains **{host['completed']:,} / {host['questions']:,}** hosted questions. "
        f"**{host['pending']:,} remain pending**. Of the committed questions, {host['answered']:,} received "
        f"an integer and {host['correct']:,} matched the sponsor answer exactly.", "",
        "## Full English release", "",
        "| Source | Questions | Correct | Wrong | Abstained | Unavailable | Unsupported | Errors | Pending |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in [*data["by_source"].items(), ("**All sources**", overall)]:
        lines.append("| " + name + " | " + " | ".join(f"{row[k]:,}" for k in ("questions", *STATES)) + " |")
    prec = overall["correct_pct_answered"]
    precision = f"{prec:.2f}%" if prec is not None else "unavailable"
    lines += ["", f"Answers so far cover **{overall['answer_pct_all']:.2f}%** of the English release. "
              f"Accuracy among those answers is **{precision}**. Verified correct answers so far represent "
              f"**{overall['correct_pct_all_to_date']:.2f}%** of the entire release.", "",
              "Pending includes questions without a committed result, including in-flight requests. "
              "The baseline's unconfigured hosted rows are replaced by this live checkpoint. "
              "The other routes retain their baseline results."]
    timing = data["observed_timing"]
    if timing["rows_per_minute"] is not None:
        lines += ["", f"Across {timing['timed_committed_rows']:,} timed, committed rows, the observed rate was "
                  f"**{timing['rows_per_minute']:.2f} rows/min** over {timing['elapsed_seconds'] / 60:.1f} minutes "
                  "from the earliest recorded request start to the latest estimated completion. "
                  "This window may include pauses between runs."]
    return "\n".join(lines) + "\n"


def write_atomic(path, content):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as f:
        f.write(content)
    Path(f.name).replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=WORK / "checkpoint.sqlite3")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--baseline", type=Path, default=ROOT / "docs/full-english-results.json")
    parser.add_argument("--out", type=Path, default=WORK)
    args = parser.parse_args()
    progress = report(args.checkpoint, args.archive, args.baseline)
    args.out.mkdir(exist_ok=True, parents=True)
    write_atomic(args.out / "progress.json", json.dumps(progress, ensure_ascii=False, indent=2) + "\n")
    write_atomic(args.out / "progress.md", markdown(progress))
    row = progress["hosted"]
    print(f"{row['completed']:,}/{row['questions']:,} committed; {row['pending']:,} pending. "
          f"Reports: {args.out / 'progress.md'} and {args.out / 'progress.json'}")


if __name__ == "__main__":
    main()
