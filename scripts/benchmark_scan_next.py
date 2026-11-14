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
# before-control is a third run of the baseline, made back to back with the after arm (E1).
BASELINE_ARMS = ("before", "before-repeat", "before-control")
AFTER_ARMS = ("after", "after-repeat")
# Full SHA of the frozen candidate. Unset until phase B sets it in one commit before any after arm runs.
AFTER_REVISION = None
ARM_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
COORDS = "xyxy_top_left_0_to_1000"
# Deferrals the harness records when the reader raises or returns a report that fails validation.
HARNESS_DEFERRALS = ("reader_error", "invalid_report")
# Exceptions of the inference guards; these still abort the run.
GUARDS = ("Network access is forbidden during inference.", "Hosted calls forbidden.")
# Run conditions: an arm starts once the 1-minute load average is below LOAD_LIMIT, or after LOAD_WAIT
# seconds regardless. Each arm keeps a time-out log and its run conditions; both are sealed.
LOAD_LIMIT = 12.0
LOAD_WAIT = 1800
RUN_RECORDS = ("timeouts.json", "conditions.json")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# Pinned after the freeze and the first baseline snapshot (see docs/scan-next-protocol.md).
FINGERPRINT = "3c5be563d29d5e3b246e18b9e5e6f1edc3bb7a9c03b139042c911a753b45f1b0"
# Equals the reader that produced 167 of 398 (.local/evaluation/scan-revision/new/config.json).
BASE_SOURCE_FINGERPRINT = "9e5bc7772a72c25e7435f31d779913e73335a63a0c3b6f5239f47ccfb94de54d"
FROZEN_FINGERPRINT = FINGERPRINT
# Canonical seal digests of the two baseline runs sealed on 2026-11-14 (docs/scan-next-protocol.md).
# Checked whenever the work directory is the default one or the manifest is the frozen one.
BASELINE_SEALS = {
    "before": "412ddb3f9ea6297ce8d81a26ff45a320167a7b2ed4662a28b73395f9f8767a3a",
    "before-repeat": "6310e14408bbdc47163919f5df241dabf7b79982d3647b7ef08fedef97bab2ca",
}

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
# Frozen drawings with a per-drawing file of the 13 November bedroom gate, derived from file NAMES under
# GATE_DIR only (no file there and no row of the gate table is opened): 40 of 72, digest of the sorted paths.
GATE_MEMBERS = dict(count=40, sha256="4079fae7fb74d174851092c2ab536b44bdc0b79c505c559ebd7c99bd711d874b")
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
    "paired": dict(gained_exact=15, lost_exact=4, newly_answered=6, newly_answered_exact=6),
    "accuracy_when_answered": dict(old=0.6667, new=0.6958),
    "mae_both_answered": dict(old=0.966, new=0.795),
    "mae_objects": dict(old=1.254, new=1.028),
    "delta_pp": 2.76,
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
    check(arm in AFTER_ARMS, "Only the arms " + ", ".join(BASELINE_ARMS + AFTER_ARMS) + " can run.")
    check(AFTER_REVISION is not None, "AFTER_REVISION is not pinned; commit the frozen candidate's full SHA first.")
    check(FULL_SHA.match(AFTER_REVISION) and AFTER_REVISION != BASE, "AFTER_REVISION must be a full SHA, not the baseline.")
    check(revision_ref and revision_ref != "working", "This arm needs --revision <committed revision>.")
    commit = resolve(revision_ref)
    check(commit == AFTER_REVISION, "The after arms are pinned to AFTER_REVISION " + AFTER_REVISION)
    return commit


def data_assets(commit):
    """Tracked non-Python files under scripts/ at a candidate revision (reader data assets)."""
    out = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--name-only", commit, "scripts/"], cwd=ROOT)
    return sorted(n for n in out.decode().split("\0") if n and not n.endswith(".py"))


@contextmanager
def offline():
    def refuse(*args, **kwargs):
        raise AssertionError(GUARDS[0])

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
    for name in RUN_RECORDS:  # absent from the two arms sealed before these records existed
        if (work / arm / name).exists():
            seal[name.removesuffix(".json") + "_sha256"] = sha((work / arm / name).read_bytes())
    return rows, seal, config


