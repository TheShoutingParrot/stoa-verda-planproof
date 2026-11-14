"""Answer room and storey questions from the CubiCasa5K room map when label OCR alone cannot.

The network's room head separates background, outdoor space, walls and nine kinds
of interior space; its icon head also marks sauna benches. This reader joins those
regions with the printed room labels and reads the wet rooms a second time at a
larger scale. Model setup is described in docs/scan-objects.md and the rules in
docs/scan-layout.md. No inference input can identify a benchmark drawing, its
split, or its annotations.
"""
from collections import OrderedDict
import hashlib
import io
import math
import shutil
import subprocess
import sys
import tempfile
import threading

from scripts import scan_objects, scan_rooms, scan_storeys

ROOM_NAMES = ('Background', 'Outdoor', 'Wall', 'Kitchen', 'Living room', 'Bedroom', 'Bath', 'Entry',
              'Railing', 'Storage', 'Garage', 'Other room')
ICON_NAMES = ('No icon', 'Window', 'Door', 'Closet', 'Electrical appliance', 'Toilet bowl',
              'Sink or washbasin', 'Sauna bench', 'Fireplace', 'Bathtub', 'Chimney')
OUTDOOR, WALL, KITCHEN, LIVING, BEDROOM, BATH, ENTRY, RAILING, STORAGE, GARAGE, OTHER = range(1, 12)
INTERIOR = (KITCHEN, LIVING, BEDROOM, BATH, ENTRY, STORAGE, GARAGE, OTHER)
TOILET, SINK, BENCH, BATHTUB = 5, 6, 7, 9
SYMBOLS = {'toilet': TOILET, 'sink': SINK, 'bench': BENCH, 'tub': BATHTUB}
COORDS = 'xyxy_top_left_0_to_1000'
METHOD = 'local_room_layout'
BATHROOM_SHARE = .03  # a wet room this large, as a share of all interior area, can hold a shower
STOREY_SHARE = .75    # uncaptioned storeys of one building have at least this share of the largest panel's rooms
BENCH_SHARE = .004    # smallest sauna bench symbol, as a share of all interior area
FAINT_BENCH = .0002   # weak bench probability over more interior area than this forbids a zero
CACHE = OrderedDict()
PLAN_LOCK = threading.Lock()


