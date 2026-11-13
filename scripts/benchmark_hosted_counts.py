"""Score real CubiCasa count requests through the configured Nemotron-compatible endpoint.

No arguments prints the population. Set NEMOTRON_BASE_URL and NEMOTRON_API_KEY,
then pass --run --limit 1 for one real request. Increase the limit or omit it to
resume the whole population. --export rebuilds the scored JSONL offline, including
after interruption. A separate working directory is required for each endpoint/model.
"""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import threading
import time
from urllib import error, parse, request
from zipfile import ZipFile

import nemotron
from benchmark_full_english import ARCHIVE, BEDROOM, MANIFEST, ROOT, read_questions, write_line


WORK = ROOT / ".local/evaluation/hosted-cubicasa"
POPULATION = 39797
QUOTA_CODES = {"insufficient_quota", "insufficient_balance", "insufficient_credits",
               "billing_hard_limit_reached", "credits_exhausted", "credit_limit_exceeded",
               "quota_exceeded"}
RESOURCE_CODES = {"image_too_large", "image_size_exceeded", "context_length_exceeded"}
TRANSIENT = {408, 425, 429}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def population(archive):
    rows = {key: row["answer"] for key, row in read_questions(archive).items()
            if key[0].startswith("data/cubicasa5k/") and key[1] != BEDROOM and row["unit"] == "count"}
    if len(rows) != POPULATION:
        raise ValueError("Expected exactly 39,797 released English non-bedroom count questions.")
    return rows


class ObservedHTTP:
    """Keep only status, Retry-After and allowlisted failure classes from HTTP errors."""
    def __init__(self):
        self.client = request.build_opener(nemotron.NoRedirect())
        self.code = self.retry_after = None
        self.quota = self.image_limit = False

    def open(self, req, *, timeout):
        try:
            return self.client.open(req, timeout=timeout)
        except error.HTTPError as exc:
            self.code = exc.code
            retry = exc.headers.get("Retry-After") if exc.headers else None
            if retry:
                try:
                    self.retry_after = max(0, int(retry))
                except ValueError:
                    try:
                        self.retry_after = max(0, parsedate_to_datetime(retry).timestamp() - time.time())
                    except (TypeError, ValueError, OverflowError):
                        pass
            try:
                message = exc.read(16384).decode("utf-8", errors="replace").lower()
                self.quota = (any(code in message for code in QUOTA_CODES)
                              or any(s in message for s in ("insufficient credits", "insufficient balance",
                                                            "out of credits", "credit balance is too low")))
                self.image_limit = any(code in message for code in RESOURCE_CODES)
            except OSError:
                pass
            finally:
                exc.close()
            raise


class Pacer:
    """Globally space starts, and honor a rate-limit response across all workers."""
    def __init__(self, rpm):
        self.spacing = 60 / rpm
        self.next_start = 0.0
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def permit(self):
        while not self.stopped.is_set():
            with self.lock:
                now = time.monotonic()
                delay = self.next_start - now
                if delay <= 0:
                    self.next_start = now + self.spacing
                    return True
            self.stopped.wait(delay)
        return False

    def backoff(self, seconds):
        with self.lock:
            self.next_start = max(self.next_start, time.monotonic() + seconds)


class Halt(Exception):
    """Safe message for a resumable batch interruption."""


