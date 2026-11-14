"""Freeze, run and score a paired, image-only CubiCasa scan holdout.

freeze requires the official split text files and predevelopment exclusion inventory.
inputs extracts just the frozen questions and exact original PNGs, without any labels.
run baseline/candidate requires an explicit authenticated --run. score is entirely offline.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import random
import time
from zipfile import ZipFile

from benchmark_full_english import ARCHIVE, BEDROOM, MANIFEST, ROOT
from benchmark_hosted_counts import ObservedHTTP, Pacer
import nemotron

WORK = ROOT / ".local/evaluation/scan-holdout"
FROZEN = ROOT / "docs/scan-holdout-inputs.json"
SEED = "planproof-upstream-test-2026-11-14-v1"
BASE = "d9a440dd5bec10c1ae2828de6e0104f3034390e8"
SPLITS = {"train": "80904159dfc4a732db9d8f77dbdd6374f74789986d9b3d4a4040b84268dc61e6",
          "val": "0a3b54194a383930d61f48d2f157c8e866de2b7d9aa7a01ce21571eccf6eb7c3",
          "test": "3997ee6378007f10e945b2621921127477530abe8f8c053f43e327a365f5ce5a"}
QUOTAS = {"colorful": 1, "high_quality": 15, "high_quality_architectural": 16}
NAMES = ("bedrooms", "doors", "windows", "floors", "toilet bowls", "sinks", "showers", "saunas",
         "kitchens", "bathrooms", "separate WC rooms", "balconies")
PREFIX = "junction-dataset/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stable(*parts):
    return sha("|".join(parts).encode())


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".partial")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    pending.replace(path)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def category(q):
    return next((x for x in NAMES if q.startswith("How many " + x + " ")), None)


def style(path):
    return Path(path).stem.rsplit("-", 1)[0]


def load_prompts(z):
    raw = z.read(PREFIX + "questions.jsonl")
    check(sha(raw) == MANIFEST, "Different sponsor question release.")
    groups = defaultdict(dict)
    for line in raw.splitlines():
        # Intentionally project the two public inference fields; values and units do not enter selection.
        item = json.loads(line)
        path, question = item["path"], item["question"]
        if path.startswith("data/cubicasa5k/") and question.startswith("How many "):
            group = category(question)
            check(group and group not in groups[path], "Unexpected prompt template or duplicate prompt.")
            groups[path][group] = question
    return groups


def freeze(archive, split_dir, exclusions, destination):
    split = {}
    for name, digest in SPLITS.items():
        raw = (split_dir / (name + ".txt")).read_bytes()
        check(sha(raw) == digest, "Different official split: " + name)
        split[name] = {"data/cubicasa5k/" + line.strip("/").replace("/", "-") + ".png"
                       for line in raw.decode().splitlines()}
    check(not (split["test"] & (split["train"] | split["val"])), "Overlapping upstream split.")
    excluded = json.loads(exclusions.read_text())
    if "excluded" in excluded:
        excluded = excluded["excluded"]
    excluded_paths = {path for group in excluded.values() for path in group}
    with ZipFile(archive) as z:
        prompts = load_prompts(z)
        pool = (set(prompts) & split["test"]) - excluded_paths
        paths = []
        for name, n in QUOTAS.items():
            all_style = sorted((p for p in pool if style(p) == name and len(prompts[p]) >= 3),
                               key=lambda p: stable(SEED, "drawing", p))
            check(len(all_style) >= n, "Not enough fresh drawings for " + name)
            paths += all_style[:n]
        # Assign the least represented *available* category first, breaking ties by seed.
        # Each drawing receives three different original questions, without inspecting target counts.
        counts = Counter()
        rows = []
        selected = sorted(paths, key=lambda p: stable(SEED, "prompt-order", p))
        for path in selected:
            picture = sha(z.read(PREFIX + path))
            choices = sorted(prompts[path], key=lambda g: (counts[g], stable(SEED, path, g)))[:3]
            for group in choices:
                counts[group] += 1
                q = prompts[path][group]
                rows.append(dict(id=stable(path, q)[:16], path=path, style=style(path), category=group,
                                 question=q, image_sha256=picture))
        check(set(counts) == set(NAMES), "One or more target categories absent.")
    manifest = dict(protocol=1, seed=SEED, base_revision=BASE, source_questions_sha256=MANIFEST,
                    official_splits={"source": "https://zenodo.org/records/2613548", "sha256": SPLITS},
                    excluded={k:sorted(v) for k,v in excluded.items()},
                    style_quotas=QUOTAS, eligible_by_style=dict(Counter(style(x) for x in pool)),
                    questions_by_category=dict(sorted(counts.items())), rows=rows)
    if destination.exists():
        check(json.loads(destination.read_text()) == manifest, "Refusing to replace a different frozen manifest.")
    else:
        save(destination, manifest)
    return manifest


def load_frozen(path):
    m = json.loads(path.read_text())
    rows = m["rows"]
    check(len(rows) == 96 and len({r["path"] for r in rows}) == 32 and len({r["id"] for r in rows}) == 96
          and all(r["id"] == stable(r["path"], r["question"])[:16] and category(r["question"]) == r["category"]
                  and set(r) == {"id","path","style","category","question","image_sha256"} for r in rows),
          "Invalid frozen inference manifest.")
    return m


def stage_inputs(m, archive, work):
    out = work / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as z:
        for path, expected in {r["path"]:r["image_sha256"] for r in m["rows"]}.items():
            raw = z.read(PREFIX + path)
            check(sha(raw) == expected, "Different original drawing.")
            dest = out / Path(path).name
            if not dest.exists() or sha(dest.read_bytes()) != expected:
                dest.write_bytes(raw)
    save(out / "questions.json", m["rows"])
    return out


FINGERPRINT = "37c2984cafd660f1e052b8679aa488caf09b5bf963fabac2cffcca4c6a6744ac"
BASE_IMAGE_CLIENT = "0e1e4172a27d5aa381b376ced9cb4392174f6eeb8084871bd4f31aebc76650be"
URL = "https://integrate.api.nvidia.com/v1"


def baseline_reader(work):
    source = subprocess.check_output(["git", "show", BASE + ":scripts/nemotron.py"], cwd=ROOT)
    check(sha(source) == BASE_IMAGE_CLIENT, "Different original baseline client.")
    path = work / "baseline_nemotron.py"
    if not path.exists() or path.read_bytes() != source:
        path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("frozen_scan_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate(row, root):
    entry = json.loads((root / (Path(row["path"]).stem + ".json")).read_text())
    check(entry["image_sha256"] == row["image_sha256"] and entry["path"] == row["path"]
          and entry["status"] == "unknown" and entry["method"] in
          {"grayscale_invariant","no_eligible_green_span","no_linkable_ocr_box"}, "Incorrect local baseline or unanticipated model-eligible bedroom.")
    return dict(status="unknown", answer=None, evidence=[], method=entry["method"],
                reason="Original local whole-sheet bedroom route could not link the required evidence.",
                image_sha256=entry["image_sha256"], question=row["question"], usage=None, latency_ms=None)


def read_arm(work, name, rows):
    directory = work / name
    seal = json.loads((directory / "seal.json").read_text())
    data = []
    for row in rows:
        r = json.loads((directory / (row["id"] + ".json")).read_text())
        check(r["id"] == row["id"] and r["path"] == row["path"] and r["question"] == row["question"]
              and r["image_sha256"] == row["image_sha256"], "Prediction binding mismatch.")
        data.append(r)
    check(seal["predictions_sha256"] == sha(canonical(data)) and seal["manifest_sha256"] == FINGERPRINT,
          "Invalid prediction seal.")
    return data, seal


def totals_by_route(reports):
    totals = defaultdict(Counter)
    for row in reports:
        bucket = totals[row["method"]]
        bucket["rows"] += 1
        if row.get("reused_original"):
            bucket["replayed"] += 1
        elif row.get("provider_host"):
            bucket["hosted_requests_with_final_record"] += 1
            if row["status"] != "unavailable":
                bucket["inference_responses"] += 1
            else:
                bucket["transport_unavailable"] += 1
            bucket.update({k:v for k,v in (row.get("usage") or {}).items() if k in ("prompt_tokens","completion_tokens","total_tokens")})
    return {method:dict(stats) for method,stats in sorted(totals.items())}


def scrub(result, token):
    result.pop("gold", None)
    for field in ("reason", "served_model"):
        if token and isinstance(result.get(field), str):
            result[field] = result[field].replace(token, "[redacted]")
    for box in result.get("evidence", []):
        if token and isinstance(box.get("label"), str):
            box["label"] = box["label"].replace(token, "[redacted]")
    return result


def uses_direct_fallback(client, image, question):
    # Called while preparing the queue, before threads start. Both provider branches
    # are disabled. This identifies the fallback only; local evidence takes precedence.
    from unittest.mock import patch
    with patch.object(client.scan_rooms, "predict", return_value=None), \
            patch.object(client.scan_objects, "predict", return_value=None), \
            patch.object(client, "hosted_count", return_value={"method": "fresh_direct"}), \
            patch.object(client.nemotron, "run", return_value={"method": "unchanged_original"}):
        result = client.run(image, question, URL, nemotron.MODEL, "offline-route-probe")
    check(result["method"] in {"fresh_direct", "nemotron_original"}, "Unexpected candidate fallback.")
    return result["method"] == "fresh_direct"


def infer(args, row, folder, client, pacer, key):
    picture = folder / Path(row["path"]).name
    check(sha(picture.read_bytes()) == row["image_sha256"], "Different staged pixels.")
    if args.arm == "baseline" and row["category"] == "bedrooms":
        r = gate(row, args.gates)
    else:
        r = None
        max_attempts = 1 if args.record_failures else 3
        for attempt in range(1, max_attempts + 1):
            if not args.replay_only and not pacer.permit():
                return None
            if args.arm == "baseline":
                observed = ObservedHTTP()
                r = client.run(picture, row["question"], URL, nemotron.MODEL, key, timeout=args.timeout, opener=observed)
                code, quota, retry_after = observed.code, observed.quota, observed.retry_after
                r["method"] = "original_full_image"
            else:
                prior = None
                saved_prior = args.work/"baseline"/(row["id"]+".json")
                if row["category"] != "bedrooms" and saved_prior.exists():
                    prior = json.loads(saved_prior.read_text())
                    check(prior["method"] == "original_full_image" and prior["image_sha256"] == row["image_sha256"]
                          and prior["question"] == row["question"], "Old report does not match the unchanged request.")
                    if prior["status"] == "unavailable" and row["id"] in args.unchanged_outages:
                        # The dispatcher confirmed an identical hosted fallback. A one-step
                        # run must still give the real local readers the chance to answer.
                        local = client.run(picture, row["question"], "", nemotron.MODEL, None, timeout=args.timeout)
                        if local["status"] == "answered":
                            r = local
                            break
                        check(local["status"] == "unavailable", "Unexpected local-only result.")
                        return {**prior, "id":row["id"], "path":row["path"], "method":"nemotron_original",
                                "reused_original":True, "reader_version":client.VERSION,
                                "origin":"Shared unavailable original request"}
                if args.replay_only:
                    from unittest.mock import patch
                    # If the immutable product no longer accepts this replay, fail locally.
                    # Neither the placeholder credential nor any request may reach a provider.
                    with patch.object(client.nemotron, "run", side_effect=AssertionError("Unexpected new request during exact replay.")):
                        r = client.run(picture,row["question"],URL,nemotron.MODEL,"offline-replay",timeout=300,baseline_report=prior)
                else:
                    r = client.run(picture, row["question"], URL, nemotron.MODEL, key, timeout=args.timeout, baseline_report=prior)
                if r.get("method") == "nemotron_original" and prior is not None:
                    # Data copied from an old call must retain its prediction and evidence verbatim.
                    check(all(r.get(k)==prior.get(k) for k in ("status","answer","evidence","timestamp","image_sha256")),
                          "Reused original result differs.")
                    r["reused_original"] = True
                elif r.get("method") == "nemotron_original" and prior is None and args.direct_only:
                    raise RuntimeError("Legacy request entered the fresh fallback queue.")
                match = re.search(r"HTTP ([0-9]{3})", str(r.get("reason","")))
                code, quota, retry_after = (int(match[1]) if match else None), bool(r.get("quota_exhausted")), None
            r = scrub(r, key)
            r["attempts"] = attempt
            if r["status"] != "unavailable":
                break
            if code == 413:
                break
            print(f"{row['id']} attempt={attempt} HTTP={code} quota={quota} retry_after_s={retry_after} reason={str(r.get('reason',''))[:130]}", flush=True)
            # The frozen client reports TLS disconnects, truncated bodies and invalid
            # proxy replies as unavailable without necessarily surfacing an HTTP code.
            # The original pixels, client and endpoint have already been verified.
            transient = code is None or code in (408,425,429) or 500 <= code < 600
            if quota or not transient or (retry_after or 0) > 600:
                pacer.stopped.set()
                kind = "quota exhausted" if quota else ("provider rejected credentials/configuration" if not transient else "provider wait exceeds limit")
                raise RuntimeError(f"{kind}; resumable. HTTP {code}")
            if attempt == max_attempts:
                if retry_after:
                    pacer.backoff(retry_after)
                r["exhausted_transient"] = True
                break
            # Apply a full rate window for shared trial capacity rather than repeatedly probing immediately.
            delay = 30 * attempt if code == 429 else 2 ** attempt
            pacer.backoff(max(retry_after or 0, delay))
    check(r["image_sha256"] == row["image_sha256"] and r["question"] == row["question"]
          and r["status"] in {"answered","unknown","unavailable"}, "Reader changed the input binding or status.")
    if r["status"] != "unavailable":
        validated = nemotron.parse_count(json.dumps(r, allow_nan=False))
        check(validated["answer"] == r["answer"] and len(validated["evidence"]) == len(r["evidence"]), "Bad evidence.")
    return {**r, "id":row["id"], "path":row["path"]}


def run_predictions(args, m):
    check(args.arm and (args.replay_only or (args.run and os.environ.get("NEMOTRON_API_KEY"))),
          "Fresh inference requires --run --arm and NEMOTRON_API_KEY.")
    check(os.environ.get("NEMOTRON_BASE_URL", URL).rstrip("/") == URL, "Only the explicit NVIDIA endpoint is enabled.")
    check(1 <= args.workers <= 6 and 1 <= args.rpm <= 18 and 1 <= args.timeout <= 600,
          "Workers, rate or timeout exceed approved bounds.")
    check(sha(canonical(m)) == FINGERPRINT, "Not the frozen scan holdout.")
    directory = args.work / args.arm
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / "seal.json").exists():
            read_arm(args.work, args.arm, m["rows"])
            print("Arm previously sealed, no requests sent.")
            return
        if args.arm == "baseline":
            client = baseline_reader(args.work)
            fingerprint = dict(baseline_revision=BASE, image_client=BASE_IMAGE_CLIENT)
        else:
            if not args.direct_only and not args.replay_only:
                read_arm(args.work,"baseline",m["rows"])
            sys.path.insert(0, str(ROOT))
            from scripts import scan_reader as client
            fingerprint = candidate_identity(args)
        config = {"manifest_sha256": FINGERPRINT, "arm": args.arm, **fingerprint}
        version = directory / "config.json"
        if version.exists():
            check(json.loads(version.read_text()) == config, "Implementation changed during run.")
        else:
            save(version,config)
        inputs = stage_inputs(m,args.archive,args.work)
        rows = m["rows"]
        if args.replay_only:
            check(args.arm == "candidate", "Only the candidate reuses prior responses.")
            baseline_done = (args.work/"baseline/seal.json").exists()
            rows = [r for r in rows if (args.work/"baseline"/(r["id"]+".json")).exists()
                    and r["category"]!="bedrooms" and (baseline_done or
                    json.loads((args.work/"baseline"/(r["id"]+".json")).read_text())["status"]!="unavailable")]
        args.unchanged_outages = set()
        staged = args.direct_only or args.replay_only
        if staged:
            check(args.arm == "candidate" and (directory/"local-stage.json").exists(), "Fallback stage needs local pass.")
        if args.arm == "candidate":
            selected = []
            for q in rows:
                prior_path = args.work / "baseline" / (q["id"] + ".json")
                outage = q["category"] != "bedrooms" and prior_path.exists() and json.loads(prior_path.read_text())["status"] == "unavailable"
                if staged or outage:
                    direct = uses_direct_fallback(client, inputs / Path(q["path"]).name, q["question"])
                    if outage and not direct:
                        args.unchanged_outages.add(q["id"])
                    if staged and direct != args.direct_only:
                        continue
                selected.append(q)
            rows = selected
        def pending_rows(recovery):
            for row in rows:
                target = directory / (row["id"] + ".json")
                if (not recovery and not target.exists()) or (recovery and target.exists() and
                        json.loads(target.read_text()).get("exhausted_transient") and
                        not json.loads(target.read_text()).get("recovery_round")):
                    yield row
        recovery = False
        todo = iter(pending_rows(recovery))
        pacer = Pacer(args.rpm)
        start = time.monotonic()
        print("Starting", args.arm, "on frozen inputs.", flush=True)
        failure = None
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            active = set()
            def fill(n):
                while len(active) < n and not pacer.stopped.is_set():
                    row = next(todo, None)
                    if row is None:
                        return
                    active.add(pool.submit(infer, args, row, inputs, client, pacer, os.environ.get("NEMOTRON_API_KEY")))
            fill(1)
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        r = future.result()
                    except Exception as exc:
                        failure = failure or exc
                        pacer.stopped.set()
                        continue
                    if r is not None:
                        if recovery:
                            old = json.loads((directory / (r["id"] + ".json")).read_text())
                            r["recovery_round"] = 1
                            r["previous_failed_attempts"] = old.get("attempts")
                        save(directory / (r["id"] + ".json"), r)
                fill(1 if args.replay_only else args.workers)
                if not active and not failure and not recovery and not args.replay_only:
                    recovery = True
                    todo = iter(pending_rows(True))
                    fill(1)
        if failure:
            raise failure
        if args.arm == "candidate":
            check(candidate_identity(args) == fingerprint, "Candidate files changed during inference.")
        if args.direct_only or args.replay_only:
            if not (args.replay_only and (args.work/"baseline/seal.json").exists()
                    and all((directory/(q["id"]+".json")).exists() for q in m["rows"])):
                print("Processed",len(rows),"eligible fallback candidates; full seal deferred until both stages complete.",flush=True)
                return
            rows = m["rows"]
        data = [json.loads((directory/(r["id"]+".json")).read_text()) for r in rows]
        seal = {**config, "predictions_sha256": sha(canonical(data)), "completed": len(data),
                "sealed_at": datetime.now(timezone.utc).isoformat(), "last_run_seconds": round(time.monotonic()-start,2)}
        save(directory/"seal.json",seal)
        print("Sealed",args.arm,len(data),seal["predictions_sha256"],flush=True)


def candidate_identity(args, verify=True):
    """Pin all product scan modules and any externally configured code or weights."""
    names = ["scripts/nemotron.py", "scripts/scan_reader.py", "scripts/scan_objects.py", "scripts/scan_rooms.py"]
    hashes = {name:sha((ROOT/name).read_bytes()) for name in names}
    if args.external_repo:
        from platform import mac_ver
        hashes["macos"] = mac_ver()[0]
        try:
            proc = subprocess.run(["tesseract","--version"],capture_output=True,text=True,timeout=5,check=True)
            hashes["tesseract"] = proc.stdout.splitlines()[0]
        except (OSError,subprocess.SubprocessError):
            hashes["tesseract"] = "unavailable"
    for path in args.artifact:
        check(path.is_file() and path.name not in hashes, "Unusable or ambiguous model artifact.")
        with path.open("rb") as stream:
            hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    for repo in args.external_repo:
        # Hash the actual inference package in addition to the advertised revision.
        revision = subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"], text=True).strip()
        pkg = repo / "floortrans"
        check(pkg.is_dir(), "Missing upstream floortrans package.")
        sources = {p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in sorted(pkg.rglob("*.py"))}
        hashes[repo.name+":git"] = revision
        hashes[repo.name+":python"] = sha(canonical(sources))
    deps = {"python": sys.version.split()[0]}
    for package in ("torch","torchvision","numpy","shapely","opencv-python","opencv-python-headless","scipy"):
        try:
            deps[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    hashes["runtime"] = deps
    identity = sha(canonical(hashes))
    if verify:
        check(args.freeze_id == identity, "Candidate requires exact reviewed --freeze-id " + identity)
    return {"candidate_id":identity, "sha256":hashes}


def metrics(rows):
    statuses = Counter(r["status"] for r in rows)
    correct = sum(r["correct"] for r in rows)
    answered = statuses["answered"]
    return dict(questions=len(rows), correct=correct, wrong=answered-correct, answered=answered,
                unknown=statuses["unknown"], unavailable=statuses["unavailable"],
                correct_pct_all=round(100*correct/len(rows),2), coverage_pct=round(100*answered/len(rows),2),
                precision_pct=round(100*correct/answered,2) if answered else None)


def paired_intervals(records):
    # Resample drawings, keeping all three prompts together. These are descriptive for
    # this style-constrained split; sampling only one colorful drawing limits inference.
    grouped = defaultdict(list)
    for r in records:
        grouped[r["path"]].append(int(r["candidate"]["correct"])-int(r["baseline"]["correct"]))
    draws = [(sum(v),len(v)) for v in grouped.values()]
    randomizer = random.Random(SEED + "-bootstrap")
    sampled = []
    for _ in range(10000):
        resampled = randomizer.choices(draws,k=len(draws))
        delta, eligible = zip(*resampled)
        sampled.append(100*sum(delta)/sum(eligible))
    sampled.sort()
    return [round(sampled[249],2),round(sampled[9749],2)]


def score(args, m):
    check(sha(canonical(m)) == FINGERPRINT, "Unexpected blind manifest.")
    baseline, bseal = read_arm(args.work,"baseline",m["rows"])
    candidate, cseal = read_arm(args.work,"candidate",m["rows"])
    # Open answers only after both complete independently saved inference arms validate.
    keys = {(r["path"],r["question"]) for r in m["rows"]}
    gold = {}
    with ZipFile(args.archive) as z:
        raw = z.read(PREFIX + "questions.jsonl")
        check(sha(raw) == MANIFEST, "Different question release.")
        for line in raw.splitlines():
            row = json.loads(line)
            k = (row["path"],row["question"])
            if k in keys:
                check(k not in gold and row["unit"] == "count" and type(row["answer"]) is int,
                      "Invalid original count.")
                gold[k] = row["answer"]
    check(keys==gold.keys(), "Missing original scores.")
    records = []
    for q, a, b in zip(m["rows"], baseline, candidate, strict=True):
        target = gold[q["path"],q["question"]]
        joined = dict(**q,gold=target)
        for name, v in (("baseline",a),("candidate",b)):
            if v["status"] in ("answered","unknown"):
                validated = nemotron.parse_count(json.dumps(v,allow_nan=False))
                check(validated["answer"] == v["answer"] and len(validated["evidence"]) == len(v["evidence"]),
                      "Invalid saved response.")
            joined[name] = {**v, "correct":v["status"] == "answered" and v["answer"] == target}
        records.append(joined)
    def both(group):
        return {name:metrics([r[name] for r in group]) for name in ("baseline", "candidate")}
    eligible = [r for r in records if "unavailable" not in (r["baseline"]["status"],r["candidate"]["status"])]
    summary = dict(observed_date="2026-11-14", manifest_sha256=FINGERPRINT, baseline_seal=bseal, candidate_seal=cseal,
                   evidence_check_ids=[r["id"] for name in QUOTAS for r in sorted(
                       (r for r in m["rows"] if r["style"]==name),
                       key=lambda r:stable("planproof-evidence-check-v1",r["id"]))[:2]],
                   overall=both(records),
                   common_service_available=both(eligible) if eligible else None,
                   paired_service_exclusions=len(records)-len(eligible),
                   by_category={g:both([r for r in records if r["category"]==g]) for g in NAMES},
                   common_by_category={g:both([r for r in eligible if r["category"]==g])
                                       for g in NAMES if any(r["category"]==g for r in eligible)},
                   by_style={g:both([r for r in records if r["style"]==g]) for g in QUOTAS},
                   gained=sum(not r["baseline"]["correct"] and r["candidate"]["correct"] for r in eligible),
                   lost=sum(r["baseline"]["correct"] and not r["candidate"]["correct"] for r in eligible),
                   clustered_bootstrap_accuracy_delta_pp_95=paired_intervals(eligible) if eligible else None,
                   routes={"baseline":totals_by_route(baseline),"candidate":totals_by_route(candidate)},
                   evidence="Count equality after evidence validation; normalized box presence and uniqueness do not establish object localization accuracy.")
    save(args.work/"paired-rows.json",records)
    save(args.work/"summary.json",summary)
    print(json.dumps(summary["overall"], indent=2))
    return summary


def local_first(args, m):
    check(sha(canonical(m)) == FINGERPRINT, "Not the frozen split.")
    fingerprint = candidate_identity(args)
    sys.path.insert(0,str(ROOT))
    from scripts import scan_reader, scan_objects
    check(scan_objects.available(), "Specialist unavailable in this interpreter.")
    folder = stage_inputs(m,args.archive,args.work)
    directory = args.work/"candidate"
    directory.mkdir(parents=True,exist_ok=True)
    config = {"manifest_sha256": FINGERPRINT, "arm":"candidate", **fingerprint}
    with (directory/"run.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory/"config.json").exists():
            check(json.loads((directory/"config.json").read_text())==config,"Candidate version changed.")
        else:
            save(directory/"config.json",config)
        unresolved = []
        for r in m["rows"]:
            output = directory/(r["id"]+".json")
            if output.exists():
                continue
            source = folder/Path(r["path"]).name
            result = scan_reader.run(source,r["question"],"",nemotron.MODEL,None,timeout=300)
            if result["status"] != "answered":
                unresolved.append(r["id"])
                continue
            valid = nemotron.parse_count(json.dumps(result,allow_nan=False))
            check(valid["answer"]==result["answer"] and result["image_sha256"]==r["image_sha256"]
                  and result["question"]==r["question"],"Invalid local candidate output.")
            save(output,{**result,"path":r["path"],"id":r["id"]})
        check(candidate_identity(args)==fingerprint,"Candidate changed during offline run.")
        save(directory/"local-stage.json", {"unresolved_ids":unresolved,"candidate_id":fingerprint["candidate_id"]})
        print("Local pass complete;",len(unresolved),"rows require hosted/replay.",flush=True)


def run_action(args, m):
    if args.action == "local":
        local_first(args,m)
    elif args.action == "run":
        run_predictions(args,m)
    else:
        score(args,m)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["freeze", "inputs", "local", "run", "candidate-id", "score"])
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--manifest", type=Path, default=FROZEN)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--split-dir", type=Path, default=WORK)
    parser.add_argument("--exclusions", type=Path, default=WORK / "exclusions.json")
    parser.add_argument("--arm", choices=("baseline","candidate"))
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--gates", type=Path, default=ROOT/".local/evaluation/full-english/finnish/gates")
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--direct-only", action="store_true", help="After the local pass, run only new hosted prompts.")
    stage.add_argument("--replay-only", action="store_true", help="Replay completed baseline inputs requiring the identical request.")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--rpm", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--record-failures", action="store_true", help="Try every missing key once before a single end-of-queue retry for transient failures.")
    parser.add_argument("--freeze-id", help="Candidate source/artifact fingerprint agreed before inference.")
    parser.add_argument("--artifact", type=Path, action="append", default=[], help="Pin any external model/code file by SHA-256.")
    parser.add_argument("--external-repo", type=Path, action="append", default=[], help="Pin upstream CubiCasa floortrans source and Git revision.")
    args = parser.parse_args()
    if args.action == "freeze":
        m = freeze(args.archive, args.split_dir, args.exclusions, args.manifest)
        print(f"Frozen {len(m['rows'])} questions; manifest digest {sha(canonical(m))}")
        return
    m = load_frozen(args.manifest)
    if args.action == "candidate-id":
        print(candidate_identity(args, verify=False)["candidate_id"])
        return
    if args.action == "inputs":
        print(stage_inputs(m,args.archive,args.work))
        return
    run_action(args, m)


if __name__ == "__main__":
    main()
