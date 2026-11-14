"""Freeze, seal and score the scan-next before/after comparison on fresh official test drawings.

The order is fixed. audit and freeze use paths, styles and question text only. prepare stages
the frozen PNGs. run loads a reader from a Git snapshot, reads staged PNGs only and seals its
outputs. score, fetch-refs, localize and example refuse to start until both arms are sealed.
See docs/scan-next-protocol.md for the pre-registered analysis and the runbook.
"""

import argparse
import fcntl
import hashlib
import importlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from zipfile import ZipFile

import benchmark_scan_revision as revision
import score_scan_evidence as evidence
from benchmark_scan_holdout import (
    ARCHIVE,
    MANIFEST,
    NAMES,
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

BASE = "b948d6744548417b7a037f32b9317c830ea7e52e"
SEED = "planproof-scan-next-2026-11-14-evaluator-v1"
WORK = ROOT / ".local/evaluation/scan-next"
FROZEN = ROOT / "docs/scan-next-inputs.json"
RESERVED = ROOT / ".local/scan-next/reserved-test-drawings.txt"
HOLDOUT_MANIFEST = ROOT / "docs/scan-holdout-inputs.json"
REVISION_MANIFEST = revision.FROZEN
REVISION_EXTRA = revision.WORK / "extra-exclusions.json"
SPLIT_DIR = revision.SPLIT_DIR
ASSETS = revision.ASSETS
QUOTAS = {"high_quality": 12, "high_quality_architectural": 60}
FAMILIES = set(NAMES)
COMPARABLE = set(revision.FAMILIES)  # the eleven families of the 398-prompt comparison
GROUPS = {
    "objects": revision.GROUPS["objects"] | {"showers"},
    "rooms": set(revision.GROUPS["rooms"]),
    "storeys": set(revision.GROUPS["storeys"]),
}
TRACKS = {
    "track1_openings": {"doors", "windows"},
    "track2_deferred": GROUPS["rooms"] | GROUPS["storeys"] | {"showers"},
    "untouched_fixtures": {"toilet bowls", "sinks"},
}
BASELINE_ARMS = ("before", "before-repeat")
ARM_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# Pinned after the freeze and the first baseline snapshot (see docs/scan-next-protocol.md).
FINGERPRINT = "3c5be563d29d5e3b246e18b9e5e6f1edc3bb7a9c03b139042c911a753b45f1b0"
BASE_SOURCE_FINGERPRINT = None

# Exposure audit: roots searched for test-split drawing names and image hashes.
AUDIT_ROOTS = (
    ".local/scan-dev",
    ".local/scan-rooms-dev",
    ".local/scan-results",
    ".local/verification",
    ".local/evaluation",
    "public/data",
    "docs",
    "tests",
)
AUDIT_SKIP_DIRS = {"venv", ".git", "__pycache__"}
# Files that name test drawings because they list the whole split or release, not because a
# drawing was opened. Each is pinned by content so a later change is reported as exposure.
INVENTORIES = {
    ".local/evaluation/scan-holdout/test.txt": (SPLITS["test"], "official CubiCasa test-split list"),
    ".local/scan-dev/objects/source-splits.json": (
        "c19a435c8a675301b6707e94674cb453bbdca2cb12c993809581d7af75c092ff",
        "official split membership of every sponsor CubiCasa PNG",
    ),
    ".local/scan-dev/grounding/central": (
        "74a8cddeece51c2f268d79190b51b63b462819420e81faca4664fed914a9f4f8",
        "central directory of the public CubiCasa5K archive (member names only)",
    ),
    ".local/scan-dev/objects/release-tail": (
        "a26eea4e3a120b54d42f29c972a90859269193784e58340afafe4b7eafd01934",
        "tail of the sponsor ZIP (member names only)",
    ),
    ".local/evaluation/full-english/finnish/rows.jsonl": (
        "9f335286d61c8fb316e47c092cdec64791f1ee0ada5423e7c6f13c661313b69f",
        "release-wide bedroom-gate table written 2026-11-13, before both earlier manifests",
    ),
}
GATE_DIR = ".local/evaluation/full-english/finnish/gates"
GATE_REASON = (
    "automated release-wide bedroom gate, one file per drawing, written 2026-11-13 before both "
    "earlier manifests; the earlier freezes kept these drawings and excluded only the 35 model runs"
)
STEM = re.compile(rb"(colorful|high_quality_architectural|high_quality)(?:[-/_]|%2[Ff])(\d+)(?!\d)")
HEX64 = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
LARGE = 512 * 1024 * 1024

# Implementers' scratch directories scanned by the leak check in the later session.
SCRATCH = (ROOT / ".local/scan-next/openings", ROOT / ".local/scan-next/deferred")
EVALUATOR_FILES = {"docs/scan-next-inputs.json"}

# Public CubiCasa5K archive on Zenodo (record 2613548). Fetched only by fetch-refs.
ZENODO = "https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content"
CENTRAL = dict(
    offset=5466775714,
    size=2719894,
    sha256="74a8cddeece51c2f268d79190b51b63b462819420e81faca4664fed914a9f4f8",
    cache=ROOT / ".local/scan-dev/grounding/central",
)
REFERENCE_MEMBERS = (("model.svg", ".svg"), ("F1_scaled.png", "-scaled.png"), ("F1_original.png", "-original.png"))

# Published figures of the 48-drawing comparison (docs/scan-revision-*.md), used by validate.
PUBLISHED = {
    "old": dict(exact=156, wrong=78, abstained=164, answered=234),
    "new": dict(exact=167, wrong=73, abstained=158, answered=240),
    "paired": dict(gained_exact=15, lost_exact=4),
    "interval": [0.75, 4.87],
    "localization": {
        "windows": {"old": (330, 401, 458, 16), "new": (346, 373, 458, 20)},
        "doors": {"old": (261, 277, 323, 14), "new": (285, 303, 323, 16)},
        "toilet bowls": {"old": (53, 61, 67, 35), "new": (53, 61, 67, 35)},
        "sinks": {"old": (89, 106, 127, 24), "new": (89, 106, 127, 24)},
        "all": {"old": (733, 845, 975, 89), "new": (773, 843, 975, 95)},
    },
}


# ---------------------------------------------------------------------------------------------
# Pool, exposure audit and freeze (metadata only)


def read_splits(split_dir):
    splits = {}
    for name, digest in SPLITS.items():
        data = (split_dir / (name + ".txt")).read_bytes()
        check(sha(data) == digest, "Different official CubiCasa split: " + name)
        splits[name] = {
            "data/cubicasa5k/" + line.strip("/").replace("/", "-") + ".png" for line in data.decode().splitlines()
        }
    check(not splits["test"] & (splits["train"] | splits["val"]), "Overlapping upstream split.")
    return splits


def known_exposures(holdout, revision_manifest, extra):
    """Groups (a), (b) and (c) of the protocol."""
    history = json.loads(holdout.read_text())
    later = json.loads(revision_manifest.read_text())
    groups = {"holdout_rows": sorted({r["path"] for r in history["rows"]})}
    groups.update({"holdout_" + k: sorted(v) for k, v in history["excluded"].items()})
    groups["revision_rows"] = sorted({r["path"] for r in later["rows"]})
    groups["revision_extra"] = sorted(json.loads(extra.read_text()))
    return groups


def stems_in(data):
    return {"data/cubicasa5k/%s-%s.png" % (a.decode(), b.decode()) for a, b in STEM.findall(data)}


def file_scan(path):
    """Return (sha256, drawing names, 64-hex strings) found in a file's name, bytes and ZIP member names."""
    names = stems_in(str(path).encode())
    hexes = set()
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        tail = b""
        while chunk := f.read(16 * 1024 * 1024):
            digest.update(chunk)
            window = tail + chunk
            names |= stems_in(window)
            hexes |= {h.decode() for h in HEX64.findall(window)}
            tail = window[-256:]
    if path.suffix in (".zip", ".npz"):
        try:
            with ZipFile(path) as z:
                for member in z.namelist():
                    names |= stems_in(member.encode())
        except (OSError, ValueError) as exc:
            names.add("unreadable-zip:" + type(exc).__name__)
    return digest.hexdigest(), names, hexes


def walk(root, skip_dirs=AUDIT_SKIP_DIRS, skip=()):
    skip = {Path(p).resolve() for p in skip}
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        here = Path(dirpath)
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs and (here / d).resolve() not in skip)
        for name in sorted(files):
            path = here / name
            if path.resolve() not in skip and path.is_file():
                yield path


