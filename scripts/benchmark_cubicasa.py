"""Evaluate the existing local_parse whole-sheet bedroom decision on English CubiCasa PNGs.

Run --stage gate, then --stage model with the pinned MLX checkout, then --stage report.
Both expensive phases resume from atomic per-image files. No network access is used.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import time
import threading
from zipfile import ZipFile

from PIL import Image, ImageChops
import numpy as np

if __package__:
    from . import local_parse as engine
else:
    import local_parse as engine

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / '.local/evaluation/swiss-frontier/inputs/junction-dataset.zip'
CACHE = ROOT / '.local/evaluation/full-english/finnish'
QUESTION = 'How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?'
PREFIX = 'junction-dataset/'
GATE_VERSION = 1
archive_session = threading.local()
WEIGHTS_SHA256 = 'd7b0f17862f8d732510438f2460240e58dae207b14a1dcc662ec76e61397f3c6'
CONFIG_BLOBS = {
    'config.json': 'c68f371b75c9e23bef9a9ba1d00044ca9fcc3245',
    'generation_config.json': '20ba50884d7e43d36f4992585b51ac793ad898ff',
    'model.safetensors.index.json': 'c932d09efec197d3d4046ba72048a25345802596',
    'preprocessor_config.json': '4e928e1485b42aa6d7c04b098accbb08230e0f75',
    'processor_config.json': '4959a42e3da9cb1fe6173d2096d0ccf3b37bcb44',
    'special_tokens_map.json': '0a7046614fdd6368c44cbb4b182d83a9d18b61bf',
    'tokenizer.json': '915caec02ef6c144f7ced7fb17f0080caaee9932',
    'tokenizer_config.json': '6f148a7f849d6c7cf020599d88930b8cec148ff2',
}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(f'.{os.getpid()}.tmp')
    pending.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
    pending.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_bytes(archive, name):
    # One seekable handle per worker; reparsing the ZIP central directory for
    # every scan adds thousands of redundant listings of this 9.8 GB pack.
    if getattr(archive_session, 'path', None) != archive:
        if hasattr(archive_session, 'dataset'):
            archive_session.dataset.close()
        archive_session.dataset = ZipFile(archive)
        archive_session.path = archive
    return archive_session.dataset.read(PREFIX + name)


def gray(image):
    red, green, blue = image.split()
    return not ImageChops.difference(red, green).getbbox() and not ImageChops.difference(red, blue).getbbox()


def any_green_span(image):
    # Exact union of all scan lines that could pass local_parse.green_bounds.
    # Work by stripes so a very large image never needs a full int16 RGB copy.
    for y in range(0, image.height, 64):
        rgb = np.asarray(image.crop((0, y, image.width, min(y + 64, image.height))), dtype=np.int16)
        red, green, blue = rgb.transpose(2, 0, 1)
        mask = (green > 140) & (green - red > 10) & (green - blue > 45)
        spans = image.width - 1 - mask.argmax(axis=1) - mask[:, ::-1].argmax(axis=1)
        if np.any(mask.any(axis=1) & (spans >= image.width * .1)):
            return True
    return False


def viable_words(image, tsv):
    # A successful link_regions transcript must contain a nonempty subset of
    # LABELS. A matching Tesseract word and valid bracket are necessary for it.
    candidates = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = engine.letters(row['text'])
        if not any(engine.similar(label, word) for label in engine.LABELS):
            continue
        x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
        bounds = engine.green_bounds(image, y + h // 2)
        if bounds and bounds[0] < x + w / 2 < bounds[1]:
            candidates.append(row['text'])
    return candidates


def path_for(cache, folder, path):
    return cache / folder / (Path(path).stem + '.json')


def run_gate(archive, cache, path):
    result_file = path_for(cache, 'gates', path)
    if result_file.exists():
        return json.loads(result_file.read_text())
    data = image_bytes(archive, path)
    image = Image.open(io.BytesIO(data)).convert('RGB')
    record = {'path': path, 'image_sha256': sha(data), 'status': 'unknown', 'answer': None, 'evidence': []}
    if gray(image):
        # Same Lanczos transform for all channels preserves exact equality.
        record['method'] = 'grayscale_invariant'
    else:
        crop = engine.render_crop(image, (0, 0, image.width, image.height))
        if not any_green_span(crop):
            record['method'] = 'no_eligible_green_span'
        else:
            buf = io.BytesIO()
            crop.save(buf, 'PNG')
            tsv = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '11', 'tsv'],
                                 input=buf.getvalue(), capture_output=True, check=True).stdout.decode()
            words = viable_words(crop, tsv)
            record['method'] = 'no_linkable_ocr_box'
            if words:
                record.update(status='pending', method='model_required', ocr_candidates=words)
                destination = path_for(cache, 'tsv', path).with_suffix('.tsv.gz')
                destination.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(destination, 'wt') as stream:
                    stream.write(tsv)
    dump(result_file, record)
    return record


def report(cache, rows):
    counts, methods = Counter(), Counter()
    styles = {}
    eligible = decided = scored = 0
    result_tmp = cache / f'rows.{os.getpid()}.jsonl.tmp'
    with result_tmp.open('w') as out:
        for row in rows:
            dest = path_for(cache, 'gates', row['path'])
            if not dest.exists():
                continue
            gate = json.loads(dest.read_text())
            if gate['status'] == 'pending':
                eligible += 1
                dest = path_for(cache, 'model', row['path'])
                if not dest.exists():
                    continue
                gate = json.loads(dest.read_text())
            correct = gate['answer'] == row['answer'] and gate['status'] == 'answered'
            scored += correct
            counts[gate['status']] += 1
            methods[gate['method']] += 1
            style = Path(row['path']).stem.split('-')[0]
            group = styles.setdefault(style, Counter())
            group['decided'] += 1
            group[gate['status']] += 1
            group['exact'] += correct
            decided += 1
            out.write(json.dumps({**gate, 'gold': row['answer'], 'correct': correct}, ensure_ascii=False) + '\n')
    result_tmp.replace(cache / 'rows.jsonl')
    state = {'total': len(rows), 'decided': decided, 'model_eligible': eligible, 'exact': scored,
             'wrong_numeric': counts['answered'] - scored, 'statuses': dict(counts), 'methods': dict(methods),
             'remaining': len(rows) - decided, 'by_style': styles,
             'accuracy_among_answered': scored / counts['answered'] if counts['answered'] else None,
             'coverage_of_all': counts['answered'] / len(rows), 'exact_fraction_of_all': scored / len(rows)}
    dump(cache / 'summary.json', state)
    return state


def run_model(archive, cache, rows, weights, follow):
    os.environ['HF_HUB_OFFLINE'] = '1'
    weights = weights.resolve(strict=True)
    with (weights / 'model.safetensors').open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != WEIGHTS_SHA256:
            raise ValueError('MLX weights differ from the pinned revision')
    for filename, expected in CONFIG_BLOBS.items():
        data = (weights / filename).read_bytes()
        blob = b'blob ' + str(len(data)).encode() + b'\0' + data
        if hashlib.sha1(blob).hexdigest() != expected:
            raise ValueError(f'{filename} differs from the pinned revision')
    from mlx_vlm import generate, load
    model, processor = load(str(weights))
    while True:
        gates_available = sum(path_for(cache, 'gates', row['path']).exists() for row in rows)
        for row in rows:
            path = row['path']
            gate_file = path_for(cache, 'gates', path)
            dest = path_for(cache, 'model', path)
            if not gate_file.exists() or dest.exists():
                continue
            gate = json.loads(gate_file.read_text())
            if gate['status'] != 'pending':
                continue
            data = image_bytes(archive, path)
            if sha(data) != gate['image_sha256']:
                raise ValueError('Changed image after gate')
            im = Image.open(io.BytesIO(data)).convert('RGB')
            crop = engine.render_crop(im, (0, 0, im.width, im.height))
            with gzip.open(path_for(cache, 'tsv', path).with_suffix('.tsv.gz'), 'rt') as stream:
                tsv = stream.read()
            started = time.perf_counter()
            pred = generate(model, processor, engine.PROMPT, image=crop, max_tokens=475, temperature=0, verbose=False)
            status, answer, evidence = engine.link_regions(pred.text, crop, tsv)
            result = {**gate, 'method':'local_nemotron_parse', 'status':status, 'answer':answer,
                      'evidence':evidence, 'transcript':engine.plain_text(pred.text),
                      'inference_ms': round((time.perf_counter()-started)*1000)}
            dump(dest, result)
            print('model', path, status, answer, result['inference_ms'], flush=True)
        state = report(cache, rows)
        if not follow or (gates_available == len(rows) and state['remaining'] == 0):
            return
        time.sleep(8)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ZIP)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--stage', choices=['gate','model','report'], required=True)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--follow', action='store_true', help='Keep one loaded model while gate workers finish')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.archive) as archive:
        questions = archive.read(PREFIX + 'questions.jsonl')
        rows = [r for line in questions.splitlines() if (r := json.loads(line))['question'] == QUESTION
                and r['path'].startswith('data/cubicasa5k/') and r['path'].endswith('.png')]
        members = [(r['path'], archive.getinfo(PREFIX+r['path']).CRC) for r in rows]
    if len({r['path'] for r in rows}) != len(rows):
        raise ValueError('Duplicate image in English bedroom questions')
    configuration = {'question': QUESTION, 'questions_sha256':sha(questions), 'members_sha256':sha(json.dumps(members).encode()),
                     'local_parse_sha256':sha(Path(engine.__file__).read_bytes()), 'gate_version':GATE_VERSION,
                     'weights':engine.WEIGHTS, 'revision':engine.REVISION, 'versions':{p:importlib.metadata.version(p)
                     for p in ('mlx','mlx-vlm','pillow','numpy')}, 'tesseract':subprocess.check_output(['tesseract','--version'],text=True).splitlines()[0]}
    meta = args.cache / 'config.json'
    if meta.exists() and configuration != json.loads(meta.read_text()):
        raise SystemExit('Evaluation inputs/runtime changed: supply a separate --cache directory')
    if not meta.exists():
        dump(meta, configuration)
    if args.stage == 'gate':
        paths = [r['path'] for r in rows]
        # Interleave drawing styles and sizes reproducibly for meaningful progress.
        paths.sort(key=lambda p: sha(p.encode()))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            workers = {pool.submit(run_gate, args.archive, args.cache, p):p for p in paths}
            for n, task in enumerate(as_completed(workers),1):
                try:
                    task.result()
                except Exception as exc:
                    print('gate error; retry on resume',workers[task],repr(exc),flush=True)
                if n % 100 == 0:
                    print('gates',n, report(args.cache,rows),flush=True)
    elif args.stage == 'model':
        if not args.weights:
            parser.error('model stage requires --weights pointing at the pinned local MLX snapshot')
        run_model(args.archive, args.cache, rows, args.weights, args.follow)
    print(json.dumps(report(args.cache,rows)), flush=True)


if __name__ == '__main__':
    main()
