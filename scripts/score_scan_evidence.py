"""Evaluate sealed opening/fixture boxes against CubiCasa's original vector annotations."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = '{http://www.w3.org/2000/svg}'
IDENTITY = (1, 0, 0, 1, 0, 0)
CATEGORIES = {
    'doors': {'Door'}, 'windows': {'Window'}, 'toilet bowls': {'Toilet'},
    'sinks': {'Sink', 'DoubleSink', 'DoubleSinkRight', 'RoundSink', 'SideSink', 'CornerSink'}
}


def compose(a, b):
    x, y, u, v, p, q = a
    X, Y, U, V, P, Q = b
    return (x*X+u*Y, y*X+v*Y, x*U+u*V, y*U+v*V, x*P+u*Q+p, y*P+v*Q+q)


NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^()]*)\)")


def numbers(raw):
    if NUMBER.sub('', raw).strip(' ,\n\t\r'):
        raise ValueError('Unsupported SVG numeric value: ' + raw)
    return [float(v) for v in NUMBER.findall(raw)]


def rotation(angle):
    angle = math.radians(angle)
    return math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0


def matrix(node):
    transform = node.get('transform', '').strip()
    result = IDENTITY
    if TRANSFORM.sub('', transform).strip(' ,\n\t\r'):
        raise ValueError('Unsupported annotation transform: ' + transform)
    for name, args in TRANSFORM.findall(transform):
        v = numbers(args)
        if name == 'matrix' and len(v) == 6:
            part = v
        elif name == 'translate' and len(v) in (1, 2):
            part = (1, 0, 0, 1, v[0], v[1] if len(v) == 2 else 0)
        elif name == 'scale' and len(v) in (1, 2):
            part = (v[0], 0, 0, v[-1], 0, 0)
        elif name == 'rotate' and len(v) in (1, 3):
            part = rotation(v[0])
            if len(v) == 3:
                _, x, y = v
                part = compose(compose((1,0,0,1,x,y), part), (1,0,0,1,-x,-y))
        elif name in ('skewX', 'skewY') and len(v) == 1:
            tangent = math.tan(math.radians(v[0]))
            part = (1,0,tangent,1,0,0) if name == 'skewX' else (1,tangent,0,1,0,0)
        else:
            raise ValueError('Unsupported annotation transform: ' + transform)
        result = compose(result, part)
    return result


def point(m, xy):
    a,b,c,d,e,f = m
    return complex(a*xy.real + c*xy.imag + e, b*xy.real + d*xy.imag + f)


def bounds(points):
    return (min(p.real for p in points), min(p.imag for p in points),
            max(p.real for p in points), max(p.imag for p in points))


def ellipse_bounds(m, center, axis_u, axis_v, start=0., sweep=math.tau):
    # After an affine map an ellipse is still c + u*cos(t) + v*sin(t).
    # Its four possible coordinate extrema have zero x or y derivative.
    origin = point(m, center)
    u = point(m, axis_u) - point(m, 0j)
    v = point(m, axis_v) - point(m, 0j)
    angles = [start, start + sweep]
    for extremum in (math.atan2(v.real, u.real), math.atan2(v.imag, u.imag)):
        for phi in (extremum, extremum + math.pi):
            distance = (phi-start) % math.tau if sweep >= 0 else (start-phi) % math.tau
            if distance <= abs(sweep) + 1e-12:
                angles.append(phi)
    return bounds([origin + u*math.cos(t) + v*math.sin(t) for t in angles])


def path_bounds(raw, m):
    try:
        from svgpathtools import Arc, parse_path
    except ImportError as exc:
        raise RuntimeError('SVG path evaluation requires svgpathtools==1.8.0 (uv run --with svgpathtools==1.8.0 ...).') from exc
    result = []
    for seg in parse_path(raw):
        if isinstance(seg, Arc):
            angle = math.radians(seg.rotation)
            direction = complex(math.cos(angle), math.sin(angle))
            result.append(ellipse_bounds(m, seg.center, seg.radius.real * direction,
                1j * seg.radius.imag * direction, math.radians(seg.theta), math.radians(seg.delta)))
        else:
            # Affine transforms commute with Bezier interpolation. Bounding the
            # transformed curve, rather than its control points, finds true extrema.
            transformed = type(seg)(*(point(m, p) for p in seg.bpoints()))
            x0, x1, y0, y1 = transformed.bbox()
            result.append((x0, y0, x1, y1))
    return result


def shape_bounds(node, parent_matrix, outline=False):
    m = compose(parent_matrix, matrix(node))
    tag = node.tag.removeprefix(NS)
    classes = node.get('class', '').split()
    if tag in ('title','desc','metadata','defs') or 'Name' in classes or 'Direction' in classes:
        return []
    if not outline and (node.get('display') == 'none' or re.search(r'(?:^|;)\s*display\s*:\s*none', node.get('style',''))):
        return []
    if tag == 'g':
        return [box for child in node for box in shape_bounds(child, m, outline)]
    if tag in ('polygon','polyline'):
        coords = numbers(node.get('points', ''))
        if len(coords) < 4 or len(coords) % 2:
            raise ValueError('Invalid SVG points on ' + tag)
        return [bounds([point(m, complex(x,y)) for x,y in zip(coords[::2],coords[1::2])])]
    def attr(name, default='0'):
        return float(node.get(name, default))
    if tag == 'line':
        return [bounds([point(m, complex(attr('x1'),attr('y1'))), point(m, complex(attr('x2'),attr('y2')))])]
    if tag in ('circle', 'ellipse'):
        rx, ry = (attr('r'), attr('r')) if tag == 'circle' else (attr('rx'), attr('ry'))
        if min(rx, ry) <= 0:
            return []
        return [ellipse_bounds(m, complex(attr('cx'), attr('cy')), rx, 1j * ry)]
    if tag == 'rect':
        x,y,w,h = (attr(k) for k in ('x','y','width','height'))
        if min(w,h) <= 0:
            return []
        rx = min(w/2, attr('rx', node.get('ry', '0')))
        ry = min(h/2, attr('ry', node.get('rx', '0')))
        if rx <= 0 or ry <= 0:
            return [bounds([point(m, complex(i,j)) for i in (x,x+w) for j in (y,y+h)])]
        return [ellipse_bounds(m, complex(cx,cy), rx, 1j*ry, start, math.pi/2)
                for cx,cy,start in ((x+w-rx,y+h-ry,0), (x+rx,y+h-ry,math.pi/2),
                                    (x+rx,y+ry,math.pi), (x+w-rx,y+ry,3*math.pi/2))]
    if tag == 'path':
        return path_bounds(node.attrib['d'], m)
    raise ValueError('Unsupported geometry in reference footprint: ' + tag)


def footprint(node, inherited, kind):
    # Openings are measured at the threshold. A swing arc is a separate glyph.
    direct = list(node.findall(NS+'polygon'))
    groups = [g for g in node.findall(NS+'g') if 'BoundaryPolygon' in g.get('class','').split()]
    selected = (direct or groups) if kind in ('Door','Window') else (groups or direct)
    ring = compose(inherited, matrix(node))
    shapes = [box for child in (selected or list(node)) for box in shape_bounds(child, ring, bool(selected))]
    if not shapes:
        raise ValueError(f'Missing actual geometry for {kind} footprint')
    return (min(b[0] for b in shapes), min(b[1] for b in shapes),
            max(b[2] for b in shapes), max(b[3] for b in shapes))


def reference_boxes(svg, size, category):
    """CubiCasa's annotations use scaled-image pixels, independently of SVG viewBox."""
    root = ET.fromstring(svg)
    parents = {child: parent for parent in root.iter() for child in parent}
    w, h = size
    boxes = []
    for node in root.iter(NS + 'g'):
        classes = node.get('class', '').split()
        kind = node.get('id') if node.get('id') in ('Door', 'Window') else (
            classes[1] if len(classes) >= 2 and classes[0] == 'FixedFurniture' else '')
        if kind not in CATEGORIES[category]:
            continue
        t = IDENTITY
        current = parents.get(node)
        while current is not None:
            t = compose(matrix(current), t)
            current = parents.get(current)
        x0,y0,x1,y1 = footprint(node, t, kind)
        if not all(map(math.isfinite, (x0,y0,x1,y1))) or x1 <= x0 or y1 <= y0:
            raise ValueError(f'Degenerate {kind} footprint')
        boxes.append([x0*1000/w,y0*1000/h,x1*1000/w,y1*1000/h])
    return boxes