def classify(rel, digest, gate_ok):
    if rel in INVENTORIES:
        expected, reason = INVENTORIES[rel]
        return reason if digest == expected else None
    if digest == MANIFEST:
        return "byte-identical copy of the sponsor questions.jsonl"
    if digest == "release-member-list":
        return "second copy of the sponsor ZIP (identical member list; bytes not read)"
    if rel.startswith(GATE_DIR + "/") and gate_ok:
        return GATE_REASON
    return None


def audit(args):
    """Search development artifacts for test-split drawings and PNG bytes not in groups (a)-(c)."""
    splits = read_splits(args.split_dir)
    groups = known_exposures(args.holdout, args.revision_manifest, args.revision_extra)
    exposed = set().union(*map(set, groups.values()))
    reserved = set(args.reserved.read_text().split())
    check(reserved == splits["test"] - exposed, "The reserved list is not the test split minus (a), (b) and (c).")
    with ZipFile(args.archive) as z:
        release_members = z.namelist()
        prompts = load_prompts(z)
        pool = sorted((set(prompts) & splits["test"]) - exposed)
        pool_hash = {p: sha(z.read(PREFIX + p)) for p in pool}
        exposed_hash = {}
        for p in sorted(exposed):
            if PREFIX + p in z.NameToInfo:
                exposed_hash.setdefault(sha(z.read(PREFIX + p)), []).append(p)
    by_hash = defaultdict(list)
    for p, h in pool_hash.items():
        by_hash[h].append(p)
    pool_hashes = set(by_hash)
    gate_files = sorted((ROOT / GATE_DIR).glob("*.json")) if (ROOT / GATE_DIR).is_dir() else []
    gate_ok = all(
        datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) < datetime(2026, 11, 14, 9, 19, 6, tzinfo=timezone.utc)
        for f in gate_files
    )
    inventories, exposures, hash_hits, skipped = {}, defaultdict(set), defaultdict(set), []
    files = 0
    archive = Path(args.archive).resolve()
    for root in AUDIT_ROOTS:
        if not (ROOT / root).exists():
            skipped.append(root + " (missing)")
            continue
        for path in walk(ROOT / root, skip=(args.work, archive)):
            files += 1
            rel = path.relative_to(ROOT).as_posix()
            if path.stat().st_size > LARGE:
                # Name and ZIP member names only; the byte contents of very large files are not read.
                digest, names, hexes = "", stems_in(rel.encode()), set()
                if path.suffix == ".zip":
                    with ZipFile(path) as z:
                        members = z.namelist()
                    names |= set().union(*(stems_in(n.encode()) for n in members))
                    if members == release_members:
                        digest = "release-member-list"
                skipped.append(rel + " (larger than 512 MB: name and ZIP member names checked, bytes not read)")
            else:
                digest, names, hexes = file_scan(path)
            reason = classify(rel, digest, gate_ok)
            hits = sorted(names & reserved)
            for h in sorted((hexes | {digest}) & pool_hashes):
                for p in by_hash[h]:
                    if not (reason and p in hits):
                        hash_hits[p].add(rel)
            if not hits:
                continue
            if reason:
                bucket = GATE_DIR + "/*.json" if rel.startswith(GATE_DIR + "/") else rel
                entry = inventories.setdefault(bucket, dict(reason=reason, files=0, drawings=set()))
                entry["files"] += 1
                entry["drawings"].update(hits)
            else:
                for p in hits:
                    exposures[p].add(rel)
    duplicates = {p: exposed_hash[h] for p, h in pool_hash.items() if h in exposed_hash}
    internal = {h: ps for h, ps in by_hash.items() if len(ps) > 1}
    excluded = sorted(set(exposures) | set(hash_hits) | set(duplicates))
    result = dict(
        roots=list(AUDIT_ROOTS),
        files_scanned=files,
        skipped=skipped,
        reserved=len(reserved),
        question_bearing_pool_before_audit=len(pool),
        inventories={
            k: dict(reason=v["reason"], files=v["files"], reserved_drawings_named=len(v["drawings"]))
            for k, v in sorted(inventories.items())
        },
        gate_files_predate_holdout_manifest=gate_ok,
        exposures={p: sorted(v) for p, v in sorted(exposures.items())},
        hash_hits={p: sorted(v) for p, v in sorted(hash_hits.items())},
        duplicate_of_exposed_png=duplicates,
        identical_pool_pngs=sorted(internal.values()),
        excluded=excluded,
    )
    save(args.work / "audit.json", result)
    print(
        f"Scanned {files} files; {len(excluded)} pool drawings excluded by the audit; "
        f"{len(internal)} groups of identical pool PNGs; audit {sha(canonical(result))}"
    )
    return result