def predict(archive, key, args, pacer, token):
    path, question = key  # No gold fields are available to the request function.
    with tempfile.TemporaryDirectory() as temporary:
        drawing = Path(temporary) / Path(path).name
        drawing.write_bytes(archive.read("junction-dataset/" + path))
        for attempt in range(1, args.retries + 2):
            if not pacer.permit():
                return None
            observer = ObservedHTTP()
            result = nemotron.run(drawing, question, args.base_url, args.model, token,
                                  timeout=args.timeout, opener=observer)
            # Free text returned by an external service can echo the authorization
            # header. Remove any exact credential before persisting its response.
            text_fields = [(result, "reason"), (result, "served_model")]
            text_fields.extend((item, "label") for item in result["evidence"])
            for container, field in text_fields:
                if isinstance(container.get(field), str):
                    container[field] = container[field].replace(token, "[redacted]")
            result.update(path=path, attempts=attempt)
            if result["status"] != "unavailable":
                return result
            code = observer.code
            if observer.quota or code in (401, 402, 403, 404):
                message = "Authentication, billing, quota or endpoint configuration failed."
            elif code == 413 or observer.image_limit:
                # The service rejected this individual input. The following drawing can still be valid.
                return result
            elif (code in TRANSIENT or (code is not None and 500 <= code < 600)
                  or result["reason"] == "Inference endpoint was unreachable or timed out."):
                if attempt <= args.retries:
                    delay = max(observer.retry_after or 0, min(120, 2 ** attempt) + random.random())
                    if delay <= args.max_wait:
                        pacer.backoff(delay)
                        continue
                    message = "Provider backoff exceeds the allowed wait."
                else:
                    message = "Transient failure persisted through the retry budget."
            else:
                message = "Provider did not accept the configured request or return a usable completion."
            pacer.stopped.set()
            raise Halt(f"{message} HTTP {code if code else 'unavailable'}. Remaining questions can be resumed.")


