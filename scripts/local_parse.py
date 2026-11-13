"""Check Finnish bedroom labels with local Nemotron Parse and Tesseract. No API keys."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import re
import subprocess
import time


MODEL = 'nvidia/NVIDIA-Nemotron-Parse-v1.2'
WEIGHTS = 'mlx-community/Nemotron-Parse-v1.2-8bit'
REVISION = '92ebb2122d413426995ea92340ac847dad6ec274'
PROMPT = '</s><s><predict_bbox><predict_classes><output_markdown><predict_text_in_pic>'
QUESTION = 'Kuinka monta makuuhuonetta (MH) pohjapiirustuksessa on?'
LABELS = {'mh', 'makuuh', 'makuuhuone'}


def plain_text(raw):
    return re.sub(r'<[^>]+>', ' ', raw).strip()


def letters(text):
    return re.sub('[^a-zäö]', '', text.casefold())


def similar(a, b):
    if a == b:
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(left != right for left, right in zip(a, b)) == 1
    short, long = sorted((a, b), key=len)
    return any(short == long[:i] + long[i + 1:] for i in range(len(long)))


def green_bounds(image, y):
    # Find both green outline strokes bracketing the label on this scan line.
    hits = []
    for x in range(image.width):
        red, green, blue = image.getpixel((x, y))
        if green > 140 and green - red > 10 and green - blue > 45:
            hits.append(x)
    if not hits or (hits[-1] - hits[0]) < image.width * 0.1:
        return None
    return hits[0], hits[-1]


def link_regions(transcript, image, tsv):
    words = [letters(word) for word in plain_text(transcript).split()]
    labels = [word for word in words if word in LABELS]
    evidence = []
    width, height = image.size
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        candidates = {label for label in labels if similar(label, letters(row['text']))}
        if len(candidates) != 1:
            continue
        x, y, dx, dy = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
        bounds = green_bounds(image, y + dy // 2)
        if bounds and bounds[0] < x + dx / 2 < bounds[1]:
            evidence.append({'label': candidates.pop(), 'box': [round(n / d * 1000) for n, d in
                             zip((x, y, x + dx, y + dy), (width, height, width, height))],
                             'ocr_box_text': row['text'], 'ocr_box_confidence': float(row['conf'])})
    # Unreadable labels, unmatched words, or ambiguous edges warrant abstention.
    supported = bool(labels) and sorted(labels) == sorted(item['label'] for item in evidence)
    return ('answered', len(evidence), evidence) if supported else ('unknown', None, [])


def regions(width, height):
    left_end, right_start = round(width * .55), round(width * .45)
    # Match the fixed 10% overlap used in the reference run, including ceiling below the midpoint.
    top_end, bottom_start = round(height * .55) + 1, round(height * .45)
    return [('full', (0, 0, width, height)), ('left-top', (0, 0, left_end, top_end)),
            ('right-top', (right_start, 0, width, top_end)),
            ('left-bottom', (0, bottom_start, left_end, height)), ('right-bottom', (right_start, bottom_start, width, height))]


def render_crop(original, region):
    from PIL import Image
    crop = original.crop(region)
    return crop.resize((int(crop.width * 2.8), int(crop.height * 2.8)), Image.Resampling.LANCZOS)


def normalized_transcripts(records):
    return [{'name': r['name'], 'region_px': list(r['region']), 'input_size_px': list(r['input_size']),
             'warm_inference_ms': round(r['elapsed_s'] * 1000), 'text': plain_text(r['text']),
             'raw_output': r['text']} for r in records]


def build_report(path, original, records, started_seconds, versions, tsv):
    full = records[0]
    status, answer, boxes = link_regions(full['text'], render_crop(original, full['region']), tsv)
    return {'schema_version': 1, 'status': status, 'answer': answer, 'evidence': boxes, 'question': QUESTION,
            'image': path.name, 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'coordinate_system': 'xyxy_top_left_0_to_1000', 'model': MODEL, 'served_model': WEIGHTS + '@' + REVISION,
            'provider_host': None, 'quantization': 'MLX community 8-bit decoder; bf16 vision encoder',
            'runtime': versions, 'method': 'Local image transcription by Nemotron Parse; Finnish bedroom label matching; Tesseract word boxes inside the green outline. Fixed-grid crops are diagnostic repeats and do not add to the full-sheet count.',
            'latency_ms': round(1000 * full['elapsed_s']), 'latency_scope': 'Warm Nemotron OCR for the upscaled whole sheet, excluding model load, Tesseract, and diagnostic crops.',
            'model_load_ms': round(1000 * started_seconds), 'usage': None, 'transcript': plain_text(full['text']),
            'crop_runs': normalized_transcripts(records), 'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def main():
    from PIL import Image
    from huggingface_hub import snapshot_download
    from mlx_vlm import generate, load
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--weights', type=Path, help='Optional local copy of the pinned MLX weights.')
    args = parser.parse_args()
    checkpoint = args.weights or snapshot_download(repo_id=WEIGHTS, revision=REVISION, allow_patterns=['*.json', '*.safetensors'])
    image = Image.open(args.image).convert('RGB')
    started = time.perf_counter()
    model, processor = load(str(checkpoint))
    load_seconds = time.perf_counter() - started
    records = []
    for name, region in regions(*image.size):
        crop = render_crop(image, region)
        started = time.perf_counter()
        r = generate(model, processor, PROMPT, image=crop, max_tokens=475, temperature=0)
        records.append({'name': name, 'region': region, 'input_size': crop.size,
                        'elapsed_s': time.perf_counter() - started, 'text': r.text})
    image_bytes = io.BytesIO()
    render_crop(image, records[0]['region']).save(image_bytes, 'PNG')
    tsv = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '11', 'tsv'],
                         input=image_bytes.getvalue(), stdout=subprocess.PIPE, check=True).stdout.decode()
    versions = {p: importlib.metadata.version(p) for p in ('mlx', 'mlx-vlm', 'pillow')}
    versions['tesseract'] = subprocess.check_output(['tesseract', '--version'], text=True).splitlines()[0]
    report = build_report(args.image, image, records, load_seconds, versions, tsv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 0 if report['status'] == 'answered' else 1


if __name__ == '__main__':
    raise SystemExit(main())