def select(pool, quotas, seed):
    picked = []
    for name, quota in quotas.items():
        subset = sorted((p for p in pool if style(p) == name), key=lambda p: stable(seed, "drawing", p))
        check(len(subset) >= quota, "Not enough fresh drawings for " + name)
        picked.extend(subset[:quota])
    return sorted(picked)


def freeze(args):
    splits = read_splits(args.split_dir)
    groups = known_exposures(args.holdout, args.revision_manifest, args.revision_extra)
    report = json.loads((args.work / "audit.json").read_text())
    groups["audit"] = report["excluded"]
    exposed = set().union(*map(set, groups.values()))
    reserved = set(args.reserved.read_text().split())
    with ZipFile(args.archive) as z:
        prompts = load_prompts(z)  # paths and question text only
        pool = (set(prompts) & splits["test"]) - exposed
        check(pool <= reserved, "Pool drawing outside the reserved list.")
        picked = select(pool, QUOTAS, SEED)
        rows, selected = [], {}
        for path in picked:
            digest = sha(z.read(PREFIX + path))
            check(digest not in selected.values(), "Two selected drawings have identical bytes.")
            selected[path] = digest
            for category, question in sorted(prompts[path].items()):
                check(category in FAMILIES, "Unexpected question family.")
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
        for path in sorted(exposed):
            if PREFIX + path in z.NameToInfo:
                check(sha(z.read(PREFIX + path)) not in selected.values(), "An exposed PNG is selected under another name.")
    check(len({r["id"] for r in rows}) == len(rows), "Duplicate question ID.")
    eligible = Counter(style(p) for p in pool)
    result = dict(
        protocol="scan-next-1",
        seed=SEED,
        base_revision=BASE,
        source_questions_sha256=MANIFEST,
        upstream_splits_sha256=SPLITS,
        reserved_list_sha256=sha(args.reserved.read_bytes()),
        exclusions_sha256=sha(canonical(groups)),
        exclusion_counts={k: len(v) for k, v in sorted(groups.items())},
        exposed_distinct=len(exposed),
        audit_sha256=sha(canonical(report)),
        eligible_by_style=dict(sorted(eligible.items())),
        styles=QUOTAS,
        unused_by_style={k: eligible[k] - QUOTAS.get(k, 0) for k in sorted(eligible)},
        images=len(picked),
        questions=len(rows),
        category_counts=dict(sorted(Counter(r["category"] for r in rows).items())),
        comparable_categories=sorted(COMPARABLE),
        comparable_questions=sum(r["category"] in COMPARABLE for r in rows),
        rows=rows,
    )
    if args.manifest.exists():
        check(result == json.loads(args.manifest.read_text()), "Existing frozen scan-next manifest differs.")
    else:
        save(args.manifest, result)
        args.manifest.chmod(0o444)
    return result


def load_manifest(path):
    manifest = json.loads(path.read_text())
    check(FINGERPRINT is None or sha(canonical(manifest)) == FINGERPRINT, "Not the frozen scan-next manifest.")
    rows = manifest["rows"]
    check(
        len({r["id"] for r in rows}) == len(rows)
        and all(
            set(r) == {"id", "path", "question", "style", "category", "image_sha256"}
            and r["id"] == stable(r["path"], r["question"])[:16]
            and r["category"] in FAMILIES
            for r in rows
        ),
        "Invalid frozen manifest rows.",
    )
    return manifest


def fingerprint_of(manifest):
    return sha(canonical(manifest))


# ---------------------------------------------------------------------------------------------
# Arms


def resolve(revision_ref):
    commit = subprocess.check_output(["git", "rev-parse", "--verify", revision_ref + "^{commit}"], cwd=ROOT, text=True)
    commit = commit.strip()
    check(FULL_SHA.match(commit), "Unresolved revision.")
    return commit


def arm_revision(arm, revision_ref):
    check(ARM_NAME.match(arm or ""), "Specify --arm with a short lower-case name.")
    if arm in BASELINE_ARMS:
        check(revision_ref in (None, BASE), "Baseline arms are pinned to " + BASE)
        return BASE
    check(revision_ref and revision_ref != "working", "This arm needs --revision <committed revision>.")
    commit = resolve(revision_ref)
    check(commit != BASE, "The after arm must differ from the baseline revision.")
    return commit


