"""Freeze and compare the local scan reader on previously unused official test drawings.

The run subcommand accepts only staged PNGs and public questions. Score requires
both arms to be sealed before opening the release questions and their answer values.
"""

import argparse
import ast
import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import nemotron
from benchmark_scan_holdout import (
    ARCHIVE,
    MANIFEST,
    PREFIX,
    ROOT,
    SPLITS,
    canonical,
    check,
    load_prompts,
    save,
    sha,
    stable,
    style,
)

BASE = "4d79ac0d2d62150f416f730ff5dbbf38486be208"
SEED = "planproof-scan-revision-2026-11-14-independent-v2"
WORK = ROOT / ".local/evaluation/scan-revision"
PREVIOUS = ROOT / "docs/scan-holdout-inputs.json"
FROZEN = ROOT / "docs/scan-revision-inputs.json"
SPLIT_DIR = ROOT / ".local/evaluation/scan-holdout"
ASSETS = ROOT / ".local/scan-dev/objects"
QUOTAS = {"high_quality": 24, "high_quality_architectural": 24}
GROUPS = {
    "objects": {"doors", "windows", "toilet bowls", "sinks"},
    "rooms": {"bedrooms", "saunas", "kitchens", "bathrooms", "separate WC rooms", "balconies"},
    "storeys": {"floors"},
}
FAMILIES = set.union(*GROUPS.values())
FINGERPRINT = "62781971de4e842eccf0070119d4721b183339bdc3f7dd07fd904d82e6b7d12c"
SOURCE_FINGERPRINTS = {
    "old": "592f2d2ffc3a80b78ac7d88e2616392485a692d16b1d46fce0ad922dea7780d8",
    "new": "9e5bc7772a72c25e7435f31d779913e73335a63a0c3b6f5239f47ccfb94de54d",
}


def freeze(archive, split_dir, previous, extra, out):
    history = json.loads(previous.read_text())
    excluded = set.union(
        {r["path"] for r in history["rows"]}, *map(set, history["excluded"].values()), set(extra)
    )
    splits = {}
    for name, digest in SPLITS.items():
        data = (split_dir / (name + ".txt")).read_bytes()
        check(sha(data) == digest, "Different official CubiCasa split.")
        splits[name] = {
            "data/cubicasa5k/" + path.strip("/").replace("/", "-") + ".png"
            for path in data.decode().splitlines()
        }
    check(not splits["test"] & (splits["train"] | splits["val"]), "Overlapping upstream split.")
    with ZipFile(archive) as z:
        public = load_prompts(z)
        pool = (set(public) & splits["test"]) - excluded
        picked = []
        for name, quota in QUOTAS.items():
            subset = sorted((p for p in pool if style(p) == name), key=lambda p: stable(SEED, p))
            check(len(subset) >= quota, "Not enough fresh drawings for " + name)
            picked.extend(subset[:quota])
        rows = []
        selected_hashes = set()
        for path in sorted(picked):
            digest = sha(z.read(PREFIX + path))
            check(digest not in selected_hashes, "Two holdout drawings have identical file content.")
            selected_hashes.add(digest)
            for category, question in sorted(public[path].items()):
                if category in FAMILIES:
                    rows.append(
                        dict(
                            id=stable(path, question)[:16],
                            path=path,
                            question=question,
                            style=style(path),
                            category=category,
                            image_sha256=digest,
                        )
                    )
        for path in sorted(excluded):
            if PREFIX + path in z.NameToInfo:
                check(
                    sha(z.read(PREFIX + path)) not in selected_hashes,
                    "An exposed PNG is present under another name.",
                )
    result = dict(
        seed=SEED,
        previous_manifest_sha256=sha(canonical(history)),
        extra_exclusions=sorted(extra),
        source_questions_sha256=MANIFEST,
        upstream_splits_sha256=SPLITS,
        eligible_by_style=dict(sorted(Counter(style(p) for p in pool).items())),
        styles=QUOTAS,
        images=len(picked),
        questions=len(rows),
        category_counts=dict(sorted(Counter(r["category"] for r in rows).items())),
        rows=rows,
    )
    if out.exists():
        check(result == json.loads(out.read_text()), "Existing frozen revision manifest differs.")
    else:
        save(out, result)
        out.chmod(0o444)
    return result


def prepare(manifest, archive, work):
    with ZipFile(archive) as z:
        drawing_dir = work / "inputs"
        drawing_dir.mkdir(parents=True, exist_ok=True)
        for path, expected in {r["path"]: r["image_sha256"] for r in manifest["rows"]}.items():
            dest = drawing_dir / Path(path).name
            if not dest.exists():
                dest.write_bytes(z.read(PREFIX + path))
                dest.chmod(0o444)
            check(sha(dest.read_bytes()) == expected, "Staged drawing mismatch.")
    return drawing_dir