def pinned(work, manifest):
    """True for the real evaluation: the default work directory or the frozen manifest."""
    return Path(work).resolve() == WORK.resolve() or fingerprint_of(manifest) == FROZEN_FINGERPRINT


def verify_arm(work, manifest, arm):
    """Recompute an arm seal from its files; refuse unless it equals the saved seal."""
    root = work / arm
    check((root / "seal.json").is_file(), "Missing sealed arm: " + arm)
    rows, seal, config = seal_of(work, manifest, arm)
    check(seal == json.loads((root / "seal.json").read_text()), "Broken arm seal: " + arm)
    if arm in BASELINE_SEALS and pinned(work, manifest):
        check(sha(canonical(seal)) == BASELINE_SEALS[arm], "Not the baseline sealed on 2026-11-14: " + arm)
    check(config["manifest_sha256"] == fingerprint_of(manifest), "Arm ran on a different manifest: " + arm)
    for name, digest in config["source_sha256"].items():
        check(sha((root / "src" / name).read_bytes()) == digest, "Snapshot file changed: " + name)
    return rows, seal, config


def deferral(method, exc, elapsed):
    return dict(status="abstained", answer=None, evidence=[], method=method,
                reason=(type(exc).__name__ + ": " + str(exc))[:220], elapsed_ms=elapsed)


def checked_report(reader, report, question, digest, elapsed):
    """nemotron.parse_count as before, plus the product's two extra rules for answered reports."""
    result = revision.normalize(reader, report, question, digest, elapsed)
    if result["status"] == "answered":
        check(report.get("coordinate_system") == COORDS, "Answered report without the 0-1000 top-left coordinates.")
        coverage = report.get("coverage_evidence")
        if coverage and result["answer"] == 0:
            reader.nemotron.parse_count(json.dumps(dict(status="answered", answer=len(coverage), evidence=coverage)))
    return result


def read_prompt(reader, image, question, digest):
    """One prompt. A reader exception or an invalid report becomes a recorded deferral, never an abort."""
    started = time.monotonic()
    try:
        report = reader.run(image, question, "", reader.nemotron.MODEL, None)
    except Exception as exc:
        if isinstance(exc, AssertionError) and str(exc) in GUARDS:
            raise  # a network or hosted call is a protocol breach, not a reader failure
        return deferral("reader_error", exc, round(1000 * (time.monotonic() - started)))
    elapsed = round(1000 * (time.monotonic() - started))
    try:
        return checked_report(reader, report, question, digest, elapsed)
    except Exception as exc:
        return deferral("invalid_report", exc, elapsed)