def data_assets(commit):
    """Tracked non-Python files under scripts/ at a candidate revision (reader data assets)."""
    out = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--name-only", commit, "scripts/"], cwd=ROOT)
    return sorted(n for n in out.decode().split("\0") if n and not n.endswith(".py"))


@contextmanager
def offline():
    def refuse(*args, **kwargs):
        raise AssertionError("Network access is forbidden during inference.")

    with patch.object(socket.socket, "connect", refuse), patch.object(
        socket.socket, "connect_ex", refuse
    ), patch.object(socket, "create_connection", refuse), patch.object(socket, "getaddrinfo", refuse):
        yield


def foreign_modules(package):
    bad = []
    package = package.resolve()
    for name, module in list(sys.modules.items()):
        if name == "scripts" or name.startswith("scripts.") or name.startswith("scan_"):
            path = getattr(module, "__file__", None)
            if not path or not Path(path).resolve().is_relative_to(package):
                bad.append(name)
    return sorted(bad)


def seal_of(work, manifest, arm):
    rows, base, config = revision.read_arm(work, manifest, arm, fingerprint=fingerprint_of(manifest))
    seal = dict(
        base,
        arm=arm,
        revision=config["revision"],
        source_sha256=config["source_sha256"],
        source_fingerprint=sha(canonical(config["source_sha256"])),
    )
    return rows, seal, config


def verify_arm(work, manifest, arm):
    """Recompute an arm seal from its files; refuse unless it equals the saved seal."""
    root = work / arm
    check((root / "seal.json").is_file(), "Missing sealed arm: " + arm)
    rows, seal, config = seal_of(work, manifest, arm)
    check(seal == json.loads((root / "seal.json").read_text()), "Broken arm seal: " + arm)
    check(config["manifest_sha256"] == fingerprint_of(manifest), "Arm ran on a different manifest: " + arm)
    for name, digest in config["source_sha256"].items():
        check(sha((root / "src" / name).read_bytes()) == digest, "Snapshot file changed: " + name)
    return rows, seal, config


def run(args, manifest):
    fingerprint = fingerprint_of(manifest)
    check(FINGERPRINT is None or fingerprint == FINGERPRINT, "Changed scan-next manifest.")
    for name in ("NEMOTRON_BASE_URL", "NEMOTRON_API_KEY"):
        check(not os.environ.get(name), "Unset " + name + " before running an arm.")
    commit = arm_revision(args.arm, args.revision)
    root = args.work / args.arm
    if (root / "seal.json").exists():
        _, seal, _ = verify_arm(args.work, manifest, args.arm)
        print("Arm already sealed; nothing to run.", sha(canonical(seal)), flush=True)
        return seal
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    with (root / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        extras = list(args.source) + ([] if args.arm in BASELINE_ARMS else data_assets(commit))
        package, files = revision.snapshot(root, commit, extras)
        if args.arm in BASELINE_ARMS and BASE_SOURCE_FINGERPRINT:
            check(sha(canonical(files)) == BASE_SOURCE_FINGERPRINT, "Baseline source differs from the pinned reader.")
        harness_dir = str(Path(__file__).resolve().parent)
        sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(harness_dir)]
        sys.path.insert(0, str(package))
        os.environ["PLANPROOF_CUBICASA_CODE"] = str((args.assets / "CubiCasa5k").resolve())
        os.environ["PLANPROOF_OBJECT_WEIGHTS"] = str((args.assets / "model_best_val_loss_var.pkl").resolve())
        reader = importlib.import_module("scripts.scan_reader")
        check(not foreign_modules(package), "Reader modules loaded outside the snapshot.")
        obj = reader.scan_objects
        check(obj.available(), "Specialist files/packages unavailable.")
        code, weights = obj._locations()
        model_files = {name: sha((code / name).read_bytes()) for name in obj.SOURCE_HASHES}
        with weights.open("rb") as f:
            weights_hash = hashlib.file_digest(f, "sha256").hexdigest()
        check(obj.SOURCE_HASHES == model_files and weights_hash == obj.WEIGHTS_HASH, "Model asset mismatch.")
        config = dict(
            source_sha256=files,
            revision=commit,
            manifest_sha256=fingerprint,
            detector_source=model_files,
            weights_sha256=weights_hash,
            detector_revision=obj.REVISION,
            environment=revision.environment(),
            network="disabled",
            hosted="forbidden; blank endpoint and no key",
        )
        if (root / "config.json").exists():
            check(config == json.loads((root / "config.json").read_text()), "Arm configuration mismatch.")
        else:
            save(root / "config.json", config)
        started_all = time.monotonic()
        drawings = defaultdict(list)
        for q in manifest["rows"]:
            drawings[q["path"]].append(q)
        with offline(), patch.object(reader.nemotron, "run", side_effect=AssertionError("Hosted calls forbidden.")):
            for index, (path, questions) in enumerate(drawings.items(), 1):
                image = args.work / "inputs" / Path(path).name
                digest = sha(image.read_bytes())
                for q in questions:
                    check(q["image_sha256"] == digest, "Staged source image mismatch.")
                    output = root / "outputs" / (q["id"] + ".json")
                    if output.exists():
                        continue
                    started = time.monotonic()
                    report = reader.run(image, q["question"], "", reader.nemotron.MODEL, None)
                    result = revision.normalize(
                        reader, report, q["question"], digest, round(1000 * (time.monotonic() - started))
                    )
                    save(output, dict(id=q["id"], question=q["question"], image_sha256=digest, **result))
                print(f"{args.arm} drawing {index}/{len(drawings)}; {time.monotonic() - started_all:.1f}s", flush=True)
        check(not foreign_modules(package), "Reader modules loaded outside the snapshot.")
        _, seal, _ = seal_of(args.work, manifest, args.arm)
        save(root / "seal.json", seal)
        for path in [root / "config.json", root / "seal.json", *sorted((root / "outputs").glob("*.json"))]:
            path.chmod(0o444)
        verify_arm(args.work, manifest, args.arm)
        print("Sealed", args.arm, sha(canonical(seal)), flush=True)
        return seal