def source_bytes(revision, name):
    if revision == "working":
        return (ROOT / name).read_bytes()
    return subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)


def snapshot(directory, revision, extras):
    """Copy the reader, imported product modules and any explicitly requested data assets."""
    dest = directory / "src"
    (dest / "scripts").mkdir(parents=True, exist_ok=True)
    (dest / "scripts/__init__.py").touch()
    pending = {"scripts/scan_reader.py", *extras}
    identity = {}
    while pending:
        name = pending.pop()
        check(Path(name).parts[0] == "scripts" and ".." not in Path(name).parts, "Invalid source path.")
        if name in identity:
            continue
        raw = source_bytes(revision, name)
        path = dest / name
        if path.exists():
            check(path.read_bytes() == raw, "Source changed since this arm was frozen: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        identity[name] = sha(raw)
        if name.endswith(".py"):
            for node in ast.walk(ast.parse(raw)):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level == 1:
                    deps = [node.module] if node.module else [item.name for item in node.names]
                elif node.module == "scripts":
                    deps = [item.name for item in node.names]
                elif (node.module or "").startswith("scripts."):
                    deps = [node.module.removeprefix("scripts.")]
                else:
                    continue
                pending.update("scripts/" + dep.replace(".", "/") + ".py" for dep in deps)
    return dest, dict(sorted(identity.items()))


def environment():
    packages = {}
    for name in ["torch", "numpy", "pillow", "opencv-python", "opencv-python-headless"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    tesseract = shutil.which("tesseract")
    try:
        tess = (
            subprocess.check_output([tesseract, "--version"], text=True).splitlines()[0]
            if tesseract
            else None
        )
    except subprocess.CalledProcessError:
        tess = None
    import torch

    return dict(
        python=platform.python_version(),
        system=platform.system(),
        macos=platform.mac_ver()[0],
        device="mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu",
        packages=packages,
        tesseract=tess,
    )


def read_arm(work, manifest, arm):
    root = work / arm
    config = json.loads((root / "config.json").read_text())
    rows = {}
    for q in manifest["rows"]:
        if q["id"] in rows:
            raise ValueError("Duplicate frozen ID.")
        path = root / "outputs" / (q["id"] + ".json")
        record = json.loads(path.read_text())
        check(
            record["id"] == q["id"]
            and record["question"] == q["question"]
            and record["image_sha256"] == q["image_sha256"],
            "Saved record has the wrong source identity.",
        )
        if record["status"] == "abstained":
            check(
                record["answer"] is None and record["evidence"] == [], "Abstention contains a numeric answer."
            )
        else:
            checked = nemotron.parse_count(json.dumps(record, allow_nan=False))
            check(
                (record["status"], record["answer"], record["evidence"])
                == (checked["status"], checked["answer"], checked["evidence"]),
                "Saved answer or evidence is invalid.",
            )
        rows[q["id"]] = record
    check(len(rows) == len(list((root / "outputs").glob("*.json"))), "Unexpected extra record.")
    seal = dict(
        config_sha256=sha(canonical(config)),
        predictions_sha256=sha(canonical(rows)),
        manifest_sha256=FINGERPRINT,
        rows=len(rows),
    )
    return rows, seal, config


def normalize(reader, report, question, digest, elapsed):
    if report.get("status") == "unavailable":
        check(report.get("answer") is None and not report.get("evidence"), "Malformed fallback.")
        return dict(
            status="abstained",
            answer=None,
            evidence=[],
            method=report.get("method", "offline_fallback"),
            reason=report.get("reason"),
            elapsed_ms=elapsed,
        )
    check(
        report.get("question", question) == question and report.get("image_sha256", digest) == digest,
        "Reader returned a different question or image.",
    )
    checked = reader.nemotron.parse_count(json.dumps(report, allow_nan=False))
    check(checked["status"] in ("answered", "unknown"), "Unexpected reader response.")
    return dict(**checked, method=report.get("method"), elapsed_ms=elapsed)


def run(args, manifest):
    check(sha(canonical(manifest)) == FINGERPRINT, "Changed holdout.")
    check(args.arm in ("old", "new"), "Specify --arm.")
    revision = BASE if args.arm == "old" else args.revision
    root = args.work / args.arm
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "outputs"
    dest.mkdir(exist_ok=True)
    with (root / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        package, files = snapshot(root, revision, args.source)
        check(
            sha(canonical(files)) == SOURCE_FINGERPRINTS[args.arm],
            "Inference source differs from the frozen arm.",
        )
        sys.path.insert(0, str(package))
        os.environ["PLANPROOF_CUBICASA_CODE"] = str((args.assets / "CubiCasa5k").resolve())
        os.environ["PLANPROOF_OBJECT_WEIGHTS"] = str((args.assets / "model_best_val_loss_var.pkl").resolve())
        reader = importlib.import_module("scripts.scan_reader")
        check(
            Path(reader.__file__).resolve() == (package / "scripts/scan_reader.py").resolve(),
            "The Python interpreter imported a reader outside the frozen snapshot.",
        )
        obj = reader.scan_objects
        check(obj.available(), "Specialist files/packages unavailable.")
        code, weights = obj._locations()
        model_files = {name: sha((code / name).read_bytes()) for name in obj.SOURCE_HASHES}
        with weights.open("rb") as f:
            weights_hash = hashlib.file_digest(f, "sha256").hexdigest()
        check(obj.SOURCE_HASHES == model_files and weights_hash == obj.WEIGHTS_HASH, "Model asset mismatch.")
        config = dict(
            source_sha256=files,
            revision=revision if revision != "working" else "content-addressed working files",
            manifest_sha256=FINGERPRINT,
            detector_source=model_files,
            weights_sha256=weights_hash,
            detector_revision=obj.REVISION,
            environment=environment(),
            network="disabled",
        )
        if (root / "config.json").exists():
            check(config == json.loads((root / "config.json").read_text()), "Arm configuration mismatch.")
        else:
            save(root / "config.json", config)
        elapsed_start = time.monotonic()
        with patch.object(reader.nemotron, "run", side_effect=AssertionError("Hosted calls forbidden.")):
            drawings = defaultdict(list)
            for q in manifest["rows"]:
                drawings[q["path"]].append(q)
            for index, (path, questions) in enumerate(drawings.items(), 1):
                image = args.work / "inputs" / Path(path).name
                digest = sha(image.read_bytes())
                for q in questions:
                    check(q["image_sha256"] == digest, "Staged source image mismatch.")
                    output = dest / (q["id"] + ".json")
                    if output.exists():
                        continue
                    started = time.monotonic()
                    report = reader.run(image, q["question"], "", reader.nemotron.MODEL, None)
                    result = normalize(
                        reader, report, q["question"], digest, round(1000 * (time.monotonic() - started))
                    )
                    save(output, dict(id=q["id"], question=q["question"], image_sha256=digest, **result))
                print(
                    f"{args.arm} drawing {index}/{len(drawings)}; {time.monotonic() - elapsed_start:.1f}s",
                    flush=True,
                )
        _, seal, _ = read_arm(args.work, manifest, args.arm)
        if (root / "seal.json").exists():
            check(seal == json.loads((root / "seal.json").read_text()), "Sealed results changed.")
        else:
            save(root / "seal.json", seal)
        print("Sealed", seal, flush=True)


def metrics(records, name):
    answered = [r for r in records if r[name]["status"] == "answered"]
    exact = sum(r[name]["correct"] for r in answered)
    return dict(
        questions=len(records),
        answered=len(answered),
        exact=exact,
        wrong=len(answered) - exact,
        abstained=len(records) - len(answered),
        accuracy=round(exact / len(records), 4),
        coverage=round(len(answered) / len(records), 4),
        accuracy_when_answered=round(exact / len(answered), 4) if answered else None,
    )


def paired_metrics(records):
    counts = Counter()
    for r in records:
        old, new = r["old"], r["new"]
        counts["gained_exact"] += new["correct"] and not old["correct"]
        counts["lost_exact"] += old["correct"] and not new["correct"]
        oa, na = old["status"] == "answered", new["status"] == "answered"
        counts["newly_answered"] += na and not oa
        counts["newly_answered_exact"] += new["correct"] and not oa
        counts["dropped_answers"] += oa and not na
        counts["both_answered"] += oa and na
        counts["both_abstained"] += not oa and not na
    common = [r for r in records if r["old"]["status"] == r["new"]["status"] == "answered"]
    absolute_error = {
        name: round(sum(abs(r[name]["answer"] - r["gold"]) for r in common) / len(common), 3)
        if common
        else None
        for name in ("old", "new")
    }
    return dict(
        old=metrics(records, "old"),
        new=metrics(records, "new"),
        paired=dict(counts),
        mean_absolute_error_on_both_answered=absolute_error,
    )


def clustered_interval(records, draws=10000):
    strata = defaultdict(lambda: defaultdict(list))
    for r in records:
        strata[r["style"]][r["path"]].append(int(r["new"]["correct"]) - int(r["old"]["correct"]))
    cohort = [[(sum(x), len(x)) for x in group.values()] for group in strata.values()]
    rng = random.Random(SEED + "-bootstrap")
    outcomes = []
    for _ in range(draws):
        replicate = [pair for stratum in cohort for pair in rng.choices(stratum, k=len(stratum))]
        delta, size = zip(*replicate)
        outcomes.append(100 * sum(delta) / sum(size))
    outcomes.sort()
    return [round(outcomes[int(draws * 0.025)], 2), round(outcomes[int(draws * 0.975) - 1], 2)]


def score(args, manifest):
    check(sha(canonical(manifest)) == FINGERPRINT, "Changed holdout.")
    arms = {}
    configs = {}
    seals = {}
    for name in ("old", "new"):
        # Read and rehash all outputs and configurations before touching the score labels.
        seal_file = args.work / name / "seal.json"
        check(seal_file.is_file(), "Missing sealed arm: " + name)
        rows, seal, config = read_arm(args.work, manifest, name)
        check(
            sha(canonical(config["source_sha256"])) == SOURCE_FINGERPRINTS[name],
            "Unexpected inference source.",
        )
        check(seal == json.loads(seal_file.read_text()), "Broken arm seal: " + name)
        arms[name], seals[name], configs[name] = rows, seal, config
    check(configs["old"]["revision"] == BASE, "Unexpected reference reader.")
    for label in (
        "weights_sha256",
        "detector_source",
        "detector_revision",
        "environment",
        "network",
        "manifest_sha256",
    ):
        check(configs["old"][label] == configs["new"][label], "Arm configuration differs: " + label)
    queries = {(r["path"], r["question"]) for r in manifest["rows"]}
    targets = {}
    with ZipFile(args.archive) as z:
        raw = z.read(PREFIX + "questions.jsonl")
        check(sha(raw) == MANIFEST, "Sponsor release mismatch.")
        for line in raw.splitlines():
            row = json.loads(line)
            key = row["path"], row["question"]
            if key in queries:
                check(
                    key not in targets and row["unit"] == "count" and type(row["answer"]) == int,
                    "Duplicate or non-count answer.",
                )
                targets[key] = row["answer"]
    check(queries == targets.keys(), "Missing score key.")
    records = []
    for q in manifest["rows"]:
        gold = targets[q["path"], q["question"]]
        record = dict(**q, gold=gold)
        for name in arms:
            r = arms[name][q["id"]]
            record[name] = dict(**r, correct=r["status"] == "answered" and r["answer"] == gold)
        records.append(record)
    out = dict(
        observed_date=datetime.now(timezone.utc).date().isoformat(),
        manifest_sha256=FINGERPRINT,
        scope="Original PNG and original English count question; offline local specialists only; hosted fallback unavailable.",
        metric="Exact numeric count. Strict product count/box schema enforced; object localization accuracy requires separate measurement.",
        drawings=manifest["images"],
        questions=len(records),
        seals=seals,
        configurations=configs,
        overall=paired_metrics(records),
        stratified_drawing_bootstrap_delta_accuracy_pp_95=clustered_interval(records),
        by_family={
            name: paired_metrics([r for r in records if r["category"] in group])
            for name, group in GROUPS.items()
        },
        by_category={c: paired_metrics([r for r in records if r["category"] == c]) for c in sorted(FAMILIES)},
        by_style={s: paired_metrics([r for r in records if r["style"] == s]) for s in QUOTAS},
        inference_seconds={
            name: round(sum(r[name]["elapsed_ms"] for r in records) / 1000, 2) for name in arms
        },
    )
    save(args.work / "paired-rows.json", records)
    save(args.work / "summary.json", out)
    if args.report:
        save(args.report, out)
    print(json.dumps(out["overall"], indent=2))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["freeze", "prepare", "run", "score"])
    p.add_argument("--archive", type=Path, default=ARCHIVE)
    p.add_argument("--manifest", type=Path, default=FROZEN)
    p.add_argument("--previous", type=Path, default=PREVIOUS)
    p.add_argument("--split-dir", type=Path, default=SPLIT_DIR)
    p.add_argument("--extra-exclusions", type=Path)
    p.add_argument("--work", type=Path, default=WORK)
    p.add_argument("--arm", choices=["old", "new"])
    p.add_argument("--assets", type=Path, default=ASSETS)
    p.add_argument("--report", type=Path, help="Optional output JSON for the completed score")
    p.add_argument("--revision", default="working")
    p.add_argument(
        "--source", action="append", default=[], help="Extra, non-imported predictor asset under scripts/"
    )
    a = p.parse_args()
    if a.action == "freeze":
        extra = json.loads(a.extra_exclusions.read_text()) if a.extra_exclusions else []
        m = freeze(a.archive, a.split_dir, a.previous, extra, a.manifest)
        print(m["images"], m["questions"], m["eligible_by_style"], m["category_counts"], sha(canonical(m)))
        return
    m = json.loads(a.manifest.read_text())
    if a.action == "prepare":
        print(prepare(m, a.archive, a.work))
    elif a.action == "run":
        run(a, m)
    else:
        score(a, m)


if __name__ == "__main__":
    main()
