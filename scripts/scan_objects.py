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
# Openings are read on square tiles whose side divides by 64 as the training crops did.
# One tile shape also means one compiled graph and bounded memory on every drawing.
TILE = 1024
OVERLAP = 128
MAX_TILES = 4
PROBE_SIDE = 1536
LOCK = threading.Lock()
CACHE = OrderedDict()
# First readings wait here until the second reading and the room-map reader have both used them.
FIRST = OrderedDict()


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


def _components(mask, probabilities, classes=tuple(ICON_NAMES), unit=1.):
    """Connected segmentation components per class as model-grid boxes, and the confident window ones.

    `probabilities` needs the window and door planes at index 1 and 2.
    """
    import cv2
    import numpy as np
    raw_boxes = {}
    strong_windows = []
    for cls in classes:
        _, components, stats, _ = cv2.connectedComponentsWithStats((mask == cls).astype(np.uint8), connectivity=8)
        boxes = []
        for component, (x, y, w, h, area) in enumerate(stats[1:], start=1):
            if area < 12*unit*unit or min(w, h) < 2*unit or max(w, h) < 4*unit:
                continue
            box = (int(x), int(y), int(x+w), int(y+h))
            if cls in (1, 2):
                crop = probabilities[cls, y:y+h, x:x+w][components[y:y+h, x:x+w] == component]
                if cls == 2 and (area < 20*unit*unit or crop.mean() < .60 or crop.max() < .80):
                    continue
                if cls == 1 and crop.mean() >= .72 and crop.max() >= .90:
                    strong_windows.append(box)
            boxes.append(box)
        raw_boxes[cls] = boxes
    return raw_boxes, strong_windows


def _boxes(mask, probabilities, endpoints=None, classes=tuple(ICON_NAMES), unit=None):
    """Model-grid boxes per class: fixtures from the segmentation, openings from the endpoint decoder."""
    import numpy as np
    raw_boxes, strong_windows = _components(mask, probabilities, classes, unit or 1.)
    if endpoints is not None:
        semantic = (probabilities[1:3]*255).round().astype(np.uint8)
        heatmaps = (endpoints*255).round().astype(np.uint8)
        raw_boxes.update(scan_openings.decode(semantic, heatmaps, strong_windows, raw_boxes[2], unit))
    return raw_boxes


def _marks(raw_boxes, width, height):
    detected = {}
    for cls, boxes in raw_boxes.items():
        evidence = []
        for box in boxes:
            mark = [round(1000*v/d) for v, d in zip(box, (width, height, width, height))]
            if mark[2] > mark[0] and mark[3] > mark[1]:
                evidence.append({'label': ICON_NAMES[cls], 'box': mark})
        detected[cls] = sorted(evidence, key=lambda e: (e['box'][1], e['box'][0]))
    return detected


def _extract(probabilities, endpoints=None):
    mask = probabilities.argmax(axis=0)
    height, width = mask.shape
    return _marks(_boxes(mask, probabilities, endpoints), width, height)


def _average(model, x, rotations=(0, 1, 2, 3), rooms=False):
    """Endpoint heatmaps (4) and icon logits (11) on the input grid, averaged over quarter turns.

    With `rooms` the 12 room logits follow the icons.
    """
    import torch
    # The native model uses 21 keypoint channels, 12 room channels, then
    # 11 semantic icons. Inverse-rotate each prediction before combining it.
    logits = None
    for rotation in rotations:
        raw = model(torch.rot90(x, rotation, (-2, -1)))
        oriented = [13+i for i in scan_openings.ENDPOINT_ORDER[rotation]]
        pred = torch.cat((raw[:, oriented], raw[:, 33:44]) + ((raw[:, 21:33],) if rooms else ()), dim=1)
        pred = torch.rot90(pred, -rotation, (-2, -1))
        pred = torch.nn.functional.interpolate(pred, size=x.shape[-2:], mode='bilinear', align_corners=True)
        logits = pred if logits is None else logits + pred
    return logits[0] / len(rotations)


