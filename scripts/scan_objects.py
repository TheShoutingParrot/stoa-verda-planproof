"""Count pixel-localized openings and plumbing fixtures using the optional CubiCasa5K model.

Model setup and measured limitations are described in docs/scan-objects.md. No
inference input can identify a benchmark drawing, its split, or its annotations.
"""
from collections import OrderedDict
from functools import lru_cache
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import re
import sys
import threading

from scripts import scan_openings


MODEL = 'CubiCasa/CubiCasa5k'
REVISION = 'c34440266665a11f4484eb06cd2e4b7d72ad76c1'
WEIGHTS_HASH = 'dd20b4e1bf1d670f2125107b079df06958b1ccd36e49a464ab739aeb00b8e7a2'
SOURCE_HASHES = {
    'floortrans/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'floortrans/models/__init__.py': '9eb6b4906a922a8ceee9e925e89495408a0b163a64b30e13b52334957973b646',
    'floortrans/models/hg_furukawa_original.py': '05a07265d9ec8cade5228b834645af00c655e1413b21d02b0b3183d041f7752a',
    'floortrans/models/model_1427.py': '1b602dc086d3ea7f0eaefb480156c10e6e09bae073c08976c43fb0493613b921',
}
ASSETS = Path(__file__).resolve().parents[1] / '.local/scan-dev/objects'
ICON_NAMES = {1: 'Window', 2: 'Door', 5: 'Toilet bowl', 6: 'Sink or washbasin'}
QUESTION_START = r'(?:how many |count (?:the )?)'
QUESTION_END = r'(?: (?:are |are there )?(?:shown |drawn )?(?:on|in) (?:this|the) (?:floor plan|drawing|plan))?'
CLASSES = {
    1: r'windows?', 2: r'doors?', 5: r'(?:toilet bowls?(?: \(wc seats\))?|wc seats?)',
    6: r'(?:sinks?(?: and wash basins?)?|washbasins?)(?: \(kitchen and bathroom combined; a double-bowl sink counts as one\))?',
}
LOCK = threading.Lock()
CACHE = OrderedDict()


def category(question):
    if not isinstance(question, str):
        return None
    query = ' '.join(question.lower().strip().split())
    query = re.sub(r'\? count doorways fitted with a door; open doorways without a door leaf do not count\.$', '?', query)
    for cls, noun in CLASSES.items():
        if re.fullmatch(QUESTION_START + noun + QUESTION_END + r'[?.]?', query):
            return cls
    return None


def _locations():
    code = Path(os.getenv('PLANPROOF_CUBICASA_CODE', ASSETS / 'CubiCasa5k')).resolve()
    weights = Path(os.getenv('PLANPROOF_OBJECT_WEIGHTS', ASSETS / 'model_best_val_loss_var.pkl')).resolve()
    return code, weights


def available():
    """Check presence without importing PyTorch, allocating the model, or downloading files."""
    code, weights = _locations()
    return (weights.is_file() and all((code / name).is_file() for name in SOURCE_HASHES)
            and all(importlib.util.find_spec(name) is not None for name in ('torch', 'numpy', 'cv2', 'PIL')))


@lru_cache(maxsize=1)
def _load(code, weights):
    # Only the byte-verified architecture and an upstream weights-only checkpoint
    # are loaded. The repo's init_weights() pulls unrelated initial weights; the
    # official evaluation state already supplies every parameter.
    import torch
    for filename, expected in SOURCE_HASHES.items():
        if hashlib.sha256((code / filename).read_bytes()).hexdigest() != expected:
            raise ValueError('Unexpected CubiCasa source revision')
    with weights.open('rb') as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
        if digest.hexdigest() != WEIGHTS_HASH:
            raise ValueError('Unexpected CubiCasa model checkpoint')
        source.seek(0)
        checkpoint = torch.load(source, map_location='cpu', weights_only=True)
    sys.path.insert(0, str(code))
    try:
        from floortrans.models.hg_furukawa_original import hg_furukawa_original
        if Path(sys.modules[hg_furukawa_original.__module__].__file__).resolve() != code / 'floortrans/models/hg_furukawa_original.py':
            raise ValueError('Conflicting CubiCasa architecture already imported')
    finally:
        sys.path.remove(str(code))
    model = hg_furukawa_original(44)
    model.load_state_dict(checkpoint['model_state'], strict=True)
    device = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
    return model.eval().to(device), device


