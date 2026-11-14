"""Count depicted storeys from identifiable floor panels and their printed room labels."""
import io
import math
import re
import unicodedata


QUESTION = re.compile(
    r"how many (?:floors(?: \(storeys\))?|storeys|stories) (?:does this floor plan show|"
    r"are (?:shown|drawn) on this (?:floor plan|drawing|sheet))\??",
    re.IGNORECASE,
)
NAMED_LEVELS = {
    "ALAKERTA": "lower", "YLÄKERTA": "upper", "KESKIKERROS": "middle",
    "KELLARI": "basement", "KELLARIKERROS": "basement", "KELLARIKRS": "basement",
    "ULLAKKOKERROS": "attic", "KÄYTTÖULLAKKO": "attic",
    "POHJAKERROS": "ground", "ASUINKERROS": "living floor",
    "BASEMENT FLOOR": "basement", "GROUND FLOOR": "ground",
    "FIRST FLOOR": "1", "SECOND FLOOR": "2", "THIRD FLOOR": "3",
    "BOTTENVÅNING": "ground", "KÄLLARVÅNING": "basement", "ÖVERVÅNING": "upper",
}


def mark_level(text):
    text = unicodedata.normalize("NFKC", text).upper().strip(" .,;:–-")
    number = re.fullmatch(r"([1-9])\s*\.?\s*(?:KERROS|KRS)|(?:FLOOR|LEVEL|VÅNING)\s+([1-9])", text)
    if number:
        return number.group(1) or number.group(2)
    return NAMED_LEVELS.get(text.replace("YLAKERTA", "YLÄKERTA").replace("KAYTTOULLAKKO", "KÄYTTÖULLAKKO"))


def captions(rows):
    """Merge repeated OCR observations in source coordinates; preserve distinct panels."""
    marks = []
    for row in sorted(rows, key=lambda r: r.get("confidence", 0), reverse=True):
        level = mark_level(row["text"])
        if not level or row["confidence"] < .65:
            continue
        box = row["box"]
        if len(box) != 4 or not all(math.isfinite(x) for x in box) or box[2] <= box[0] or box[3] <= box[1]:
            continue
        center = ((box[0]+box[2])/2, (box[1]+box[3])/2)
        if any(math.dist(center, m["center"]) < 35 for m in marks):
            continue
        marks.append(dict(level=level, label=row["text"], box=box, center=center))
    return marks


def _panels(ink, dilation):
    """Find large, ink-dense connected drawing regions at one contrast and gap scale."""
    import cv2
    import numpy as np

    height, width = ink.shape
    expanded = cv2.dilate(ink, np.ones((dilation, dilation), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(expanded)
    regions = []
    for x, y, w, h, _ in stats[1:]:
        area = w * h / (width * height)
        if area < .035 or (w > .98*width and h > .98*height):
            continue
        if min(w/width, h/height) < .064 or min(w,h) < .12*max(w,h):
            continue
        if np.mean(ink[y:y+h, x:x+w]) <= .055:
            continue
        regions.append((area, [round(x*1000/width), round(y*1000/height),
                               round((x+w)*1000/width), round((y+h)*1000/height)]))
    largest = max((area for area, _ in regions), default=0.)
    return [box for area, box in regions if area >= .16*largest]


def panel_views(image_bytes):
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return []
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.format != "PNG" or image.width * image.height > 35_000_000:
            return []
        gray = np.array(image.convert("L"))
    height, width = gray.shape
    scale = min(1., 768 / max(width, height))
    gray = cv2.resize(gray, (max(1, round(width*scale)), max(1, round(height*scale))),
                      interpolation=cv2.INTER_AREA)
    return [_panels((gray < threshold).astype(np.uint8), dilation)
            for threshold in (110, 165) for dilation in (3, 7)]


def _contains(box, point):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def read_panels(inv, views):
    marks = inv.get("storeys", ())
    labels = []
    for kind, items in inv.get("labels", {}).items():
        for item in items:
            x0, y0, x1, y1 = item["box"]
            labels.append((kind, ((x0+x1)/2, (y0+y1)/2)))
    if len({level["level"] for level in marks}) != len(marks) or len(labels) < 3 or len(views) != 4:
        return None
    counts = [len(v) for v in views]
    if len(marks) >= 2:
        # A faint extra panel can lose its caption. Require more than one view to
        # corroborate the labels, and decline when both lighter-ink views suggest an extra floor.
        if counts.count(len(marks)) < 2 or all(n > len(marks) for n in counts[2:]):
            return None
        if any(math.dist(a["center"], b["center"]) < 120 for i,a in enumerate(marks) for b in marks[i+1:]):
            return None
        return [{"label":m["label"], "box":m["box"]} for m in marks]
    if counts != [1,1,1,1]:
        return None
    # One large floor drawing must contain all the room labels at every contrast.
    # A cropped neighbor, a second floor panel or an isolated legend can break agreement.
    if len({kind for kind, _ in labels}) < 2:
        return None
    if any(_area(v[0]) < 180_000 or any(not _contains(v[0], pt) for _, pt in labels) for v in views):
        return None
    return [{"label":"Floor plan with room labels", "box":views[2][0]}]


def predict(image_bytes, question):
    if not QUESTION.fullmatch(" ".join(question.strip().split())):
        return None
    from . import scan_rooms

    inv = scan_rooms.inventory(image_bytes)
    if not inv.get("labels"):
        return None
    try:
        views = panel_views(image_bytes)
    except (OSError, ValueError):
        return None
    marks = read_panels(inv, views)
    if not marks:
        return None
    return dict(status="answered", answer=len(marks), evidence=marks, method="local_storey_panels",
                coordinate_system="xyxy_top_left_0_to_1000")