def verify(args, manifest):
    """Structure only: seal, schema and statuses. Prints no prediction values or distributions."""
    rows, seal, config = verify_arm(args.work, manifest, args.arm)
    statuses = {r["status"] for r in rows.values()}
    check(statuses <= {"answered", "unknown", "abstained"}, "Unexpected status.")
    check(set(rows) == {q["id"] for q in manifest["rows"]}, "Arm does not cover the manifest.")
    print(
        f"{args.arm}: {len(rows)} records, schema valid, seal {sha(canonical(seal))}, "
        f"revision {config['revision']}, sources {seal['source_fingerprint']}"
    )
    return seal


def identity(args):
    """Compare the baseline snapshot with the reader that produced 167 of 398."""
    reference = json.loads((revision.WORK / "new/config.json").read_text())["source_sha256"]
    root = args.work / "before" / "src"
    ours = {}
    for name in sorted(set(reference) | {p.relative_to(root).as_posix() for p in (root / "scripts").glob("*.py")}):
        if name.endswith("__init__.py"):
            continue
        path = root / name
        ours[name] = sha(path.read_bytes()) if path.exists() else None
    differs = sorted(n for n in set(reference) | set(ours) if reference.get(n) != ours.get(n))
    result = dict(reference="scan-revision/new/config.json", files=len(ours), differing=differs)
    save(args.work / "identity.json", result)
    print(json.dumps(result))
    return result


def noise(args, manifest):
    """Agreement between two sealed runs of one reader; counts only."""
    first, _, c1 = verify_arm(args.work, manifest, args.arms[0])
    second, _, c2 = verify_arm(args.work, manifest, args.arms[1])
    same_config = {k: v for k, v in c1.items()} == {k: v for k, v in c2.items()}
    answers = sum((first[i]["status"], first[i]["answer"]) != (second[i]["status"], second[i]["answer"]) for i in first)
    evidences = sum(first[i]["evidence"] != second[i]["evidence"] for i in first)
    methods = sum(first[i].get("method") != second[i].get("method") for i in first)
    result = dict(
        arms=list(args.arms),
        questions=len(first),
        identical_configuration=same_config,
        answers_differing=answers,
        evidence_lists_differing=evidences,
        methods_differing=methods,
    )
    save(args.work / "noise.json", result)
    print(json.dumps(result))
    return result


# ---------------------------------------------------------------------------------------------
# Scoring (after both arms are sealed)


def join(manifest, before, after, targets):
    records = []
    for q in manifest["rows"]:
        gold = targets[q["path"], q["question"]]
        record = dict(**q, gold=gold)
        for name, arm in (("old", before), ("new", after)):
            r = arm[q["id"]]
            record[name] = dict(**r, correct=r["status"] == "answered" and r["answer"] == gold)
        records.append(record)
    return records


def relabel(block):
    if block is None:
        return None
    mae = block["mean_absolute_error_on_both_answered"]
    return dict(
        before=block["old"],
        after=block["new"],
        paired=block["paired"],
        mean_absolute_error_on_both_answered=dict(before=mae["old"], after=mae["new"]),
        delta_exact_pp=round(100 * (block["new"]["exact"] - block["old"]["exact"]) / block["old"]["questions"], 2),
    )


def paired(records, seed):
    if not records:
        return None
    block = relabel(revision.paired_metrics(records))
    block["clustered_bootstrap_delta_pp_95"] = revision.clustered_interval(records, seed=seed)
    return block


def brief(record):
    return dict(
        id=record["id"],
        path=record["path"],
        style=record["style"],
        category=record["category"],
        question=record["question"],
        gold=record["gold"],
        before=dict(status=record["old"]["status"], answer=record["old"]["answer"]),
        after=dict(status=record["new"]["status"], answer=record["new"]["answer"]),
    )


def summarize(records, styles, seed):
    by_style = {s: paired([r for r in records if r["style"] == s], seed) for s in styles}
    weighted = {
        arm: round(sum(by_style[s][arm]["exact"] / by_style[s][arm]["questions"] for s in styles) / len(styles), 4)
        for arm in ("before", "after")
    }
    return dict(
        overall=paired(records, seed),
        comparable_eleven_families=paired([r for r in records if r["category"] in COMPARABLE], seed),
        equal_style_weighted_exact_accuracy=dict(
            weighted, delta_pp=round(100 * (weighted["after"] - weighted["before"]), 2)
        ),
        by_style=by_style,
        by_group={g: paired([r for r in records if r["category"] in c], seed) for g, c in GROUPS.items()},
        by_track={t: paired([r for r in records if r["category"] in c], seed) for t, c in TRACKS.items()},
        by_category={c: paired([r for r in records if r["category"] == c], seed) for c in sorted(FAMILIES)},
        regressions=[brief(r) for r in records if r["old"]["correct"] and not r["new"]["correct"]],
        newly_wrong=[
            brief(r)
            for r in records
            if r["old"]["status"] != "answered" and r["new"]["status"] == "answered" and not r["new"]["correct"]
        ],
        gains=[brief(r) for r in records if r["new"]["correct"] and not r["old"]["correct"]],
    )


def check_pair(configs):
    for label in ("weights_sha256", "detector_source", "detector_revision", "environment", "network", "manifest_sha256"):
        check(configs[0][label] == configs[1][label], "Arm configuration differs: " + label)


