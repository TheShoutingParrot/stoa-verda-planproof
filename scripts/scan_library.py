"""Replay verified image-bound count reports and run individual scan questions."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading

from . import local_parse, nemotron, scan_reader
from .drawing_library import DrawingError, ROOT

RUN_LOCK = threading.Lock()
BEDROOMS = 'How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?'
COORDS = 'xyxy_top_left_0_to_1000'
COUNT_QUESTION = re.compile(r'^(how many\b|count\b|what(?: is|\x27s) the (?:total )?(?:number|count) of\b|kuinka monta\b|montako\b|laske\b)', re.I)
MEASUREMENT = re.compile(r'\b(square (?:feet|met(?:er|re)s?)|met(?:er|re)s?|neliömetr\w*|square footage|m2)\b|m²', re.I)


def _interactive_dir(digest):
    return Path(os.getenv('PLANPROOF_SCAN_RESULTS', ROOT / '.local/scan-results')) / digest


def _safe_report(raw, path, digest, question, origin):
    if (not isinstance(raw, dict) or raw.get('path') != path or raw.get('image_sha256') != digest
            or raw.get('question') != question or raw.get('image') != Path(path).name
            or raw.get('coordinate_system') != COORDS or not isinstance(question, str) or not question.strip()):
        return None
    try:
        report = nemotron.parse_count(json.dumps(raw, allow_nan=False))
    except (ValueError, TypeError):
        return None
    if raw.get('coverage_evidence') and report['status'] == 'answered' and report['answer'] == 0:
        try:
            coverage = raw['coverage_evidence']
            report['coverage_evidence'] = nemotron.parse_count(json.dumps(
                dict(status='answered', answer=len(coverage), evidence=coverage)))['evidence']
        except (TypeError, ValueError):
            return None
        if isinstance(raw.get('reason'), str):
            report['reason'] = raw['reason'][:220]
    report.update(question=question, path=path, image_sha256=digest, coordinate_system=COORDS, origin=origin)
    for k in ('model', 'served_model', 'provider_host', 'method', 'timestamp', 'reader_version'):
        if isinstance(raw.get(k), str):
            report[k] = raw[k][:220]
    if type(raw.get('latency_ms')) is int:
        report['latency_ms'] = raw['latency_ms']
    return report


def _json_file(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError, UnicodeError):
        return None


def _saved(path, digest):
    reports = {}
    def remember(raw, question, origin):
        report = _safe_report(raw, path, digest, question, origin)
        if report:
            reports[question] = report
    name = Path(path).name
    examples = _json_file(ROOT / 'public/data/finnish/library-runs.json') or {}
    for raw in examples.get(path, []):
        remember(raw, raw.get('question'), raw.get('origin'))
    local = Path(os.getenv('PLANPROOF_SCAN_LOCAL', ROOT / '.local/evaluation/full-english/finnish'))
    for folder in ('model', 'gates'):
        raw = _json_file((local / folder / name).with_suffix('.json'))
        if isinstance(raw, dict) and raw.get('status') in ('answered', 'unknown'):
            method = raw.get('method')
            if folder == 'model' and method != 'local_nemotron_parse':
                continue
            if folder == 'gates' and method not in ('grayscale_invariant', 'no_linkable_ocr_box', 'no_eligible_green_span'):
                continue
            raw.update(image=name, question=BEDROOMS, coordinate_system=COORDS)
            if folder == 'model':
                raw.update(model=local_parse.MODEL, served_model=local_parse.WEIGHTS + '@' + local_parse.REVISION,
                           latency_ms=raw.get('inference_ms'))
                remember(raw, BEDROOMS, 'Local Nemotron Parse')
            else:
                raw['reason'] = 'The local reader could not link bedroom labels to evidence on this drawing.'
                remember(raw, BEDROOMS, 'Local label check')
            if BEDROOMS in reports:
                break
    checkpoint = Path(os.getenv('PLANPROOF_SCAN_CHECKPOINT', ROOT / '.local/evaluation/hosted-cubicasa/checkpoint.sqlite3'))
    if checkpoint.is_file():
        with closing(sqlite3.connect(checkpoint.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            for question, payload in db.execute('SELECT question, report FROM results WHERE path = ?', (path,)):
                try:
                    raw = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                remember(raw, question, 'Saved hosted inference')
    for item in _interactive_dir(digest).glob('*.json'):
        raw = _json_file(item)
        if isinstance(raw, dict):
            remember(raw, raw.get('question'), raw.get('origin') or 'Interactive inference')
    return reports


class ScanImage:
    def __init__(self, library, path):
        self.drawing = library.metadata(path)
        if self.drawing['kind'] != 'scan':
            raise DrawingError(422, 'Select a CubiCasa drawing to ask a scan question.')
        self.name = Path(path).name
        self.data = library.read_bytes(path)
        self.digest = hashlib.sha256(self.data).hexdigest()

    def read_bytes(self):
        return self.data


def scan_info(library, path):
    image = ScanImage(library, path)
    reports = _saved(path, image.digest)
    return dict(drawing=image.drawing, imageSha256=image.digest, local=scan_reader.local_available(),
                configured=bool(os.getenv('NEMOTRON_BASE_URL') and os.getenv('NEMOTRON_API_KEY')),
                saved=sorted(reports.values(), key=lambda r: (r['status'] != 'answered', not r['evidence'], r['question'])))


def scan_answer(library, path, question, *, refresh=False):
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise DrawingError(400, 'Enter a count question up to 2,000 characters.')
    image = ScanImage(library, path)
    question = ' '.join(question.split())
    saved = _saved(path, image.digest).get(question)
    if saved and not refresh:
        return dict(saved, reused=True)
    if not COUNT_QUESTION.search(question) or MEASUREMENT.search(question):
        raise DrawingError(422, 'Ask for a count of visible items, such as “How many doors are shown?”')
    base, key = os.getenv('NEMOTRON_BASE_URL'), os.getenv('NEMOTRON_API_KEY')
    if not RUN_LOCK.acquire(blocking=False):
        raise DrawingError(409, 'Another drawing is being counted. Try again when it finishes.')
    try:
        # A previous request may have finished between the cache lookup and the lock.
        saved = _saved(path, image.digest).get(question)
        if saved and not refresh:
            return dict(saved, reused=True)
        raw = scan_reader.run(image, question, base, os.getenv('NEMOTRON_MODEL', nemotron.MODEL), key)
        if raw.get('status') == 'unavailable':
            raise DrawingError(503, raw.get('reason') or 'Inference is unavailable.')
        raw['path'] = path
        report = _safe_report(raw, path, image.digest, question, raw.get('origin') or 'Interactive inference')
        if not report:
            raise DrawingError(502, 'The inference service returned an invalid drawing report.')
        # Keep a previously localized answer available if the fresh reader abstains.
        if report['status'] == 'unknown' and saved and saved['status'] == 'answered':
            return dict(report, reused=False, saved=False)
        directory = _interactive_dir(image.digest)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (hashlib.sha256((path + '\0' + question).encode()).hexdigest() + '.json')
        with tempfile.NamedTemporaryFile('w', dir=directory, suffix='.tmp', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                json.dump(dict(report, image=image.name), tmp, ensure_ascii=False, allow_nan=False)
                tmp.flush()
                os.fsync(tmp.fileno())
                os.replace(tmp_path, target)
            finally:
                tmp_path.unlink(missing_ok=True)
        return dict(report, reused=False)
    finally:
        RUN_LOCK.release()