def _starts(length):
    if length <= TILE:
        return [0]
    count = -(-(length-OVERLAP) // (TILE-OVERLAP))
    return [round(i * (length-TILE) / (count-1)) for i in range(count)]


def _fit(width, height, factor):
    """Largest resize factor up to `factor` whose sheet needs at most MAX_TILES tiles."""
    while len(_starts(round(width*factor))) * len(_starts(round(height*factor))) > MAX_TILES:
        factor *= .96
    return factor


def _tiled(model, x, rotations):
    """Run the model on fixed square tiles with a white margin and blend the overlaps linearly."""
    import torch
    height, width = x.shape[-2:]
    total = torch.zeros((15, height, width), device=x.device)
    weight = torch.zeros((height, width), device=x.device)
    rise = torch.arange(1, OVERLAP+1, device=x.device, dtype=torch.float32)
    for top in _starts(height):
        for left in _starts(width):
            bottom, right = min(height, top+TILE), min(width, left+TILE)
            patch = torch.ones((1, 3, TILE, TILE), device=x.device)
            patch[:, :, :bottom-top, :right-left] = x[:, :, top:bottom, left:right]
            part = _average(model, patch, rotations)[:, :bottom-top, :right-left]
            taper = []
            for size, first, last in ((bottom-top, top == 0, bottom == height), (right-left, left == 0, right == width)):
                side = torch.full((size,), float(OVERLAP), device=x.device)
                if not first:
                    side[:OVERLAP] = rise
                if not last:
                    side[size-OVERLAP:] = rise.flip(0)
                taper.append(side)
            share = taper[0][:, None] * taper[1][None, :]
            total[:, top:bottom, left:right] += part * share
            weight[top:bottom, left:right] += share
    return total / weight


def _read(model, device, original, factor, rotations=(0, 1, 2, 3)):
    """Segmentation and endpoint planes after a nearest-neighbour resize of the drawing by about `factor`."""
    import cv2
    import torch
    height, width = original.shape[:2]
    factor = _fit(width, height, factor)
    target = (max(1, round(width*factor)), max(1, round(height*factor)))
    # CubiCasa produced its scale-normalised training images with nearest-neighbour resampling.
    rgb = cv2.resize(original, target, interpolation=cv2.INTER_NEAREST_EXACT) if target != (width, height) else original
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().to(device) / 127.5 - 1.
    averaged = _tiled(model, x, rotations)
    probabilities = averaged[4:].softmax(dim=0)
    mask = probabilities.argmax(dim=0).byte().cpu().numpy()
    return mask, probabilities[:3].cpu().numpy(), averaged[:4].cpu().numpy(), target


def _door_lengths(doors, grid):
    return [max(box[2]-box[0], box[3]-box[1]) / grid for box in doors]


def _openings(model, device, original, lengths):
    """Read windows and doors again at a scale set by the drawing's doors, or None to keep the first reading."""
    width = original.shape[1]
    length = scan_openings.door_length(lengths)
    if length is None:
        # Too few doors at the first scale to size them. One orientation of an enlarged sheet is enough for that.
        guess = min(4., max(1., PROBE_SIDE / max(original.shape[:2])))
        mask, probabilities, _, target = _read(model, device, original, guess, rotations=(0,))
        probed = _door_lengths(_components(mask, probabilities, (2,))[0][2], target[0]/width)
        length = scan_openings.door_length(max(probed, lengths, key=len), 2)
        if length is None:
            return None
    mask, probabilities, endpoints, target = _read(model, device, original, scan_openings.resize_factor(length))
    grid = target[0] / width
    unit = grid * length / scan_openings.DOOR
    # The doors that sized the drawing must show again at that size. If they do not, the sizing was wrong.
    seen = scan_openings.door_length(_door_lengths(_components(mask, probabilities, (2,), unit)[0][2], grid), 2)
    if seen is None or not 2/3 <= seen/length <= 3/2:
        return None
    return _marks(_boxes(mask, probabilities, endpoints, (1, 2), unit), *target)


def _first(data, model, device):
    """First reading, on a grid of at most 896 pixels a side.

    Returns the marks of every class, the door lengths that size the drawing and the
    room map planes, together with the decoded sheet; None for unsupported input.
    """
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
        original = np.array(image.convert('RGB'))
    rgb = cv2.resize(original, target, interpolation=cv2.INTER_AREA) if target != (width, height) else original
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().to(device) / 127.5 - 1.
    with torch.inference_mode():
        averaged = _average(model, x, rooms=True)
        icons = averaged[4:15].softmax(dim=0)
        probabilities = icons.cpu().numpy()
        mask = probabilities.argmax(axis=0)
        marks = _marks(_boxes(mask, probabilities, averaged[:4].cpu().numpy()), *target)
        # Door components of the segmentation size the drawing; they do not depend on the endpoint decoder.
        lengths = _door_lengths(_components(mask, probabilities, (2,))[0][2], scale)
        # The room-map reader measures on class probabilities quantised to bytes.
        planes = tuple((plane * 255).round().to(torch.uint8).cpu().numpy()
                       for plane in (averaged[15:].softmax(dim=0), icons))
    return {'marks': marks, 'lengths': lengths, 'planes': planes}, original


def _second(model, device, original, lengths):
    """Windows and doors from the second reading, or None to keep the first."""
    import torch
    with torch.inference_mode():
        try:
            return _openings(model, device, original, lengths)
        except RuntimeError:
            return None


def _infer(data, model, device):
    """Marks per class: the first reading, with windows and doors from the second reading when it holds."""
    read = _first(data, model, device)
    if read is None:
        return None
    first, original = read
    result = dict(first['marks'])
    openings = _second(model, device, original, first['lengths'])
    if openings is not None:
        result.update(openings)
    return result


def _first_cached(key, image_bytes, model, device):
    """First reading of a drawing, and its decoded sheet when it was read just now. The caller holds LOCK."""
    first = FIRST.get(key)
    if first is not None:
        FIRST.move_to_end(key)
        return first, None
    read = _first(image_bytes, model, device)
    if read is None:
        return None, None
    FIRST[key] = read[0]
    if len(FIRST) > 2:
        FIRST.popitem(last=False)
    return read


def _cached_inventory(image_bytes):
    """Return all four classes (cached by exact input bytes) or None."""
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
            model, device = _load(code, weights)
            first, original = _first_cached(key, image_bytes, model, device)
            if first is None:
                return None
            if original is None:
                # The room-map reader asked for this drawing first; only the second reading is left.
                import numpy as np
                from PIL import Image
                with Image.open(io.BytesIO(image_bytes)) as image:
                    original = np.array(image.convert('RGB'))
            result = dict(first['marks'])
            openings = _second(model, device, original, first['lengths'])
            if openings is not None:
                result.update(openings)
        except (ImportError, OSError, RuntimeError, ValueError):
            return None
        record = {'image_sha256':digest, 'classes':result}
        CACHE[key] = record
        if len(CACHE) > 16:
            CACHE.popitem(last=False)
        return record


def room_planes(image_bytes):
    """Room (12) and icon (11) class probabilities of the first reading as uint8 planes on its grid, or None.

    The room-map reader takes them from here, so a drawing passes through the network
    once for both readers whichever question comes first.
    """
    if not available():
        return None
    code, weights = _locations()
    key = (code, weights, hashlib.sha256(image_bytes).hexdigest())
    with LOCK:
        try:
            first, _ = _first_cached(key, image_bytes, *_load(code, weights))
        except (ImportError, OSError, RuntimeError, ValueError):
            return None
    return first['planes'] if first else None


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