def score(args, manifest):
    fingerprint = fingerprint_of(manifest)
    check(FINGERPRINT is None or fingerprint == FINGERPRINT, "Changed scan-next manifest.")
    # Verify both seals before the sponsor answers are opened.
    before, bseal, bconfig = verify_arm(args.work, manifest, args.before)
    after, aseal, aconfig = verify_arm(args.work, manifest, args.after)
    check(bconfig["revision"] == BASE, "The before arm is not the pinned baseline.")
    check(
        BASE_SOURCE_FINGERPRINT is None or bseal["source_fingerprint"] == BASE_SOURCE_FINGERPRINT,
        "Unexpected baseline sources.",
    )
    check(FULL_SHA.match(aconfig["revision"]) and aconfig["revision"] != BASE, "The after arm needs a committed revision.")
    for name, digest in aconfig["source_sha256"].items():
        check(sha(revision.source_bytes(aconfig["revision"], name)) == digest, "After-arm source differs from Git: " + name)
    check_pair((bconfig, aconfig))
    targets = revision.read_targets(args.archive, manifest)
    records = join(manifest, before, after, targets)
    out = dict(
        observed_date=datetime.now(timezone.utc).date().isoformat(),
        protocol="docs/scan-next-protocol.md",
        manifest_sha256=fingerprint,
        arms=dict(before=args.before, after=args.after),
        scope="Original PNG and original English count question; offline local readers only; a hosted hand-off is a deferral.",
        drawings=manifest["images"],
        questions=len(records),
        seals=dict(before=bseal, after=aseal),
        seal_sha256=dict(before=sha(canonical(bseal)), after=sha(canonical(aseal))),
        configurations=dict(before=bconfig, after=aconfig),
        **summarize(records, QUOTAS, SEED),
        inference_seconds={
            label: round(sum(r[key]["elapsed_ms"] for r in records) / 1000, 2)
            for label, key in (("before", "old"), ("after", "new"))
        },
    )
    save(args.work / "paired-rows.json", records)
    save(args.work / "summary.json", out)
    if args.report:
        save(args.report, out)
    print(json.dumps(dict(overall=out["overall"], equal_style=out["equal_style_weighted_exact_accuracy"]), indent=2))
    return out


def localization(rows, upstream):
    """Marks matched over marks placed, objects located and fully grounded questions, per class."""
    result = evidence.run(rows, upstream, *evidence.paired_predictions(rows))
    table = {}
    for label, key in (("before", "before"), ("after", "after")):
        for cls, c in result["by_reader"][key].items():
            table.setdefault(cls, {})[label] = dict(
                matched=c["matched"],
                marks_placed=c["proposed"],
                annotated=c["reference"],
                fully_grounded=c["fully_grounded"],
                questions=c["questions"],
            )
    return result, table


def localize(args, manifest):
    verify_arm(args.work, manifest, args.before)
    verify_arm(args.work, manifest, args.after)
    rows = json.loads((args.work / "paired-rows.json").read_text())
    check([r["id"] for r in rows] == [q["id"] for q in manifest["rows"]], "Paired rows do not match the manifest.")
    result, table = localization(rows, args.references)
    save(args.work / "grounding.json", result)
    save(args.work / "localization.json", table)
    print(json.dumps(table, indent=2))
    return table


# ---------------------------------------------------------------------------------------------
# Reference annotations (later session only)


def http_range(start, end, url=ZENODO):
    for attempt in range(8):
        try:
            request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                    raise OSError("Range request refused")
                raw = response.read()
            if len(raw) < end - start + 1:
                raise OSError("Short range")
            return raw[: end - start + 1]
        except OSError:
            if attempt == 7:
                raise
            time.sleep(min(45, 2**attempt))


