"""Run a blinded image-only Codex model on the 60 frozen Swiss sheets and score its answers."""

import argparse
import concurrent.futures
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import zipfile

from benchmark_swiss import FROZEN, ROOT, RangeReader, questions_by_sheet

PROMPT = (
    "Inspect the attached public Swiss architectural floor plan. Answer every numbered question "
    "from the image alone. Use no tools, files, outside information or code. A count must be an "
    "integer; areas are in square metres. Use null when the drawing is insufficient. Return the "
    "numbers in the exact question order, with one entry per question.\n"
)
SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {"type": ["number", "null"]}}},
    "required": ["answers"],
    "additionalProperties": False,
}


def fingerprint(blob):
    return hashlib.sha256(blob).hexdigest()


def predict(stem, questions, image, model, cache):
    prompt = PROMPT + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    identity = {
        "model": model,
        "effort": "medium",
        "image_sha256": fingerprint(image.read_bytes()),
        "prompt_sha256": fingerprint(prompt.encode()),
        "schema": SCHEMA,
    }
    output = cache / (stem + ".json")
    if output.exists():
        existing = json.loads(output.read_text())
        if existing["identity"] == identity:
            return existing
    with tempfile.TemporaryDirectory(prefix="planproof-blind-") as directory:
        cwd = Path(directory)
        attachment, schema, response = (
            cwd / filename for filename in ("drawing.png", "format.json", "answer.json")
        )
        attachment.write_bytes(image.read_bytes())
        schema.write_text(json.dumps(SCHEMA))
        cmd = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "-c",
            'model_reasoning_effort="medium"',
            "-c",
            "features.shell_tool=false",
            "--model",
            model,
            "--image",
            str(attachment),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(response),
            "--json",
            "-",
        ]
        start = time.monotonic()
        proc = subprocess.run(
            cmd, input=prompt, text=True, cwd=cwd, capture_output=True, timeout=480
        )
        events = [json.loads(s) for s in proc.stdout.splitlines() if s.startswith("{")]
        if proc.returncode or not response.exists():
            raise RuntimeError(
                str(
                    [
                        e.get("message") or e.get("error")
                        for e in events
                        if e.get("type") in ("error", "turn.failed")
                    ]
                )[-900:]
                + "\n"
                + proc.stderr[-450:]
            )
        used_tools = [
            e
            for e in events
            if e.get("item", {}).get("type")
            not in (None, "agent_message", "reasoning", "plan")
        ]
        if used_tools:
            raise RuntimeError(
                "Model used a tool. This sheet cannot enter the image-only comparison."
            )
        answers = json.loads(response.read_text())["answers"]
        if len(answers) != len(questions) or any(
            n is not None and (type(n) not in (float, int) or not math.isfinite(n))
            for n in answers
        ):
            raise ValueError(f"Unexpected answer vector for {stem}")
        result = {
            "identity": identity,
            "answers": answers,
            "seconds": round(time.monotonic() - start, 2),
            "usage": next(
                (e.get("usage") for e in events if e.get("type") == "turn.completed"),
                None,
            ),
        }
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2) + "\n")
    temp.replace(output)
    return result


def score(answers, errors, groups, sheets, model):
    families = {}
    usage = Counter()
    total = Counter()
    predictions = {}
    for stem in sheets:
        result = answers.get(stem)
        if result:
            usage.update(result["usage"] or {})
            # Store predictions and inputs' fingerprints so a third party can verify the
            # score with only the public questions, without a second inference call.
            predictions[stem] = {
                key: result[key] for key in ("answers", "seconds", "usage")
            }
            predictions[stem].update(
                {
                    key: result["identity"][key]
                    for key in ("image_sha256", "prompt_sha256")
                }
            )
        for i, row in enumerate(groups[stem]):
            answer = result["answers"][i] if result else None
            ok = answer is not None and (
                answer == row["answer"]
                if row["unit"] == "count"
                else abs(answer - row["answer"]) <= abs(row["answer"]) * 0.02
            )
            stats = dict(questions=1, answered=int(answer is not None), correct=int(ok))
            total.update(stats)
            families.setdefault(row["family"], Counter()).update(stats)
    return {
        "model": model,
        "effort": "medium",
        "cli": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "sheets_requested": len(sheets),
        "sheets_completed": len(answers),
        "errors": errors,
        "numeric": total,
        "families": families,
        "usage": usage,
        "median_seconds_per_sheet": statistics.median(
            r["seconds"] for r in answers.values()
        )
        if answers
        else None,
        "prompt": PROMPT,
        "output_schema": SCHEMA,
        "predictions": predictions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument(
        "--archive", type=Path, help="Optional local copy of junction-dataset.zip"
    )
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/evaluation/vision")
    parser.add_argument(
        "--published-results",
        type=Path,
        help="Write a complete, shareable result with frozen predictions",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 60 or args.jobs < 1:
        parser.error("Use 1–60 sheets and a positive number of workers")
    manifest = json.loads(FROZEN.read_text())
    images = args.cache / "images"
    outputs = args.cache / args.model
    for folder in (images, outputs):
        folder.mkdir(parents=True, exist_ok=True)
    question_file = args.cache / "questions.jsonl"
    sheets = [s["stem"] for s in manifest["sites"][: args.limit]]
    missing = [stem for stem in sheets if not (images / (stem + ".png")).exists()]
    if missing or not question_file.exists():
        with zipfile.ZipFile(
            args.archive or RangeReader(manifest["source"])
        ) as archive:
            if not question_file.exists():
                question_file.write_bytes(archive.read(manifest["questionsMember"]))
            for stem in missing:
                (images / (stem + ".png")).write_bytes(
                    archive.read(
                        "junction-dataset/data/swiss_dwellings/" + stem + ".png"
                    )
                )
    groups = questions_by_sheet(question_file, manifest)
    answers = {}
    errors = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                predict,
                stem,
                [r["question"] for r in groups[stem]],
                images / (stem + ".png"),
                args.model,
                outputs,
            ): stem
            for stem in sheets
        }
        for future in concurrent.futures.as_completed(futures):
            stem = futures[future]
            try:
                answers[stem] = future.result()
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                errors[stem] = str(exc)
            print(
                f"{len(answers)} sheets answered, {len(errors)} failed; {stem}: "
                + errors.get(stem, "ok"),
                flush=True,
            )
    report = score(answers, errors, groups, sheets, args.model)
    (outputs / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.published_results:
        if errors or len(sheets) != 60:
            raise ValueError("Publish only the complete 60-site run")
        args.published_results.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["numeric"]))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