def iou(a, b):
    intersection = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0, min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0


def match_count(boxes, references):
    matched = {}
    def assign(i, seen):
        for j in candidates[i]:
            if j not in seen:
                seen.add(j)
                if j not in matched or assign(matched[j], seen):
                    matched[j] = i
                    return True
        return False
    candidates = [[j for j,r in enumerate(references) if iou(b,r) >= .25] for b in boxes]
    return sum(assign(i, set()) for i in range(len(boxes)))


def reports(path):
    source = path.glob('*.json') if path.is_dir() else [path]
    rows = {}
    for file in source:
        for raw in file.read_text().splitlines() if not path.is_dir() else [file.read_text()]:
            data = json.loads(raw)
            if isinstance(data, dict) and 'path' in data and 'question' in data:
                rows[(data['path'], data['question'])] = data
    return rows


def run(questions, upstream, before, after):
    buckets = {name: defaultdict(Counter) for name in ('before','after')}
    comparable = {name: defaultdict(Counter) for name in buckets}
    positive = {name: Counter() for name in buckets}
    per_question = []
    with ZipFile(upstream) as z:
        for row in questions:
            cat = row['category']
            if cat not in CATEGORIES:
                continue
            key = row['path'], row['question']
            base = 'cubicasa5k/' + Path(row['path']).stem.replace('-', '/') + '/'
            original = z.read(base + 'F1_original.png')
            if hashlib.sha256(original).hexdigest() != row['image_sha256']:
                raise ValueError('Original image digest mismatch: ' + row['path'])
            with z.open(base + 'F1_scaled.png') as f:
                scaled = struct.unpack('>II', f.read(24)[16:24])
            refs = reference_boxes(z.read(base+'model.svg'), scaled, cat)
            service_available = all(pred[key]['status'] != 'unavailable' for pred in (before, after))
            entry = dict(path=row['path'], category=cat, reference_count=len(refs),
                         both_readers_available=service_available)
            if 'gold' in row:
                entry['reference_count_agrees_with_gold'] = len(refs) == row['gold']
            for name,pred in [('before',before[key]), ('after',after[key])]:
                if pred['image_sha256'] != row['image_sha256']:
                    raise ValueError('Prediction bound to different bytes')
                boxes = [item['box'] for item in pred.get('evidence', [])]
                matched = match_count(boxes, refs)
                metrics = dict(questions=1, reference=len(refs), proposed=len(boxes), matched=matched,
                    fully_grounded=int(pred['status']=='answered' and matched==len(refs)==len(boxes)))
                entry[name] = metrics
                buckets[name][cat].update(metrics)
                buckets[name]['all'].update(metrics)
                if service_available:
                    comparable[name][cat].update(metrics)
                    comparable[name]['all'].update(metrics)
                    if refs:
                        positive[name].update(metrics)
            per_question.append(entry)
    return dict(iou_threshold=.25, by_reader=buckets, common_service_available=comparable,
                positive_common_service_available=positive, questions=per_question)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('questions', 'upstream', 'before', 'after', 'output'):
        parser.add_argument('--'+arg, type=Path, required=True)
    args = parser.parse_args()
    output = run(json.loads(args.questions.read_text()), args.upstream, reports(args.before), reports(args.after))
    args.output.write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps({k:v['all'] for k,v in output['by_reader'].items()}))
