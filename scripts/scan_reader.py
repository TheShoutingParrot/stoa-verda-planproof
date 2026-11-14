"""Read visible counts on the original scan. Coordinates use top-left xyxy in 0–1000."""
from datetime import datetime, timezone
import hashlib
import shutil
import sys
import time
from urllib.parse import urlsplit

from . import nemotron, scan_layout, scan_objects, scan_rooms, scan_storeys

VERSION = 'scan-reader-4'

DIRECT_INSTRUCTIONS = """Inspect the entire supplied floor plan and answer the user's counting question.
Scope: count objects in the depicted plan, across all separate floor panels. Ignore the legend, neighboring building silhouettes and advertising thumbnails. Follow any narrower scope in the question. Use Finnish or Swedish room abbreviations when present. A WC room and a toilet bowl are different objects. For sinks, count a double-bowl unit once. Distinguish showers or tubs from saunas, sinks and floor drains. A doorway needs a door leaf; ignore furniture arcs. Windows are glazed openings in walls. Count storeys from distinct drawn floors, not staircases or sheet layout.
Review the drawing once in reading order. Return compact JSON only. For each item draw a tight, distinct box around the actual symbol, room label, or floor panel on the original image. Coordinates are integers [left,top,right,bottom] in 0–1000 with origin at top left. Use a short label, e.g. "WC". Output {"status":"answered","answer":N,"evidence":[{"label":"...","box":[x0,y0,x1,y1]}]}. If the drawing shows no such objects, answer 0 with empty evidence. If the count cannot be verified, return {"status":"unknown","answer":null,"evidence":[],"reason":"short reason"}. Never substitute an entire image for an object's location."""


def hosted_count(image, question, base, model, api_key, timeout=90):
    report = nemotron.run(image, question, base, model, api_key, timeout,
                          instructions=DIRECT_INSTRUCTIONS, thinking=False, json_output=True)
    report['method'] = 'nemotron_direct'
    return report


def local_available():
    return bool(sys.platform == 'darwin' or shutil.which('tesseract') or scan_objects.available())


def run(image, question, base, model, api_key, timeout=90, *, baseline_report=None):
    """Use raster pixels and the question only. A benchmark may replay an identical old hosted request."""
    started = time.monotonic()
    data = image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    for predictor, origin, local_model in (
        (scan_rooms.predict, 'Local room labels', 'Room label OCR'),
        (scan_storeys.predict, 'Local floor panels', 'Floor plan and caption reader'),
        (scan_layout.predict, 'Local room map', 'CubiCasa5K room map with label OCR'),
        (scan_objects.predict, 'Local object detector', 'CubiCasa5K')
    ):
        result = predictor(data, question)
        if result is not None and result['status'] == 'answered':
            return dict(result, question=question, image=image.name, image_sha256=digest,
                        coordinate_system='xyxy_top_left_0_to_1000', model=local_model,
                        origin=origin, reader_version=VERSION,
                        latency_ms=round((time.monotonic() - started) * 1000),
                        timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    if not base or not api_key:
        return dict(status='unavailable', answer=None, evidence=[], reason=(
            'The local readers could not verify this count. Configure the hosted endpoint to run it on this drawing.'))
    # The old hosted pass was most reliable on storeys and several room types.
    # Use the shorter structured response on the categories prone to running out of output.
    direct = any(term in question.casefold() for term in ('window', 'door', 'shower', 'bathtub', 'sink', 'basin', 'bedroom'))
    if direct:
        report = hosted_count(image, question, base, model, api_key, timeout)
    elif (baseline_report and baseline_report.get('image_sha256') == digest
          and baseline_report.get('question') == question and baseline_report.get('model') == model
          and baseline_report.get('provider_host') == urlsplit(base).hostname
          and baseline_report.get('method') == 'original_full_image'
          and baseline_report.get('coordinate_system') == 'xyxy_top_left_0_to_1000'
          and baseline_report.get('status') in ('answered', 'unknown')):
        report = dict(baseline_report, method='nemotron_original')
    else:
        report = nemotron.run(image, question, base, model, api_key, timeout)
        report['method'] = 'nemotron_original'
    return dict(report, reader_version=VERSION, origin='Interactive inference')