def central_entries(raw):
    """Parse a ZIP central directory into {name: (local offset, compressed, size, crc, method)}."""
    entries, k = {}, 0
    while k < len(raw):
        h = struct.unpack_from("<4s6H3I5H2I", raw, k)
        check(h[0] == b"PK\x01\x02", "Malformed central directory.")
        ns, es, cs = h[10:13]
        name = raw[k + 46 : k + 46 + ns].decode()
        extra = raw[k + 46 + ns : k + 46 + ns + es]
        k += 46 + ns + es + cs
        compressed, size, offset = h[8], h[9], h[-1]
        if 0xFFFFFFFF in (compressed, size, offset):
            j = 0
            while j < len(extra):
                kind, n = struct.unpack_from("<HH", extra, j)
                field, j = extra[j + 4 : j + 4 + n], j + 4 + n
                if kind == 1:
                    values = iter(struct.unpack_from("<%dQ" % (n // 8), field))
                    size = next(values) if size == 0xFFFFFFFF else size
                    compressed = next(values) if compressed == 0xFFFFFFFF else compressed
                    offset = next(values) if offset == 0xFFFFFFFF else offset
        entries[name] = (offset, compressed, size, h[7], h[4])
    return entries


def member_bytes(entry, fetch):
    offset, compressed, size, crc, method = entry
    margin = 512
    while True:
        raw = fetch(offset, offset + 30 + margin + compressed - 1)
        n, e = struct.unpack_from("<HH", raw, 26)
        if 30 + n + e + compressed <= len(raw):
            break
        margin = n + e
    body = raw[30 + n + e : 30 + n + e + compressed]
    data = zlib.decompress(body, -15) if method == 8 else body
    check(len(data) == size and zlib.crc32(data) == crc, "Reference member failed its CRC.")
    return data


def reference_targets(manifest):
    drawings = sorted({r["path"] for r in manifest["rows"] if r["category"] in evidence.CATEGORIES})
    return {
        "cubicasa5k/" + Path(p).stem.replace("-", "/") + "/" + member: p
        for p in drawings
        for member, _ in REFERENCE_MEMBERS
    }


def build_references(manifest, central, fetch, sponsor, out):
    entries = central_entries(central)
    targets = reference_targets(manifest)
    hashes = {r["path"]: r["image_sha256"] for r in manifest["rows"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    pending = out.with_suffix(".partial")
    with ZipFile(pending, "w") as z:
        for member, path in sorted(targets.items()):
            check(member in entries, "Missing upstream member: " + member)
            data = None
            if member.endswith("/F1_original.png") and sponsor is not None:
                local = sponsor(path)
                offset, compressed, size, crc, method = entries[member]
                if len(local) == size and zlib.crc32(local) == crc:
                    data = local
            data = data if data is not None else member_bytes(entries[member], fetch)
            if member.endswith("/F1_original.png"):
                check(sha(data) == hashes[path], "Upstream original differs from the frozen PNG: " + path)
            z.writestr(member, data)
    pending.replace(out)
    return len(targets)


def fetch_refs(args, manifest):
    verify_arm(args.work, manifest, args.before)
    verify_arm(args.work, manifest, args.after)
    cache = CENTRAL["cache"]
    if cache.is_file() and sha(cache.read_bytes()) == CENTRAL["sha256"]:
        central = cache.read_bytes()
    else:
        central = http_range(CENTRAL["offset"], CENTRAL["offset"] + CENTRAL["size"] - 1)
    check(sha(central) == CENTRAL["sha256"], "Unexpected upstream archive directory.")
    with ZipFile(args.archive) as z:
        count = build_references(
            manifest, central, http_range, lambda p: z.read(PREFIX + p), args.references
        )
    print(f"Wrote {count} reference members to {args.references} ({sha(args.references.read_bytes())})")


# ---------------------------------------------------------------------------------------------
# Leak check and clickable example


def scan_text(data, stems, hashes):
    found = set(stems_in(data)) & stems
    found |= {h.decode() for h in HEX64.findall(data)} & hashes
    if sha(data) in hashes:
        found.add("identical image bytes")
    return found


def git_blobs(commit, base=BASE):
    commits = [commit] + subprocess.check_output(["git", "rev-list", base + ".." + commit], cwd=ROOT, text=True).split()
    blobs = defaultdict(set)
    for c in dict.fromkeys(commits):
        out = subprocess.check_output(["git", "ls-tree", "-r", "-z", c], cwd=ROOT)
        for item in out.split(b"\0"):
            if not item:
                continue
            meta, path = item.split(b"\t", 1)
            _, kind, oid = meta.split()
            if kind == b"blob":
                blobs[oid.decode()].add(path.decode())
    return blobs


def read_blobs(oids):
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=("\n".join(oids) + "\n").encode(),
                          capture_output=True, check=True)
    raw, k, result = proc.stdout, 0, {}
    for oid in oids:
        header_end = raw.index(b"\n", k)
        name, kind, size = raw[k:header_end].split()
        size = int(size)
        result[oid] = raw[header_end + 1 : header_end + 1 + size]
        k = header_end + 1 + size + 1
    return result


def leak_findings(manifest, commit, scratch):
    stems = {r["path"] for r in manifest["rows"]}
    hashes = {r["image_sha256"] for r in manifest["rows"]}
    findings = []
    blobs = git_blobs(commit)
    contents = read_blobs(sorted(blobs))
    for oid, paths in sorted(blobs.items()):
        data = contents[oid]
        names = {p for p in paths if not (p in EVALUATOR_FILES and allowed_evaluator_file(p, data))}
        if not names:
            continue
        found = scan_text(data, stems, hashes) | set().union(*(stems_in(p.encode()) & stems for p in names))
        if found:
            findings.append(dict(where="git", paths=sorted(names), hits=sorted(found)))
    for directory in scratch:
        if not directory.exists():
            continue
        for dirpath, dirs, files in os.walk(directory, followlinks=False):
            here = Path(dirpath)
            for name in sorted(dirs + files):
                path = here / name
                found = set(stems_in(str(path).encode())) & stems
                if path.is_symlink():
                    found |= set(stems_in(os.readlink(path).encode())) & stems
                elif path.is_file():
                    digest, names, hexes = file_scan(path)
                    found |= (names & stems) | (hexes & hashes) | ({"identical image bytes"} if digest in hashes else set())
                if found:
                    findings.append(dict(where="scratch", paths=[str(path)], hits=sorted(found)))
    return findings


def allowed_evaluator_file(path, data):
    if path == "docs/scan-next-inputs.json":
        try:
            return FINGERPRINT is not None and sha(canonical(json.loads(data))) == FINGERPRINT
        except ValueError:
            return False
    return False


def leak_check(args, manifest):
    commit = resolve(args.revision)
    scratch = [] if args.no_scratch else [Path(p) for p in (args.scratch or SCRATCH)]
    findings = leak_findings(manifest, commit, scratch)
    report = dict(
        revision=commit,
        scratch=[str(p) for p in scratch],
        findings=findings,
        checked=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    save(args.work / ("leak-check-" + commit[:12] + ".json"), report)
    if findings:
        for f in findings:
            print("LEAK", f["where"], ", ".join(f["paths"])[:200], f"({len(f['hits'])} fresh identifiers)")
        sys.exit(1)
    print(f"No fresh drawing names or image hashes in {commit} or {len(scratch)} scratch directories.")


def example(args, manifest):
    """Build a replay bundle of the after arm and print links to gained questions."""
    verify_arm(args.work, manifest, args.before)
    verify_arm(args.work, manifest, args.after)
    rows = json.loads((args.work / "paired-rows.json").read_text())
    sys.path.insert(0, str(ROOT))
    from scripts import export_scan_replay, scan_library

    reports = []
    for r in rows:
        item = r["new"]
        if item["status"] != "answered":
            continue
        source, model = export_scan_replay.LOCAL_METHODS.get(item.get("method"), ("local reader", item.get("method") or "local"))
        enriched = dict(item, path=r["path"], image=Path(r["path"]).name, model=model, coordinate_system=scan_library.COORDS)
        report = scan_library._safe_report(
            enriched, r["path"], r["image_sha256"], r["question"], "Measured scan-next after arm · " + source, sealed=True
        )
        check(report is not None, "Invalid evidence in an after-arm answer.")
        reports.append({k: report[k] for k in export_scan_replay.UI_FIELDS if k in report})
    data = export_scan_replay.canonical(dict(version=1, reports=reports)) + b"\n"
    out = args.work / "scan-next-replay.json"
    out.write_bytes(data)
    print(f"{sha(data)}  {out} ({len(reports)} answered reports)")
    gained = sorted(
        (r for r in rows if r["new"]["correct"] and not r["old"]["correct"]),
        key=lambda r: (r["category"] not in TRACKS["track1_openings"] | TRACKS["track2_deferred"], stable(SEED, "example", r["id"])),
    )
    for r in gained[: args.limit]:
        query = urlencode(dict(path=r["path"], question=r["question"]))
        print(f"{r['category']}: expected {r['gold']}, before {r['old']['answer']}, after {r['new']['answer']}: "
              f"http://127.0.0.1:4179/scan-drawing.html?{query}")


# ---------------------------------------------------------------------------------------------
# Validation of the scoring path on the previous sealed cohort


def validate(args):
    manifest = json.loads(args.revision_manifest.read_text())
    check(sha(canonical(manifest)) == revision.FINGERPRINT, "Not the 48-drawing manifest.")
    arms, configs = {}, []
    for name in ("old", "new"):
        rows, seal, config = revision.read_arm(args.revision_work, manifest, name)
        check(seal == json.loads((args.revision_work / name / "seal.json").read_text()), "Broken seal: " + name)
        check(sha(canonical(config["source_sha256"])) == revision.SOURCE_FINGERPRINTS[name], "Unexpected sources.")
        arms[name] = rows
        configs.append(config)
    check_pair(configs)
    targets = revision.read_targets(args.archive, manifest)
    records = join(manifest, arms["old"], arms["new"], targets)
    summary = summarize(records, revision.QUOTAS, revision.SEED)
    overall = summary["overall"]
    comparisons = []

    def compare(label, published, observed):
        comparisons.append(dict(figure=label, published=published, observed=observed, reproduced=published == observed))

    for arm, label in (("old", "before"), ("new", "after")):
        for key, value in PUBLISHED[arm].items():
            compare(f"{arm} {key}", value, overall[label][key])
    for key, value in PUBLISHED["paired"].items():
        compare(key, value, overall["paired"][key])
    compare("bootstrap interval pp", PUBLISHED["interval"], overall["clustered_bootstrap_delta_pp_95"])
    if args.references:
        _, table = localization(records, args.references)
        for cls, arms_published in PUBLISHED["localization"].items():
            for arm, label in (("old", "before"), ("new", "after")):
                t = table[cls][label]
                compare(
                    f"{cls} {arm} matched/placed/annotated/fully grounded",
                    list(arms_published[arm]),
                    [t["matched"], t["marks_placed"], t["annotated"], t["fully_grounded"]],
                )
    result = dict(comparisons=comparisons, all_reproduced=all(c["reproduced"] for c in comparisons))
    save(args.work / "validation-revision.json", result)
    for c in comparisons:
        print(("ok  " if c["reproduced"] else "DIFF"), c["figure"], c["published"], c["observed"])
    check(result["all_reproduced"], "A published figure did not reproduce.")
    return result


# ---------------------------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "action",
        choices=["audit", "freeze", "prepare", "run", "verify", "identity", "noise", "leak-check",
                 "score", "fetch-refs", "localize", "example", "validate"],
    )
    p.add_argument("--archive", type=Path, default=ARCHIVE)
    p.add_argument("--manifest", type=Path, default=FROZEN)
    p.add_argument("--work", type=Path, default=WORK)
    p.add_argument("--split-dir", type=Path, default=SPLIT_DIR)
    p.add_argument("--reserved", type=Path, default=RESERVED)
    p.add_argument("--holdout", type=Path, default=HOLDOUT_MANIFEST)
    p.add_argument("--revision-manifest", type=Path, default=REVISION_MANIFEST)
    p.add_argument("--revision-extra", type=Path, default=REVISION_EXTRA)
    p.add_argument("--revision-work", type=Path, default=revision.WORK)
    p.add_argument("--assets", type=Path, default=ASSETS)
    p.add_argument("--arm")
    p.add_argument("--arms", nargs=2, default=list(BASELINE_ARMS))
    p.add_argument("--before", default="before")
    p.add_argument("--after", default="after")
    p.add_argument("--revision", help="Committed revision for a non-baseline arm or the leak check")
    p.add_argument("--source", action="append", default=[], help="Extra non-imported reader asset under scripts/")
    p.add_argument("--scratch", action="append", help="Directory for the leak check (default: implementers' scratch)")
    p.add_argument("--no-scratch", action="store_true")
    p.add_argument("--references", type=Path, help="Upstream-format ZIP with model.svg, F1_scaled.png, F1_original.png")
    p.add_argument("--report", type=Path)
    p.add_argument("--limit", type=int, default=3)
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    if a.action == "audit":
        audit(a)
        return
    if a.action == "freeze":
        m = freeze(a)
        print(m["images"], m["questions"], m["eligible_by_style"], m["category_counts"], fingerprint_of(m))
        return
    if a.action == "validate":
        validate(a)
        return
    if a.action == "identity":
        identity(a)
        return
    if a.action in ("fetch-refs", "localize") and a.references is None:
        a.references = a.work / "references/references.zip"
    m = load_manifest(a.manifest)
    actions = dict(
        run=run, verify=verify, noise=noise, score=score, localize=localize,
        example=example, **{"leak-check": leak_check, "fetch-refs": fetch_refs},
    )
    if a.action == "prepare":
        print(revision.prepare(m, a.archive, a.work))
    else:
        actions[a.action](a, m)


if __name__ == "__main__":
    main()