def _infer(data, model, device):
    """Return (rooms, icons): uint8 class probabilities on the model grid, or None.

    Preprocessing and the four-orientation average match scan_objects._infer, so
    the icon planes are the ones the object reader sees.
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
        rgb = np.array(image.convert('RGB'))
    if target != (width, height):
        rgb = cv2.resize(rgb, target, interpolation=cv2.INTER_AREA)
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().to(device) / 127.5 - 1.
    logits = None
    with torch.inference_mode():
        for rotation in range(4):
            raw = model(torch.rot90(x, rotation, (-2, -1)))
            pred = torch.rot90(raw[:, 21:44], -rotation, (-2, -1))
            pred = torch.nn.functional.interpolate(pred, size=x.shape[-2:], mode='bilinear', align_corners=True)
            logits = pred if logits is None else logits + pred
        averaged = logits[0] / 4
        rooms = (averaged[:12].softmax(dim=0) * 255).round().to(torch.uint8).cpu().numpy()
        icons = (averaged[12:].softmax(dim=0) * 255).round().to(torch.uint8).cpu().numpy()
    return rooms, icons


def _components(mask, minimum):
    import cv2
    import numpy as np
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    found = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area >= minimum:
            found.append((index, area, (x, y, x+w, y+h)))
    return labels, found


def describe(rooms, icons):
    """Summarise the class planes as floor panels, room regions and fixture symbols.

    Pixel boxes are XYXY on the model grid. 'region_map' holds the index+1 of the
    room region at each pixel and 'panel_map' the index+1 of its floor panel.
    """
    import cv2
    import numpy as np
    classes = rooms.argmax(axis=0).astype(np.uint8)
    symbols = icons.argmax(axis=0).astype(np.uint8)
    height, width = classes.shape
    interior = np.isin(classes, INTERIOR)
    inside = int(interior.sum())

    # A floor panel is one connected body of walls and rooms. Background and
    # outdoor space separate the storeys drawn side by side on one sheet. A
    # dimension line read as wall must not bridge two panels, so hairlines are opened away.
    body = cv2.morphologyEx((interior | (classes == WALL)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    labels, bodies = _components(body, 1)
    panel_map = np.zeros(classes.shape, np.uint8)
    panels = []
    sized = sorted(((int(interior[labels == index].sum()), index, box) for index, _, box in bodies), reverse=True)
    for rooms_area, index, box in sized[:40]:
        if rooms_area < max(.004*classes.size, .02*sized[0][0]):
            break
        panels.append({'interior': rooms_area, 'box': box})
        panel_map[labels == index] = len(panels)

    region_map = np.zeros(classes.shape, np.uint16)
    regions = []
    for cls in INTERIOR + (OUTDOOR,):
        labels, found = _components(classes == cls, max(24, .004*inside))
        for index, area, box in found:
            mask = labels == index
            panel = np.bincount(panel_map[mask], minlength=1).argmax() if cls != OUTDOOR else 0
            regions.append({'kind': cls, 'area': area, 'box': box, 'panel': int(panel),
                            'score': round(float(rooms[cls][mask].mean()) / 255, 3)})
            region_map[mask] = len(regions)

    marks = {}
    for name, cls in SYMBOLS.items():
        labels, found = _components(symbols == cls, 12)
        items = []
        for index, area, box in found:
            mask = labels == index
            inside_regions = np.bincount(region_map[mask])
            region = int(inside_regions[1:].argmax()) + 1 if inside_regions[1:].sum() else 0
            if not region:
                # A symbol drawn over a wall line or an unclassified patch belongs to the room around it.
                x0, y0, x1, y1 = box
                near = np.bincount(region_map[max(0, y0-6):y1+6, max(0, x0-6):x1+6].ravel())
                region = int(near[1:].argmax()) + 1 if near[1:].sum() else 0
            items.append({'area': area, 'box': box, 'region': region,
                          'score': round(float(icons[cls][mask].mean()) / 255, 3)})
        marks[name] = items
    return {'size': (width, height), 'interior': inside, 'classes': classes, 'panels': panels,
            'panel_map': panel_map, 'regions': regions, 'region_map': region_map, 'symbols': marks,
            'faint_bench': int((icons[BENCH] >= 26).sum())}


def _locate(layout, box):
    """Room region (index+1, 0 for none) and room class under a 0-1000 box."""
    import numpy as np
    width, height = layout['size']
    x0, y0 = int(box[0]*width/1000), int(box[1]*height/1000)
    x1, y1 = max(x0+1, math.ceil(box[2]*width/1000)), max(y0+1, math.ceil(box[3]*height/1000))
    patch = layout['region_map'][y0:y1, x0:x1]
    if patch.size == 0:
        return 0, 0
    counts = np.bincount(patch.ravel())
    cls = int(np.bincount(layout['classes'][y0:y1, x0:x1].ravel(), minlength=12).argmax())
    if not counts[1:].sum():
        # Dark lettering is often classed as wall; the room around it is the one meant.
        counts = np.bincount(layout['region_map'][max(0, y0-8):y1+8, max(0, x0-8):x1+8].ravel())
    region = int(counts[1:].argmax()) + 1 if counts[1:].sum() else 0
    return region, cls


ZOOM_MARGIN = 24


def zoom_tiles(image, layout, kinds=(BATH,), limit=6):
    """Cut the wet rooms out of the source image and enlarge them onto one white sheet.

    Returns (sheet, tiles); each tile maps a sheet rectangle back to source pixels.
    """
    from PIL import Image
    grid_w, grid_h = layout['size']
    sx, sy = image.width / grid_w, image.height / grid_h
    wet = sorted((r for r in layout['regions'] if r['kind'] in kinds), key=lambda r: -r['area'])[:limit]
    tiles = []
    top = ZOOM_MARGIN
    for region in wet:
        x0, y0, x1, y1 = region['box']
        left, upper = max(0, int((x0-6)*sx)), max(0, int((y0-6)*sy))
        right, lower = min(image.width, math.ceil((x1+6)*sx)), min(image.height, math.ceil((y1+6)*sy))
        if right-left < 8 or lower-upper < 8:
            continue
        scale = min(4., max(1., 420 / min(right-left, lower-upper)))
        size = (round((right-left)*scale), round((lower-upper)*scale))
        if max(size) > 1600:
            scale *= 1600 / max(size)
            size = (round((right-left)*scale), round((lower-upper)*scale))
        tiles.append({'source': (left, upper, right, lower), 'top': top, 'size': size, 'scale': scale})
        top += size[1] + ZOOM_MARGIN
    if not tiles:
        return None, []
    sheet = Image.new('RGB', (max(t['size'][0] for t in tiles) + 2*ZOOM_MARGIN, top), 'white')
    for tile in tiles:
        part = image.crop(tile['source']).resize(tile['size'], Image.LANCZOS)
        sheet.paste(part, (ZOOM_MARGIN, tile['top']))
    return sheet, tiles


def zoom_restore(rows, sheet_size, tiles, source_size):
    """Map OCR rows read on the enlarged sheet back to 0-1000 source coordinates."""
    restored = []
    for row in rows:
        x0, y0, x1, y1 = (row['box'][0]*sheet_size[0]/1000, row['box'][1]*sheet_size[1]/1000,
                          row['box'][2]*sheet_size[0]/1000, row['box'][3]*sheet_size[1]/1000)
        middle = (y0+y1) / 2
        tile = next((t for t in tiles if t['top'] <= middle <= t['top']+t['size'][1]), None)
        if tile is None:
            continue
        left, upper = tile['source'][:2]
        box = [1000*(left + (x0-ZOOM_MARGIN)/tile['scale'])/source_size[0],
               1000*(upper + (y0-tile['top'])/tile['scale'])/source_size[1],
               1000*(left + (x1-ZOOM_MARGIN)/tile['scale'])/source_size[0],
               1000*(upper + (y1-tile['top'])/tile['scale'])/source_size[1]]
        box = [min(1000., max(0., round(v, 2))) for v in box]
        if box[2] > box[0] and box[3] > box[1]:
            restored.append({'text': row['text'], 'confidence': row['confidence'], 'box': box, 'engine': 'vision'})
    return restored


def zoom_rows(image_bytes, layout, orientation=1, kinds=(BATH,)):
    """Read room regions again at a larger scale with the sheet's reading direction and its reverse.

    Returns OCR rows in source coordinates, or None when the second look could not be completed.
    """
    if sys.platform != 'darwin' or not shutil.which('osascript'):
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = source.convert('RGB')
        sheet, tiles = zoom_tiles(image, layout, kinds)
        if sheet is None:
            return []
        rows = []
        with tempfile.NamedTemporaryFile(suffix='.png') as file:
            sheet.save(file.name)
            for direction in (orientation, {1: 3, 3: 1, 2: 4, 4: 2}.get(orientation, 3)):
                rows.extend(scan_rooms._vision(file.name, direction))
        return zoom_restore(rows, sheet.size, tiles, image.size)
    except (ImportError, OSError, subprocess.SubprocessError, ValueError):
        return None


def build_plan(inv, layout, zoomed=(), ink_views=()):
    """Join the OCR inventory with the room map. The result holds plain values in 0-1000 coordinates.

    'zoomed' holds the second-look rows, or None when that reading failed.
    """
    width, height = layout['size']
    looked = zoomed is not None
    zoomed = zoomed or ()

    def unit(box):
        scaled = [round(1000*box[0]/width), round(1000*box[1]/height),
                  round(1000*box[2]/width), round(1000*box[3]/height)]
        return [min(1000, max(0, v)) for v in scaled]

    labels = []
    for kind, items in inv.get('labels', {}).items():
        for item in items:
            region, cls = _locate(layout, item['box'])
            labels.append({'kind': kind, 'label': item['label'], 'box': item['box'], 'region': region,
                           'cls': cls, 'source': 'sheet'})
    unclear_wc = len(inv.get('possible_wc', ()))
    for row in sorted(zoomed, key=lambda r: -r['confidence']):
        if row['confidence'] < .47:
            continue
        if scan_rooms.letters(row['text']) in {'WG', 'W0'}:
            unclear_wc += 1
        for kind in scan_rooms._label(row['text']):
            if any(scan_rooms._same(row['box'], other['box']) for other in labels if other['kind'] == kind):
                continue
            region, cls = _locate(layout, row['box'])
            labels.append({'kind': kind, 'label': row['text'], 'box': row['box'], 'region': region,
                           'cls': cls, 'source': 'zoom'})
    regions = []
    inside = max(1, layout['interior'])
    for index, region in enumerate(layout['regions'], 1):
        held = {name: [m for m in marks if m['region'] == index] for name, marks in layout['symbols'].items()}
        regions.append({'kind': region['kind'], 'share': round(region['area']/inside, 4), 'box': unit(region['box']),
                        'panel': region['panel'], 'score': region['score'],
                        'toilets': len(held['toilet']), 'sinks': len(held['sink']),
                        'bench': round(sum(m['area'] for m in held['bench'])/inside, 4),
                        'tub': round(sum(m['area'] for m in held['tub'])/inside, 4),
                        'labels': [i for i, item in enumerate(labels) if item['region'] == index]})
    symbols = {name: [{'share': round(m['area']/inside, 4), 'box': unit(m['box']), 'region': m['region'],
                       'score': m['score']} for m in marks] for name, marks in layout['symbols'].items()}
    largest = max((p['interior'] for p in layout['panels']), default=1)
    panels = [{'share': round(p['interior']/largest, 4), 'box': unit(p['box'])} for p in layout['panels']]
    return {'size': [width, height], 'panels': panels, 'regions': regions, 'symbols': symbols,
            'faint_bench': round(layout['faint_bench']/inside, 5), 'labels': labels,
            'titles': inv.get('titles', []), 'storeys': inv.get('storeys', []),
            'floor_markers': inv.get('floor_markers', []), 'unclear_wc': unclear_wc,
            'explicit_no_sauna': len(inv.get('explicit_no_sauna', ())),
            'ink': [len(view) for view in ink_views],
            'sheet_read': bool(inv.get('vision')), 'looked': looked}


def _report(answer, evidence, reason=None, coverage=None):
    report = {'status': 'answered', 'answer': answer, 'evidence': evidence, 'method': METHOD,
              'coordinate_system': COORDS}
    if reason:
        report['reason'] = reason
    if coverage is not None:
        report['coverage_evidence'] = coverage
    return report


def _mark(label, box):
    """One evidence box; a box may never be the whole sheet."""
    box = [min(1000, max(0, v)) for v in box]
    if box[2] <= box[0]:
        box[2] = min(1000, box[0]+1)
        box[0] = box[2]-1
    if box[3] <= box[1]:
        box[3] = min(1000, box[1]+1)
        box[1] = box[3]-1
    if box == [0, 0, 1000, 1000]:
        box = [1, 1, 999, 999]
    return {'label': label, 'box': box}


def _distinct(marks):
    seen, kept = set(), []
    for mark in marks:
        key = tuple(mark['box'])
        if key not in seen:
            seen.add(key)
            kept.append(mark)
    return kept


def _named(plan, kind):
    return [item for item in plan['labels'] if item['kind'] == kind]


def _kind_at(plan, item):
    return plan['regions'][item['region']-1]['kind'] if item['region'] else None


def _region_labels(plan, region, *kinds):
    return [plan['labels'][i] for i in region['labels'] if plan['labels'][i]['kind'] in kinds]


def floor_panels(plan, share=.25):
    return [panel for panel in plan['panels'] if panel['share'] >= share]


def storeys(plan):
    """Count the separate bodies of walls and rooms; decline when captions or raw ink disagree."""
    panels = floor_panels(plan)
    if not panels or len(floor_panels(plan, .10)) != len(panels):
        return None  # a mid-sized extra body may be an outbuilding or a small upper floor
    if len(panels) == 1:
        if plan['storeys'] or plan['floor_markers']:
            return None  # a level caption on a one-panel sheet points at a floor that is not separated
        if len(plan['ink']) == 4 and min(plan['ink']) >= 2:
            return None  # two panels drawn wall to wall merge in the room map but not in the ink
        return _report(1, [_mark('Floor plan drawn as one connected body of rooms', panels[0]['box'])])
    captions = len(plan['storeys'])
    if captions >= 2 and captions != len(panels):
        return None
    if not captions and min(panel['share'] for panel in panels) < STOREY_SHARE:
        return None  # without a level caption a much smaller body may be a garage or sauna building
    marks = [_mark('Floor panel %d' % number, panel['box']) for number, panel in enumerate(panels, 1)]
    if len(_distinct(marks)) != len(marks):
        return None
    return _report(len(marks), marks)


def kitchens(plan):
    """One kitchen region in the room map and no sign of a second kitchen."""
    regions = [r for r in plan['regions'] if r['kind'] == KITCHEN]
    if len(regions) != 1 or regions[0]['share'] < .04:
        return None
    if len(_named(plan, 'kitchen')) > 1 or len(plan['titles']) > 1:
        return None
    inside = _region_labels(plan, regions[0], 'kitchen')
    label = 'Kitchen area' + (' labelled ' + inside[0]['label'] if inside else '')
    return _report(1, [_mark(label, regions[0]['box'])])


def _wet_rooms(plan):
    return [r for r in plan['regions'] if r['kind'] == BATH]


def _gap(a, b):
    """Distance between two boxes along the axes, zero when they touch or overlap."""
    return max(0, max(a[0], b[0]) - min(a[2], b[2])) + max(0, max(a[1], b[1]) - min(a[3], b[3]))


def saunas(plan):
    """A sauna bench symbol or a sauna label inside a wet room; zero only when every wet room is identified."""
    benches = plan['symbols']['bench']
    area = sum(m['share'] for m in benches)
    labels = _named(plan, 'sauna')
    if area >= BENCH_SHARE:
        largest = max(benches, key=lambda m: m['share'])
        if any(m['share'] >= BENCH_SHARE/2 and _gap(m['box'], largest['box']) > 80 for m in benches):
            return None  # bench symbols far apart may belong to two saunas
        return _report(1, [_mark('Sauna bench', largest['box'])])
    wet = _wet_rooms(plan)
    inside = [item for item in labels if _kind_at(plan, item) == BATH]
    if inside:
        if len(labels) != len(inside) or len({item['region'] for item in inside}) != 1:
            return None
        return _report(1, [_mark('Sauna label ' + inside[0]['label'], inside[0]['box'])])
    if labels or plan['faint_bench'] > FAINT_BENCH or any(t.get('sauna') for t in plan['titles']) or not wet:
        return None
    if not plan['looked']:
        return None  # a zero needs the completed second look at the wet rooms
    coverage = []
    for region in wet:
        named = _region_labels(plan, region, 'washroom', 'wc')
        if not (region['toilets'] or region['sinks'] or named):
            return None
        what = named[0]['label'] if named else 'toilet or basin'
        coverage.append(_mark('Wet room without a sauna bench: ' + what, region['box']))
    return _report(0, [], 'No sauna bench or sauna label is drawn, and every wet room is a bathroom or WC.',
                   _distinct(coverage))


def separate_wcs(plan):
    """WC labels inside wet rooms; zero when the only wet room is a full bathroom."""
    if plan['unclear_wc']:
        return None
    wet = _wet_rooms(plan)
    labels = _named(plan, 'wc')
    if labels:
        if any(_kind_at(plan, item) != BATH for item in labels):
            return None
        rooms = {}
        for item in labels:
            rooms.setdefault(item['region'], item)
        for index, region in enumerate(plan['regions'], 1):
            if region['kind'] == BATH and index not in rooms and region['toilets'] and not region['bench'] \
                    and region['share'] < BATHROOM_SHARE and not _region_labels(plan, region, 'washroom', 'sauna'):
                return None  # a small unnamed toilet room may be a second WC
        return _report(len(rooms), [_mark('WC label ' + item['label'], item['box']) for item in rooms.values()])
    if len(wet) != 1 or wet[0]['share'] < BATHROOM_SHARE or len(plan['symbols']['toilet']) > 1 or not plan['looked']:
        return None
    named = _region_labels(plan, wet[0], 'washroom')
    what = named[0]['label'] if named else 'the only wet room'
    return _report(0, [], 'The plan has a single wet room and no room labelled WC.',
                   [_mark('Bathroom: ' + what, wet[0]['box'])])


def _printed(plan):
    """The sheet carries printed room names: at least three labels of two kinds, as the label reader requires."""
    return len(plan['labels']) >= 3 and len({item['kind'] for item in plan['labels']}) >= 2


def bathrooms(plan):
    """Bathroom labels inside wet rooms, or the single bathroom-sized wet room of a labelled plan."""
    labels = _named(plan, 'washroom')
    wet = [(index, region) for index, region in enumerate(plan['regions'], 1) if region['kind'] == BATH]
    if labels:
        if any(_kind_at(plan, item) != BATH for item in labels):
            return None
        rooms = {}
        for item in labels:
            rooms.setdefault(item['region'], item)
        for index, region in wet:
            if index not in rooms and region['share'] >= BATHROOM_SHARE and not region['bench'] \
                    and not _region_labels(plan, region, 'wc', 'sauna'):
                return None  # a second bathroom-sized wet room whose name was not read
        return _report(len(rooms), [_mark('Bathroom label ' + item['label'], item['box']) for item in rooms.values()])
    sized = [region for _, region in wet if region['share'] >= BATHROOM_SHARE and not region['bench']
             and not _region_labels(plan, region, 'wc', 'sauna')]
    if len(sized) != 1 or not (sized[0]['toilets'] or sized[0]['sinks']) or not _printed(plan) or not plan['looked']:
        return None
    return _report(1, [_mark('Bathroom area with a toilet or basin', sized[0]['box'])])


OUTDOOR_NAMES = {'TERASSI', 'KUISTI'}


def balconies(plan):
    """Balcony labels on outdoor areas; zero when no outdoor area could be a balcony."""
    labels = _named(plan, 'balcony')
    outdoor = [r for r in plan['regions'] if r['kind'] == OUTDOOR and r['share'] >= .01]
    if labels:
        if any(_kind_at(plan, item) != OUTDOOR for item in labels):
            return None
        return _report(len(labels), [_mark('Balcony label ' + item['label'], item['box']) for item in labels])
    panels = floor_panels(plan)
    if not panels:
        return None
    if not outdoor:
        return _report(0, [], 'The room map shows no balcony or other outdoor area and no balcony label was read.',
                       _distinct([_mark('Floor plan without an outdoor area', panel['box']) for panel in panels]))
    coverage = []
    for region in outdoor:
        named = [item for item in _region_labels(plan, region, 'other')
                 if scan_rooms.letters(item['label']) in OUTDOOR_NAMES]
        if not named:
            return None
        coverage.append(_mark('Outdoor area labelled ' + named[0]['label'], region['box']))
    return _report(0, [], 'Every outdoor area on the plan is labelled as a terrace or porch.', _distinct(coverage))


def bedrooms(plan):
    """Bedroom labels that each sit in a bedroom region, with no bedroom region left unnamed."""
    labels = _named(plan, 'bedroom')
    if not labels or any(_kind_at(plan, item) != BEDROOM for item in labels):
        return None
    numbers = [scan_rooms.re.fullmatch(r'(?:MH|SOVRUM)\s*[- ]?(\d{1,2})', scan_rooms.letters(item['label']))
               for item in labels]
    if any(found and int(found[1]) > len(labels) for found in numbers):
        return None
    named = {item['region'] for item in labels}
    for index, region in enumerate(plan['regions'], 1):
        if region['kind'] == BEDROOM and region['share'] >= .04 and index not in named:
            return None
    return _report(len(labels), [_mark('Bedroom label ' + item['label'], item['box']) for item in labels])


RULES = {'storeys': storeys, 'kitchen': kitchens, 'sauna': saunas, 'wc': separate_wcs,
         'washroom': bathrooms, 'balcony': balconies, 'bedroom': bedrooms}
# Room regions that are read again at a larger scale before the family's rule runs.
SECOND_LOOK = {'sauna': BATH, 'wc': BATH, 'washroom': BATH, 'bedroom': BEDROOM}


def answer(plan, name):
    """Apply the rule for one question family; every counted instance must have its own box."""
    rule = RULES.get(name)
    # Every rule lets a caption or a second label veto its count, so the sheet OCR must have completed.
    report = rule(plan) if rule and plan and plan.get('sheet_read') else None
    if report and len(_distinct(report['evidence'])) != report['answer']:
        return None
    return report


def category(question):
    """The room kind or 'storeys' for a whole-plan count question this reader supports."""
    if not isinstance(question, str):
        return None
    name = scan_rooms.category(question)
    if name is None and scan_storeys.QUESTION.fullmatch(' '.join(question.strip().split())):
        name = 'storeys'
    return name if name in RULES else None


def plan(image_bytes, name):
    """Build the joined plan for one question family (cached by exact input bytes), or None.

    The room map is computed once per drawing. Rooms are read a second time only for
    the families in SECOND_LOOK, so the answer never depends on which question came first.
    """
    if not image_bytes.startswith(b'\x89PNG\r\n\x1a\n') or not scan_objects.available():
        return None
    code, weights = scan_objects._locations()
    key = (code, weights, hashlib.sha256(image_bytes).hexdigest())
    with PLAN_LOCK:
        entry = CACHE.get(key)
        if entry is None:
            inv = scan_rooms.inventory(image_bytes)
            try:
                with scan_objects.LOCK:
                    planes = _infer(image_bytes, *scan_objects._load(code, weights))
                if planes is None:
                    return None
                entry = {'inv': inv, 'layout': describe(*planes), 'views': scan_storeys.panel_views(image_bytes),
                         'plans': {}}
            except (ImportError, OSError, RuntimeError, ValueError):
                return None
            CACHE[key] = entry
            if len(CACHE) > 8:
                CACHE.popitem(last=False)
        CACHE.move_to_end(key)
        kind = SECOND_LOOK.get(name)
        if kind not in entry['plans']:
            rows = zoom_rows(image_bytes, entry['layout'], entry['inv'].get('orientation', 1), (kind,)) if kind else []
            entry['plans'][kind] = build_plan(entry['inv'], entry['layout'], rows, entry['views'])
        return entry['plans'][kind]


def predict(image_bytes, question):
    """Return a count grounded in the room map and labels of the supplied scan, or None."""
    name = category(question)
    if name is None:
        return None
    return answer(plan(image_bytes, name), name)