def _extract(probabilities, endpoints=None):
    import cv2
    import numpy as np
    mask = probabilities.argmax(axis=0)
    height, width = mask.shape
    raw_boxes = {}
    strong_windows = []
    for cls in ICON_NAMES:
        _, components, stats, _ = cv2.connectedComponentsWithStats((mask == cls).astype(np.uint8), connectivity=8)
        boxes = []
        for component, (x, y, w, h, area) in enumerate(stats[1:], start=1):
            if area < 12 or min(w, h) < 2 or max(w, h) < 4:
                continue
            box = (int(x), int(y), int(x+w), int(y+h))
            if cls in (1, 2):
                crop = probabilities[cls, y:y+h, x:x+w][components[y:y+h, x:x+w] == component]
                if cls == 2 and (area < 20 or crop.mean() < .60 or crop.max() < .80):
                    continue
                if cls == 1 and crop.mean() >= .72 and crop.max() >= .90:
                    strong_windows.append(box)
            boxes.append(box)
        raw_boxes[cls] = boxes

    if endpoints is not None:
        semantic = (probabilities[1:3]*255).round().astype(np.uint8)
        heatmaps = (endpoints*255).round().astype(np.uint8)
        raw_boxes.update(scan_openings.decode(semantic, heatmaps, strong_windows, raw_boxes[2]))

    detected = {}
    for cls, boxes in raw_boxes.items():
        evidence = []
        for box in boxes:
            mark = [round(1000*v/d) for v, d in zip(box, (width, height, width, height))]
            if mark[2] > mark[0] and mark[3] > mark[1]:
                evidence.append({'label': ICON_NAMES[cls], 'box': mark})
        detected[cls] = sorted(evidence, key=lambda e: (e['box'][1], e['box'][0]))
    return detected


def _infer(data, model, device):
    import cv2
    import numpy as np
    import torch
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or image.width * image.height > 36_000_000:
            return None
        width, height = image.size
        scale = min(1.0, 896 / max(width, height))
        target = (round(width * scale), round(height * scale))
        if min(target) < 128:
            return None
        rgb = np.array(image.convert('RGB'))
    if target != (width, height):
        rgb = cv2.resize(rgb, target, interpolation=cv2.INTER_AREA)
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().to(device) / 127.5 - 1.
    # The native model uses 21 keypoint channels, 12 room channels, then
    # 11 semantic icons. Inverse-rotate each prediction before combining it.
    logits = None
    with torch.inference_mode():
        for rotation in range(4):
            raw = model(torch.rot90(x, rotation, (-2, -1)))
            oriented = [13+i for i in scan_openings.ENDPOINT_ORDER[rotation]]
            pred = torch.cat((raw[:, oriented], raw[:, 33:44]), dim=1)
            pred = torch.rot90(pred, -rotation, (-2, -1))
            pred = torch.nn.functional.interpolate(pred, size=x.shape[-2:], mode='bilinear', align_corners=True)
            logits = pred if logits is None else logits + pred
        averaged = logits[0] / 4
        result = _extract(averaged[4:].softmax(dim=0).cpu().numpy(), averaged[:4].cpu().numpy())
    return result


def _cached_inventory(image_bytes):
    """Return all four classes in one pass (cached by exact input bytes) or None."""
    if not available():
        return None
    code, weights = _locations()
    digest = hashlib.sha256(image_bytes).hexdigest()
    key = (code, weights, digest)
    with LOCK:
        if key in CACHE:
            CACHE.move_to_end(key)
            return CACHE[key]
        try:
            result = _infer(image_bytes, *_load(code, weights))
        except (ImportError, OSError, RuntimeError, ValueError):
            return None
        if result is None:
            return None
        record = {'image_sha256':digest, 'classes':result}
        CACHE[key] = record
        if len(CACHE) > 16:
            CACHE.popitem(last=False)
        return record


def predict(image_bytes, question, inventory=None):
    """Return a source-image count and individually localized boxes, or None for unsupported input."""
    cls = category(question)
    if cls is None:
        return None
    record = inventory if inventory is not None else _cached_inventory(image_bytes)
    if not record or record['image_sha256'] != hashlib.sha256(image_bytes).hexdigest():
        return None
    marks = record['classes'][cls]
    return {'status':'answered', 'answer':len(marks), 'evidence':marks, 'question':question,
            'image_sha256':record['image_sha256'], 'coordinate_system':'xyxy_top_left_0_to_1000',
            'model':MODEL, 'served_model':MODEL + '@' + REVISION, 'provider_host':None,
            'method':'cubicasa_icon_segmentation',
            'reason':('Count from model-predicted opening endpoints and the pixel segmentation of the supplied scan.'
                      if cls in (1, 2) else 'Count of distinct fixture symbols in the pixel segmentation of the supplied scan.')}


def inventory(image_bytes):
    """Inspect the complete object inventory for reuse across questions on the same PNG."""
    return _cached_inventory(image_bytes)
