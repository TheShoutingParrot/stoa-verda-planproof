"""Identify rendered openings and plumbing symbols in Junction's Swiss Dwellings DXFs."""

import math


KINDS = ("doors", "windows", "toilets", "washbasins", "bathtubs", "showers")
# Vertex counts identify the tessellated symbols in this particular renderer.
# The two 48-point oval bowls are separated by their drain circle or cistern line.
TUB_INSERT = 69
OVAL_BOWL = 48
TRAY_INSERT = 5


def _points(entity, scale):
    return [[float(x) * scale, float(y) * scale] for x, y in zip(entity[10], entity[20], strict=True)]


def _middle(points):
    n = len(points)
    return [sum(p[axis] for p in points) / n for axis in (0, 1)]


def _inside(point, polygon):
    x, y = point
    edges = zip(polygon, polygon[1:] + polygon[:1])
    crossings = sum(1 for (a, b), (c, d) in edges
                    if (b > y) != (d > y) and x < a + (c - a) * (y - b) / (d - b))
    return crossings % 2 == 1


def _mark(kind, handle, outline):
    return {"id": f"{kind}-{handle}", "center": _middle(outline), "lines": [outline + [outline[0]]]}


def _circle(center, radius):
    return [[center[0] + radius * math.cos(i * math.tau / 24),
             center[1] + radius * math.sin(i * math.tau / 24)] for i in range(25)]


def extract_objects(entities, scale):
    """Return one evidence object per source opening or supported fixture symbol.

    In the Swiss rendering, one explicit frame delineates each opening; a pair of
    opening leaves or panes can produce several secondary strokes. Plumbing objects
    have outer footprints with distinct inner bowl, cistern and drain details.
    """
    result = {kind: [] for kind in KINDS}
    footprints = []
    details = []
    for entity in entities:
        layer = next(iter(entity.get(8, [])), "")
        kind = entity[0][0]
        if layer not in ("DOOR", "WINDOW", "FIXTURE") or kind not in ("LWPOLYLINE", "CIRCLE"):
            continue
        p = _points(entity, scale)
        closed = bool(int((entity.get(70) or ["0"])[0]) & 1)
        handle = entity[5][0]
        if layer == "DOOR" and kind == "LWPOLYLINE" and len(p) >= 4 and p[0] == p[-1]:
            result["doors"].append(_mark("doors", handle, p[:-1]))
        elif layer == "WINDOW" and closed:
            result["windows"].append(_mark("windows", handle, p))
        elif layer == "FIXTURE" and kind == "LWPOLYLINE" and closed:
            footprints.append((handle, p))
        elif layer == "FIXTURE":
            if kind == "CIRCLE":
                radius = float(entity[40][0]) * scale
                details.append(("circle", _circle(p[0], radius), p[0], radius))
            else:
                details.append((len(p), p, _middle(p), None))
    for handle, poly in footprints:
        inner = [item for item in details if _inside(item[2], poly)]
        strokes = {item[0] for item in inner}
        center = _middle(poly)
        # On narrow bathtub footprints the renderer leaves just the fixed 25 mm
        # drain, on the long axis 0.20 m from an end. Basins have a centered drain.
        sides = [(math.dist(a, b), a, b) for a, b in zip(poly, poly[1:] + poly[:1])]
        length, a, b = max(sides)
        tub_drains = []
        if length > 0.40:
            offset = (length / 2 - 0.20) / length
            ends = [[center[i] + sign * (b[i] - a[i]) * offset for i in (0, 1)] for sign in (-1, 1)]
            tub_drains = [d for d in inner if d[0] == "circle" and abs(d[3] - 0.025) < 1e-5
                          and any(math.dist(d[2], end) <= 1e-4 for end in ends)]
        centered_basin = any(d[0] == "circle" and math.dist(d[2], center) <= 1e-4 for d in inner)
        corresponding_tub = any(d[0] == TUB_INSERT and math.dist(d[2], center) <= 0.04 for d in inner)
        if corresponding_tub or tub_drains:
            key = "bathtubs"
        elif OVAL_BOWL in strokes:
            key = "washbasins" if centered_basin else "toilets" if 2 in strokes else None
        elif TRAY_INSERT in strokes and "circle" in strokes:
            key = "showers"
        else:
            key = None
        if key is not None:
            item = _mark(key, handle, poly)
            item["lines"].extend(stroke[1] for stroke in inner)
            result[key].append(item)
    return result
