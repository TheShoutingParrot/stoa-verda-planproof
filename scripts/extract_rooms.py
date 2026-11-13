"""Export measured rooms and source geometry from a Junction Swiss Dwellings ASCII DXF."""

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STEM = "site1102_bldg2242_floor10281"
DEFAULT_DXF = ROOT / "public" / "data" / "swiss" / f"{DEFAULT_STEM}.dxf"
DEFAULT_JSON = ROOT / "public" / "data" / "swiss-floor.json"
ROOM_NUMBER = re.compile(r"-?\d+\.\d+")
AREA_LABEL = re.compile(r"(\d+(?:[.,]\d+)?)\s*m(?:²|2|\^2)", re.I)
APARTMENT = re.compile(r"^(?:app\.|apt\.|whg\.|wohnung\b|appartamento\b|appartement\b)", re.I)
METRES_PER_UNIT = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
SOURCE_CREDIT = "Swiss Dwellings v3.0.0, Archilyse AG and the credited authors. Drawing rendered for Stoa / Junction. CC BY 4.0."
SOURCE_URL = "https://doi.org/10.5281/zenodo.7788422"


def read_entities(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) % 2:
        raise ValueError("Incomplete DXF group code/value pair")
    pairs = [(int(code), value.strip()) for code, value in zip(lines[::2], lines[1::2])]
    try:
        unit_code = int(pairs[pairs.index((9, "$INSUNITS")) + 1][1])
        scale = METRES_PER_UNIT[unit_code]
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError("A supported explicit DXF insertion unit is required") from exc
    start = pairs.index((2, "ENTITIES")) + 1
    end = pairs.index((0, "ENDSEC"), start)
    entities = []
    for code, value in pairs[start:end]:
        if code == 0:
            entity = defaultdict(list)
            entities.append(entity)
        entity[code].append(value)
    return scale, entities


def polygon_area(points):
    return abs(math.fsum(x * b - a * y for (x, y), (a, b) in edges(points))) / 2


def edges(points):
    return zip(points, points[1:] + points[:1])


def contains(points, xy):
    x, y = xy
    return sum(
        1 for (x1, y1), (x2, y2) in edges(points)
        if (y1 > y) != (y2 > y) and x < x1 + (x2 - x1) * (y - y1) / (y2 - y1)
    ) % 2 == 1


def xy_points(entity, scale):
    return [[float(x) * scale, float(y) * scale] for x, y in zip(entity[10], entity[20], strict=True)]


def make_room(entity, points):
    return {
        "id": "outline-" + entity[5][0], "label": "", "area": polygon_area(points),
        "printedArea": None, "polygon": points, "handle": entity[5][0],
        "center": [sum(v[i] for v in points) / len(points) for i in (0, 1)],
        "numbered": False, "labelled": False, "annotations": [],
    }


def extract_rooms(path):
    scale, entities = read_entities(path)
    rooms, walls, details, labels, notes = [], [], [], [], []
    for entity in entities:
        kind, layer = entity[0][0], entity[8][0] if entity[8] else ""
        if kind == "TEXT" and layer in ("ROOM_TEXT", "ANNOTATION"):
            value = entity[1][0]
            if layer == "ANNOTATION":
                notes.append(value)
            else:
                labels.append((value, xy_points(entity, scale)[0]))
            continue
        if kind != "LWPOLYLINE" or layer not in ("ROOM_OUTLINE", "WALL"):
            continue
        if any(float(bulge) != 0 for bulge in entity[42]):
            raise ValueError(f"Curved polyline {entity[5][0]} needs an arc-aware extractor")
        points = xy_points(entity, scale)
        closed = bool(int((entity[70] or ["0"])[0]) & 1)
        if not closed or len(points) < 3 or polygon_area(points) == 0:
            details.append(points)
        elif layer == "WALL":
            walls.append(points)
        else:
            rooms.append(make_room(entity, points))
    if not rooms:
        raise ValueError("No measurable ROOM_OUTLINE polygons found")
    unassigned = []
    for label, xy in labels:
        candidates = [room for room in rooms if contains(room["polygon"], xy)]
        if not candidates:
            unassigned.append({"text": label, "xy": xy})
            continue
        room = min(candidates, key=lambda r: r["area"])
        room["annotations"].append({"text": label, "xy": xy})
        area_text = AREA_LABEL.fullmatch(label)
        if area_text:
            room["printedArea"] = float(area_text[1].replace(",", "."))
        elif ROOM_NUMBER.fullmatch(label):
            room.update(id=label, numbered=True, center=xy)
        elif not APARTMENT.match(label):
            room.update(label=label, labelled=True)
            if not room["numbered"]:
                room["center"] = xy
    if len({room["id"] for room in rooms}) != len(rooms):
        raise ValueError("Duplicate room IDs on this floor")
    points = [point for poly in walls + [r["polygon"] for r in rooms] for point in poly]
    name = path.stem
    project = notes[1] if len(notes) > 1 else ""
    file_base = "/data/swiss/" + name
    return {
        "sheet": {
            "id": name, "title": notes[0] if notes else name, "project": project,
            "units": "m", "areaUnit": "m²", "yAxis": "up",
            "sourceUrl": SOURCE_URL, "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
            "credit": SOURCE_CREDIT, "creditUrl": "/data/SWISS-SOURCE.md",
            "dxfUrl": file_base + ".dxf", "pdfUrl": file_base + ".pdf",
            "notes": notes,
        },
        "bounds": [min(p[0] for p in points), min(p[1] for p in points),
                   max(p[0] for p in points), max(p[1] for p in points)],
        "walls": walls, "rooms": rooms, "detailLines": details, "unassignedLabels": unassigned,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dxf", type=Path, nargs="?", default=DEFAULT_DXF)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()
    result = extract_rooms(args.dxf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(f"{args.output}: {len(result['rooms'])} room polygons, {len(result['walls'])} wall outlines")


if __name__ == "__main__":
    main()