@contextmanager
def timeout_log(entries, where, saved=lambda: None):
    """Pass-through around subprocess.run that records each TimeoutExpired and re-raises it unchanged.

    The readers call subprocess.run for macOS Vision (20 s limit) and Tesseract (20 s; 5 s for the
    language list) and continue with less text when a call expires. Nothing else is altered."""
    real = subprocess.run

    def run(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        except subprocess.TimeoutExpired as exc:
            command = args[0] if args else kwargs.get("args")
            program = command[0] if isinstance(command, (list, tuple)) and command else command
            entries.append(dict(program=Path(str(program)).name, timeout_s=exc.timeout,
                                at=datetime.now(timezone.utc).isoformat(timespec="seconds"), **where))
            saved()
            raise

    with patch.object(subprocess, "run", run):
        yield


def load_average():
    return [round(x, 2) for x in os.getloadavg()]


def uptime():
    return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()


def wait_for_load(limit=LOAD_LIMIT, wait=LOAD_WAIT, poll=30, load=load_average, sleep=time.sleep,
                  clock=time.monotonic):
    """Wait until the 1-minute load average is below limit, at most wait seconds; then go on regardless."""
    started = clock()
    while load()[0] >= limit and clock() - started < wait:
        print(f"Load {load()[0]} >= {limit}; waiting ({clock() - started:.0f} of {wait} s)", flush=True)
        sleep(poll)
    return dict(limit=limit, max_wait_s=wait, waited_s=round(clock() - started), met=load()[0] < limit)


def infer(reader, manifest, inputs, root, arm, timeouts=None):
    started_all = time.monotonic()
    timeouts = [] if timeouts is None else timeouts
    drawings = defaultdict(list)
    for q in manifest["rows"]:
        drawings[q["path"]].append(q)
    where = {}
    log = lambda: save(root / "timeouts.json", timeouts)
    with offline(), patch.object(reader.nemotron, "run", side_effect=AssertionError(GUARDS[1])), \
            timeout_log(timeouts, where, log):
        prompt = 0
        for index, (path, questions) in enumerate(drawings.items(), 1):
            image = inputs / Path(path).name
            digest = sha(image.read_bytes())
            for q in questions:
                prompt += 1
                check(q["image_sha256"] == digest, "Staged source image mismatch.")
                output = root / "outputs" / (q["id"] + ".json")
                if output.exists():
                    continue
                where.update(prompt=prompt, id=q["id"], drawing=index)
                result = read_prompt(reader, image, q["question"], digest)
                save(output, dict(id=q["id"], question=q["question"], image_sha256=digest, **result))
            print(f"{arm} drawing {index}/{len(drawings)}; {time.monotonic() - started_all:.1f}s; "
                  f"time-outs {len(timeouts)}", flush=True)
    log()
    return timeouts


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
    check(args.arm not in BASELINE_SEALS or not pinned(args.work, manifest),
          "The sealed baseline arm " + args.arm + " is missing; restore it, never run it again.")
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
        if args.arm not in BASELINE_SEALS:
            # Fail before inference if the arm could not be paired with the sealed baseline.
            _, _, baseline = verify_arm(args.work, manifest, "before")
            check_pair((baseline, config))
        if (root / "config.json").exists():
            check(config == json.loads((root / "config.json").read_text()), "Arm configuration mismatch.")
        else:
            save(root / "config.json", config)
        conditions = json.loads((root / "conditions.json").read_text()) if (root / "conditions.json").exists() else []
        timeouts = json.loads((root / "timeouts.json").read_text()) if (root / "timeouts.json").exists() else []
        session = dict(load_wait=wait_for_load(args.max_load, args.load_wait),
                       started=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       uptime_start=uptime(), load_start=load_average(), harness=harness_identity(),
                       prompts_already_sealed=len(list((root / "outputs").glob("*.json"))))
        print("Run conditions:", json.dumps(session), flush=True)
        save(root / "conditions.json", conditions + [session])  # an interrupted session stays on record
        started = time.monotonic()
        infer(reader, manifest, args.work / "inputs", root, args.arm, timeouts)
        session.update(ended=datetime.now(timezone.utc).isoformat(timespec="seconds"), uptime_end=uptime(),
                       load_end=load_average(), wall_seconds=round(time.monotonic() - started, 1),
                       timeouts_total=len(timeouts))
        save(root / "conditions.json", conditions + [session])
        check(not foreign_modules(package), "Reader modules loaded outside the snapshot.")
        _, seal, _ = seal_of(args.work, manifest, args.arm)
        save(root / "seal.json", seal)
        for path in [root / "config.json", root / "seal.json", *(root / n for n in RUN_RECORDS),
                     *sorted((root / "outputs").glob("*.json"))]:
            path.chmod(0o444)
        verify_arm(args.work, manifest, args.arm)
        print("Sealed", args.arm, sha(canonical(seal)), flush=True)
        print(f"Time-outs logged in {args.arm}: {len(timeouts)}"
              + (f"; run `settle --arm {args.arm}` (protocol addendum, rule R4)" if timeouts else ""), flush=True)
        return seal


def verify(args, manifest):
    """Structure only: seal, schema and statuses. Prints no prediction values or distributions."""
    rows, seal, config = verify_arm(args.work, manifest, args.arm)
    statuses = {r["status"] for r in rows.values()}
    check(statuses <= {"answered", "unknown", "abstained"}, "Unexpected status.")
    check(set(rows) == {q["id"] for q in manifest["rows"]}, "Arm does not cover the manifest.")
    failures = Counter(r.get("method") for r in rows.values() if r.get("method") in HARNESS_DEFERRALS)
    print(
        f"{args.arm}: {len(rows)} records, schema valid, seal {sha(canonical(seal))}, "
        f"revision {config['revision']}, sources {seal['source_fingerprint']}, "
        f"harness deferrals: " + ", ".join(f"{m} {failures[m]}" for m in HARNESS_DEFERRALS) + ", "
        f"time-outs: {len(logged) if (logged := timeout_entries(args.work / args.arm)) is not None else 'not logged'}"
    )
    return seal


def timeout_entries(root):
    path = root / "timeouts.json"
    return json.loads(path.read_text()) if path.exists() else None


def settle(args, manifest):
    """Apply the pre-registered time-out rule to a sealed arm without opening its answers.

    A run that logged a time-out is set aside (renamed <arm>.set-aside, never scored) and the arm is run
    again from scratch once. If the second run also logged time-outs, the run with fewer stands; on a
    tie the first run stands. Returns the exit status: 0 settled, 2 run the arm again."""
    arm, work = args.arm, args.work
    check(arm in BASELINE_ARMS + AFTER_ARMS and arm not in BASELINE_SEALS, "settle applies to new arms only.")
    record = work / f"settle-{arm}.json"
    aside, second = work / (arm + ".set-aside"), work / (arm + ".second-run")
    if record.exists() and json.loads(record.read_text()).get("standing"):
        print(f"{arm}: already settled; {json.dumps(json.loads(record.read_text()))}")
        return 0
    _, seal, _ = verify_arm(work, manifest, arm)
    check("timeouts_sha256" in seal, "This arm has no sealed time-out log.")
    count = len(timeout_entries(work / arm))
    if not aside.exists():
        if not count:
            save(record, dict(arm=arm, runs=1, first_run_timeouts=0, standing="first"))
            print(f"{arm}: no time-outs; the run stands.")
            return 0
        (work / arm).rename(aside)
        save(record, dict(arm=arm, runs=1, first_run_timeouts=count, first_run_seal=sha(canonical(seal))))
        print(f"{arm}: {count} time-outs; set aside unseen as {aside.name}. Run --arm {arm} again from scratch once.")
        return 2
    first = timeout_entries(aside)
    check(sha((aside / "timeouts.json").read_bytes()) == json.loads((aside / "seal.json").read_text())["timeouts_sha256"],
          "The set-aside run's time-out log changed.")
    standing = "second" if len(first) > count else "first"
    if standing == "first":
        (work / arm).rename(second)
        aside.rename(work / arm)
        verify_arm(work, manifest, arm)
    kept = timeout_entries(work / arm)
    result = dict(json.loads(record.read_text()), runs=2, second_run_timeouts=count, standing=standing,
                  standing_timeouts=len(kept), affected_prompts=sorted({e["id"] for e in kept}))
    save(record, result)
    print(f"{arm}: first run {len(first)} time-outs, second run {count}; the {standing} run stands "
          f"({len(kept)} time-outs on {len(result['affected_prompts'])} prompts).")
    return 0


def check_settled(work, arm):
    """Before scoring: a new arm has a sealed time-out log, and any time-out went through settle."""
    logged = timeout_entries(work / arm)
    check(logged is not None, "No time-out log for " + arm)
    record = work / f"settle-{arm}.json"
    settled = json.loads(record.read_text()) if record.exists() else {}
    check(not logged or settled.get("runs") == 2, f"{arm} logged time-outs; run settle and the second run first.")
    return dict(timeouts=len(logged), prompts=sorted({e["id"] for e in logged}), settle=settled or None)


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


def agreement(work, manifest, arms):
    """Agreement between two sealed runs of one reader; counts only."""
    check(arms and len(arms) == 2 and arms[0] != arms[1], "Name two different arms with --arms.")
    first, _, c1 = verify_arm(work, manifest, arms[0])
    second, _, c2 = verify_arm(work, manifest, arms[1])
    check(c1["revision"] == c2["revision"], "noise compares two runs of one revision only.")
    pairs = [(first[i], second[i]) for i in first]
    return dict(
        arms=list(arms),
        questions=len(first),
        identical_configuration=c1 == c2,
        answers_differing=sum((a["status"], a["answer"]) != (b["status"], b["answer"]) for a, b in pairs),
        statuses_differing=sum(a["status"] != b["status"] for a, b in pairs),
        evidence_lists_differing=sum(a["evidence"] != b["evidence"] for a, b in pairs),
        methods_differing=sum(a.get("method") != b.get("method") for a, b in pairs),
    )


def noise(args, manifest):
    result = agreement(args.work, manifest, args.arms)
    save(args.work / ("noise-%s-%s.json" % tuple(args.arms)), result)
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


def style_weighted(records, styles):
    """Mean over styles of exact/questions per arm, with the paired difference in points."""
    present = [s for s in styles if any(r["style"] == s for r in records)]
    weighted = {}
    for arm, key in (("before", "old"), ("after", "new")):
        shares = []
        for s in present:
            rows = [r for r in records if r["style"] == s]
            shares.append(sum(r[key]["correct"] for r in rows) / len(rows))
        weighted[arm] = round(sum(shares) / len(shares), 4) if shares else None
    delta = round(100 * (weighted["after"] - weighted["before"]), 2) if present else None
    return dict(weighted, delta_pp=delta, styles=present)


def summarize(records, styles, seed):
    by_style = {s: paired([r for r in records if r["style"] == s], seed) for s in styles}
    comparable = [r for r in records if r["category"] in COMPARABLE]
    return dict(
        overall=paired(records, seed),
        comparable_eleven_families=paired(comparable, seed),
        equal_style_weighted_exact_accuracy=style_weighted(records, styles),
        # The figure set beside the 24 + 24 cohort: eleven families, both styles weighted equally.
        comparable_equal_style_weighted_exact_accuracy=style_weighted(comparable, styles),
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
        harness_deferrals=[
            dict(brief(r), **{arm: dict(method=r[key].get("method"), reason=r[key].get("reason"))
                              for arm, key in (("before_record", "old"), ("after_record", "new"))})
            for r in records
            if r["old"].get("method") in HARNESS_DEFERRALS or r["new"].get("method") in HARNESS_DEFERRALS
        ],
    )


def gate_members(manifest):
    """Frozen drawings with a 13 November gate file, from the file names alone."""
    gates = ROOT / GATE_DIR
    names = {p.name for p in gates.iterdir()} if gates.is_dir() else set()
    return sorted({r["path"] for r in manifest["rows"] if Path(r["path"]).stem + ".json" in names})


def gate_sensitivity(records, members, seed):
    """Descriptive: the primary endpoint and exact/wrong/deferred counts with and without a gate record."""
    members = set(members)
    out = {}
    for label, inside in (("with_13_november_gate_record", True), ("without_13_november_gate_record", False)):
        subset = [r for r in records if (r["path"] in members) == inside]
        out[label] = dict(drawings=len({r["path"] for r in subset}), **(paired(subset, seed) or {}))
    return out


def harness_identity():
    """Which harness ran a command: file digest, checkout commit and whether the file is committed as is."""
    here = Path(__file__).resolve()
    git = lambda *a: subprocess.run(["git", *a], cwd=here.parent, capture_output=True, text=True).stdout.strip()
    return dict(sha256=sha(here.read_bytes()), commit=git("rev-parse", "HEAD"),
                uncommitted_changes=bool(git("status", "--porcelain", "--", here.name)))


def check_pair(configs):
    for label in ("weights_sha256", "detector_source", "detector_revision", "environment", "network", "manifest_sha256"):
        check(configs[0][label] == configs[1][label], "Arm configuration differs: " + label)


def score(args, manifest):
    fingerprint = fingerprint_of(manifest)
    check(FINGERPRINT is None or fingerprint == FINGERPRINT, "Changed scan-next manifest.")
    check(args.before == "before", "The comparator is the sealed arm 'before'; no other before arm is scored.")
    check(args.after == "after", "Only the arm 'after' is scored; after-repeat is a noise floor.")
    check(AFTER_REVISION is not None, "AFTER_REVISION is not pinned.")
    # Verify both seals before the sponsor answers are opened.
    before, bseal, bconfig = verify_arm(args.work, manifest, args.before)
    after, aseal, aconfig = verify_arm(args.work, manifest, args.after)
    check(bconfig["revision"] == BASE, "The before arm is not the pinned baseline.")
    check(
        BASE_SOURCE_FINGERPRINT is None or bseal["source_fingerprint"] == BASE_SOURCE_FINGERPRINT,
        "Unexpected baseline sources.",
    )
    check(aconfig["revision"] == AFTER_REVISION, "The after arm is not at AFTER_REVISION.")
    for name, digest in aconfig["source_sha256"].items():
        check(sha(revision.source_bytes(aconfig["revision"], name)) == digest, "After-arm source differs from Git: " + name)
    check_pair((bconfig, aconfig))
    # The control and repeat runs (protocol addendum) are sealed, paired and settled before scoring too.
    control, cseal, cconfig = verify_arm(args.work, manifest, "before-control")
    repeat, rseal, rconfig = verify_arm(args.work, manifest, "after-repeat")
    check(cconfig["revision"] == BASE and (BASE_SOURCE_FINGERPRINT is None
                                           or cseal["source_fingerprint"] == BASE_SOURCE_FINGERPRINT),
          "before-control is not the pinned baseline reader.")
    check(rconfig["revision"] == AFTER_REVISION, "after-repeat is not at AFTER_REVISION.")
    check_pair((bconfig, cconfig))
    check_pair((bconfig, rconfig))
    timeouts = {arm: check_settled(args.work, arm) for arm in ("before-control", "after", "after-repeat")}
    scorings = json.loads((args.work / "scorings.json").read_text()) if (args.work / "scorings.json").exists() else []
    check(not scorings or args.rescore, "This cohort was scored on %s; a second scoring needs --rescore and is "
          "recorded in the summary." % scorings[-1]["scored"] if scorings else "")
    seals = {"before": bseal, "before-control": cseal, "after": aseal, "after-repeat": rseal}
    seal_sha256 = {k: sha(canonical(v)) for k, v in seals.items()}
    scorings.append(dict(
        scored=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        harness=harness_identity(),
        arms=dict(before=args.before, after=args.after),
        seal_sha256=seal_sha256,
        rescore=bool(args.rescore),
    ))
    save(args.work / "scorings.json", scorings)  # written before the sponsor answers are opened
    floors = {
        "before vs before-control (baseline under the after arm's conditions)":
            agreement(args.work, manifest, ["before", "before-control"]),
        "after vs after-repeat (candidate repeat)": agreement(args.work, manifest, ["after", "after-repeat"]),
    }
    if (args.work / "before-repeat/seal.json").exists():  # descriptive; already in noise-before-before-repeat.json
        floors["before vs before-repeat (sealed baseline repeat)"] = agreement(args.work, manifest,
                                                                              ["before", "before-repeat"])
    members = gate_members(manifest)
    if fingerprint == FROZEN_FINGERPRINT:
        check(dict(count=len(members), sha256=sha(canonical(members))) == GATE_MEMBERS, "Gate-file membership changed.")
    targets = revision.read_targets(args.archive, manifest)
    records = join(manifest, before, after, targets)
    summary = summarize(records, QUOTAS, SEED)
    against_control = paired(join(manifest, control, after, targets), SEED)
    control_differs = floors["before vs before-control (baseline under the after arm's conditions)"]["answers_differing"] > 0
    low, low_control = summary["overall"]["clustered_bootstrap_delta_pp_95"][0], against_control["clustered_bootstrap_delta_pp_95"][0]
    seconds = {arm: round(sum(r["elapsed_ms"] for r in rows.values()) / 1000, 2)
               for arm, rows in (("before-control", control), ("after", after), ("after-repeat", repeat))}
    out = dict(
        observed_date=datetime.now(timezone.utc).date().isoformat(),
        protocol="docs/scan-next-protocol.md",
        manifest_sha256=fingerprint,
        arms=dict(before=args.before, after=args.after),
        scope="Original PNG and original English count question; offline local readers only; a hosted hand-off is a deferral.",
        drawings=manifest["images"],
        questions=len(records),
        seals=seals,
        seal_sha256=seal_sha256,
        configurations={"before": bconfig, "before-control": cconfig, "after": aconfig, "after-repeat": rconfig},
        scorings=scorings,
        claim=dict(
            rule="Improvement only if the primary interval's lower end is above zero against 'before' and, when "
                 "before-control differs from before in any answer, also against before-control.",
            lower_end_against_before=low,
            before_control_differs_from_before=control_differs,
            lower_end_against_before_control=low_control,
            improvement_shown=low > 0 and (not control_differs or low_control > 0),
        ),
        primary_endpoint_against_before_control=against_control,
        noise_floors=floors,
        timeouts=dict(timeouts, **{arm: "not logged (sealed before the log existed)" for arm in BASELINE_SEALS}),
        **summary,
        gate_sensitivity=gate_sensitivity(records, members, SEED),
        timing=dict(
            note="before-control and after ran back to back under recorded conditions; the sealed before arm is "
                 "not a timing reference.",
            inference_seconds=seconds,
            after_over_before_control=round(seconds["after"] / seconds["before-control"], 3) if seconds["before-control"] else None,
            run_conditions={arm: json.loads((args.work / arm / "conditions.json").read_text())
                            for arm in ("before-control", "after", "after-repeat")},
        ),
    )
    save(args.work / "paired-rows.json", records)
    save(args.work / "summary.json", out)
    if args.report:
        save(args.report, out)
    print(json.dumps(dict(claim=out["claim"], overall=out["overall"],
                          equal_style=out["equal_style_weighted_exact_accuracy"]), indent=2))
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
        scratch_missing=[str(p) for p in scratch if not p.exists()],
        findings=findings,
        checked=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    save(args.work / ("leak-check-" + commit[:12] + ".json"), report)
    if findings:
        for f in findings:
            print("LEAK", f["where"], ", ".join(f["paths"])[:200], f"({len(f['hits'])} fresh identifiers)")
        sys.exit(1)
    missing = f" ({len(report['scratch_missing'])} missing)" if report["scratch_missing"] else ""
    print(f"No fresh drawing names or image hashes in {commit} or {len(scratch)} scratch directories{missing}.")


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
    for arm, label in (("old", "before"), ("new", "after")):
        compare(f"{arm} accuracy when answered", PUBLISHED["accuracy_when_answered"][arm],
                overall[label]["accuracy_when_answered"])
        compare(f"{arm} mean absolute error, both answered", PUBLISHED["mae_both_answered"][arm],
                overall["mean_absolute_error_on_both_answered"][label])
        compare(f"{arm} mean absolute error, object counts", PUBLISHED["mae_objects"][arm],
                summary["by_group"]["objects"]["mean_absolute_error_on_both_answered"][label])
    compare("paired difference pp", PUBLISHED["delta_pp"], overall["delta_exact_pp"])
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
        choices=["audit", "freeze", "prepare", "run", "verify", "settle", "identity", "noise", "leak-check",
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
    p.add_argument("--arms", nargs=2, help="The two runs of one revision that noise compares")
    p.add_argument("--before", default="before")
    p.add_argument("--after", default="after")
    p.add_argument("--revision", help="Committed revision for a non-baseline arm or the leak check")
    p.add_argument("--source", action="append", default=[], help="Extra non-imported reader asset under scripts/")
    p.add_argument("--scratch", action="append", help="Directory for the leak check (default: implementers' scratch)")
    p.add_argument("--no-scratch", action="store_true")
    p.add_argument("--references", type=Path, help="Upstream-format ZIP with model.svg, F1_scaled.png, F1_original.png")
    p.add_argument("--report", type=Path)
    p.add_argument("--rescore", action="store_true", help="Allow a second scoring; it is recorded in the summary")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--max-load", type=float, default=LOAD_LIMIT, help="run: start once the 1-minute load is below this")
    p.add_argument("--load-wait", type=int, default=LOAD_WAIT, help="run: seconds to wait for that load, then go on")
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
    elif a.action == "settle":
        sys.exit(settle(a, m))
    else:
        actions[a.action](a, m)


if __name__ == "__main__":
    main()