@contextmanager
def locked(work):
    work.mkdir(parents=True, exist_ok=True)
    with (work / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Halt("Another benchmark process is using this working directory.")
        yield


def configure(connection, args):
    connection.execute("CREATE TABLE IF NOT EXISTS config(value TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS results(path TEXT, question TEXT, report TEXT NOT NULL, "
                       "PRIMARY KEY(path, question))")
    saved = connection.execute("SELECT value FROM config").fetchone()
    if not args.run:
        if not saved:
            raise Halt("No authenticated run exists in this working directory.")
        return json.loads(saved[0])
    endpoint = nemotron.endpoint_url(args.base_url)
    config = dict(schema_version=1, question_manifest_sha256=MANIFEST, population=POPULATION,
                  model=args.model, provider_host=parse.urlsplit(endpoint).hostname,
                  endpoint_sha256=sha(endpoint.encode()),
                  inference_client_sha256=sha(Path(nemotron.__file__).read_bytes()))
    if saved:
        if json.loads(saved[0]) != config:
            raise Halt("The endpoint, model, inference implementation or release changed. Use a new --work directory.")
    else:
        if (args.work / "hosted-rows.jsonl.gz").exists() or (args.work / "summary.json").exists():
            raise Halt("Existing results in this directory have no matching checkpoint. Use a new --work directory.")
        connection.execute("INSERT INTO config VALUES (?)", (json.dumps(config),))
        connection.commit()
    return config


def collect(connection, archive, selected, args, token):
    done = set(connection.execute("SELECT path,question FROM results"))
    pending = iter(key for key in selected if key not in done)
    pacer = Pacer(args.rpm)
    failure = None
    seen = 0
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        active = {}
        def fill(capacity):
            while len(active) < capacity and not pacer.stopped.is_set():
                key = next(pending, None)
                if key is None:
                    break
                active[workers.submit(predict, archive, key, args, pacer, token)] = key

        try:
            # Probe one real question before opening concurrent billable requests.
            fill(1)
            while active:
                completed, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed:
                    key = active.pop(future)
                    try:
                        result = future.result()
                    except Halt as exc:
                        failure = failure or exc
                        continue
                    if result is not None:
                        connection.execute("INSERT INTO results VALUES (?,?,?)", (*key, json.dumps(result)))
                        connection.commit()
                        seen += 1
                        if seen == 1 or seen % 100 == 0:
                            print(f"Committed {seen:,} new results.", flush=True)
                fill(args.workers)
        finally:
            pacer.stopped.set()
    if failure:
        raise failure


def export(connection, config, targets, work):
    counts, usage = Counter(), Counter()
    attempts = 0
    out = work / "hosted-rows.jsonl.gz"
    scratch = work / "hosted-rows.jsonl.gz.tmp"
    with gzip.open(scratch, "wt", encoding="utf-8") as stream:
        # Scoring happens only here, after the provider's sealed report was committed.
        for path, question in targets:
            stored = connection.execute("SELECT report FROM results WHERE path=? AND question=?", (path, question)).fetchone()
            if not stored:
                continue
            report = json.loads(stored[0])
            gold = targets[path, question]
            correct = report["status"] == "answered" and report["answer"] == gold
            counts[report["status"]] += 1
            counts["correct"] += correct
            attempts += report["attempts"]
            usage.update(report["usage"] or {})
            write_line(stream, dict(**report, gold=gold, correct=correct))
    scratch.replace(out)
    completed = sum(counts[s] for s in ("answered", "unknown", "unavailable"))
    summary = dict(**config, completed=completed, remaining=len(targets) - completed,
                   answered=counts["answered"], correct=counts["correct"],
                   wrong=counts["answered"] - counts["correct"], unknown=counts["unknown"],
                   unavailable=counts["unavailable"], attempts_on_completed_rows=attempts,
                   reported_tokens_on_completed_rows=dict(usage),
                   updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    temp = work / "summary.json.tmp"
    temp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    temp.replace(work / "summary.json")
    print(f"{completed:,}/{len(targets):,} completed, {counts['correct']:,} exact. {out}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Authorize real model requests to the configured HTTPS endpoint.")
    mode.add_argument("--export", action="store_true", help="Rebuild JSONL from the saved checkpoint without network.")
    parser.add_argument("--archive", default=ARCHIVE, type=Path)
    parser.add_argument("--work", default=WORK, type=Path)
    parser.add_argument("--base-url", default=os.environ.get("NEMOTRON_BASE_URL", ""))
    parser.add_argument("--model", default=os.environ.get("NEMOTRON_MODEL", nemotron.MODEL))
    parser.add_argument("--api-key-env", default="NEMOTRON_API_KEY", help="Environment variable name, never the token.")
    parser.add_argument("--limit", type=int, help="Run only the first N release questions. Repeating the same cap resumes it.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--rpm", type=int, default=20, help="Maximum number of request starts per minute including retries.")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-wait", type=int, default=300, help="Stop and keep checkpoints if Retry-After exceeds this, in seconds.")
    args = parser.parse_args()
    if (not 1 <= args.workers <= 16 or not 1 <= args.rpm <= 600 or not 0 <= args.retries <= 8
            or not 1 <= args.timeout <= 600 or not 1 <= args.max_wait <= 86400
            or (args.limit is not None and not 1 <= args.limit <= POPULATION)):
        parser.error("Invalid worker, rate, retry, timeout, wait or population bounds.")
    if args.work.resolve() == (ROOT / ".local/evaluation/full-english").resolve():
        parser.error("Choose a separate hosted working directory to preserve the offline benchmark.")
    token = os.environ.get(args.api_key_env) if args.run else None
    if args.run:
        if not token or not args.model.strip() or not args.base_url:
            parser.error("--run requires the configured endpoint, model and credential environment variable.")
        try:
            nemotron.endpoint_url(args.base_url)
        except nemotron.ConfigurationError as exc:
            parser.error(str(exc))
    with ZipFile(args.archive) as archive:
        targets = population(archive)
        selected = list(targets)[:args.limit]
        if not args.run and not args.export:
            print(f"Dry run: {len(selected):,} of {len(targets):,} questions selected. Pass --run to send requests.")
            return 0
        with locked(args.work), sqlite3.connect(args.work / "checkpoint.sqlite3") as connection:
            config = configure(connection, args)
            if args.run:
                try:
                    collect(connection, archive, selected, args, token)
                finally:
                    export(connection, config, targets, args.work)
            else:
                export(connection, config, targets, args.work)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Halt as failure:
        sys.exit(str(failure))
