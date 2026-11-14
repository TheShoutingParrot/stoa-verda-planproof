"""Recover individual window and door footprints from the CubiCasa model's output heads."""

from bisect import bisect_right
from dataclasses import dataclass, replace
import math
from statistics import median


# The upstream model predicts left, right, top and bottom threshold endpoints.
# torch.rot90 rotates the input counterclockwise. Undo the resulting orientation
# as well as undoing the spatial rotation of the output grid.
ENDPOINT_ORDER = ((0, 1, 2, 3), (3, 2, 0, 1), (1, 0, 3, 2), (2, 3, 1, 0))

# decode() measures in pixels of a grid on which a typical door threshold is this long:
# half the 78 px of CubiCasa's scale-normalised training drawings. `unit` rescales the
# pixel constants for a grid on which doors are `unit` times longer.
DOOR = 39.
# A window part shorter than this share of a door, touching another window on the
# same wall, is drawn as a sash of that window.
SASH = .5


@dataclass(frozen=True)
class Opening:
    box: tuple
    axis: int
    category: int
    score: float
    semantic: float
    competing: float
    peak: float

    @property
    def centerline(self):
        return (self.box[1-self.axis] + self.box[3-self.axis]) / 2

    @property
    def thickness(self):
        return self.box[3-self.axis] - self.box[1-self.axis]


def door_length(lengths, least=3):
    """Median door length, or None when too few doors make it unreliable."""
    return median(lengths) if len(lengths) >= least else None


def resize_factor(length):
    """Resize for a drawing whose doors are `length` pixels long.

    Doors measure DOOR to 2*DOOR pixels on the scales the detector handles best. A drawing
    inside that band keeps its own pixels. A smaller one is enlarged until its doors
    measure DOOR, and a larger one is reduced until they measure 2*DOOR.
    """
    return min(max(1., DOOR/length), 2*DOOR/length)


def _peaks(channel, unit=1.):
    import cv2
    import numpy as np
    size = max(3, round(9*unit) | 1)
    local = cv2.dilate(channel, np.ones((size, size), np.uint8))
    maxima = ((channel >= .16 * 255) & (channel == local)).astype(np.uint8)
    _, _, _, centers = cv2.connectedComponentsWithStats(maxima, connectivity=8)
    peaks = []
    for x, y in centers[1:]:
        x, y = round(x), round(y)
        peaks.append((x, y, channel[y, x] / 255.))
    return sorted(peaks, key=lambda point: -point[2])[:100]


def _candidate(start, end, axis, probabilities, unit=1.):
    import numpy as np
    x, y, left_confidence = start
    end_x, end_y, right_confidence = end
    length = end_x - x
    if (length < 7*unit or abs(end_y-y) > max(4*unit, min(12*unit, length*.13))
            or max(left_confidence, right_confidence) < .32):
        return None
    # Follow the opening along the wall. A class vote over its centerline can
    # connect interrupted glazing ink and distinguish a door from a window.
    height = probabilities.shape[1]
    half, core, reach = round(24*unit), max(1, round(2*unit)), round(6*unit)
    xs = np.arange(x+1, end_x)
    ys = np.linspace(y, end_y, len(xs)).round().astype(int)
    raster_y = np.clip(ys + np.arange(-half, half+1)[:, None], 0, height-1)
    band = probabilities[:, raster_y, xs]
    center = band[:, half-core:half+core+1]
    votes = center.mean(axis=(1, 2)) / 255.
    winner = int(votes.argmax())
    semantic, competing = votes[winner], votes[1-winner]
    if semantic < .12 or semantic < competing*1.05:
        return None

    # Estimate thickness perpendicular to the wall from the semantic profile.
    profile = band[winner].mean(axis=1) / 255.
    middle = half-reach + int(profile[half-reach:half+reach+1].argmax())
    interior = profile >= max(.055, profile[middle]*.45)
    lo = hi = middle
    while lo > 0 and interior[lo-1]:
        lo -= 1
    while hi+1 < len(interior) and interior[hi+1]:
        hi += 1
    box = (x, max(0, min(y, end_y)+min(-1, lo-half)),
           end_x, min(height, max(y, end_y)+max(1, hi-half)+1))
    if axis == 1:
        box = box[1], box[0], box[3], box[2]
    supported = (center[winner].mean(axis=0) > 51).mean()
    confidence = math.sqrt(left_confidence * right_confidence)
    confidence *= (.2+semantic)**.6 * (.65+.35*supported)
    if confidence <= .10:
        return None
    return Opening(box, axis, winner+1, (confidence-.10)**2, semantic, competing,
                   max(left_confidence, right_confidence))


def _nonoverlapping(wall, axis):
    # Weighted interval scheduling lets two well-supported adjoining openings
    # beat one long hypothesis spanning them. An endpoint can be used only once.
    ordered = sorted(wall, key=lambda item: item.box[axis+2])
    ends = [item.box[axis+2] for item in ordered]
    scores = [0.]
    previous = []
    for i, item in enumerate(ordered):
        j = bisect_right(ends, item.box[axis]-1, hi=i)
        combined = item.score + scores[j]
        previous.append(j if combined > scores[-1] else -1)
        scores.append(max(combined, scores[-1]))
    selected = []
    i = len(ordered)
    while i:
        j = previous[i-1]
        if j < 0:
            i -= 1
        else:
            selected.append(ordered[i-1])
            i = j
    return selected


def _joined(selected, unit):
    """Merge each short window part into the window it adjoins along the same wall."""
    items = list(selected)
    reach = 6*unit
    index = 0
    while index < len(items):
        item = items[index]
        axis = item.axis
        if item.category != 1 or item.box[axis+2]-item.box[axis] >= SASH*DOOR*unit:
            index += 1
            continue
        neighbours = [
            other for other in items
            if other is not item and other.category == 1 and other.axis == axis
            and abs(other.centerline-item.centerline) <= reach
            and -2*unit <= max(other.box[axis]-item.box[axis+2], item.box[axis]-other.box[axis+2]) <= reach]
        if not neighbours:
            index += 1
            continue
        other = max(neighbours, key=lambda candidate: candidate.score)
        box = (min(item.box[0], other.box[0]), min(item.box[1], other.box[1]),
               max(item.box[2], other.box[2]), max(item.box[3], other.box[3]))
        items[items.index(other)] = replace(other, box=box, peak=max(other.peak, item.peak))
        del items[index]
        index = 0
    return items


def _overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    area_a = (a[2]-a[0])*(a[3]-a[1])
    area_b = (b[2]-b[0])*(b[3]-b[1])
    return intersection > .38*min(area_a, area_b) or intersection > .19*(area_a+area_b-intersection)


def decode(probabilities, endpoints, semantic_windows, semantic_doors, unit=None):
    """Return model-grid XYXY boxes. Input planes are uint8 confidence in [0,255].

    `unit` says how long doors are on this grid, in multiples of DOOR. Leave it out when
    the drawing has not been sized: the pixel constants then apply as they are and no
    rule that depends on the size of a door is used.
    """
    sized, unit = unit is not None, unit or 1.
    selected = []
    for axis in (0, 1):
        p = probabilities if axis == 0 else probabilities.transpose(0, 2, 1)
        e = endpoints[:2] if axis == 0 else endpoints[2:].transpose(0, 2, 1)
        starts, ends = _peaks(e[0], unit), _peaks(e[1], unit)
        candidates = []
        for start in starts:
            for end in ends:
                item = _candidate(start, end, axis, p, unit)
                if item is not None:
                    candidates.append(item)
        wall = []
        for item in sorted(candidates, key=lambda candidate: candidate.centerline):
            tolerance = max(3*unit, min(8*unit, item.thickness*.55))
            if wall and item.centerline-median(other.centerline for other in wall) > tolerance:
                selected.extend(_nonoverlapping(wall, axis))
                wall = []
            wall.append(item)
        selected.extend(_nonoverlapping(wall, axis))
    if sized:
        selected = _joined(selected, unit)

    windows = []
    doors = list(semantic_doors)
    door_endpoints = []
    for item in sorted(selected, key=lambda item: -item.peak):
        if item.category == 1:
            if not any(_overlap(item.box, box) for box in windows):
                windows.append(item.box)
        else:
            door_endpoints.append(item.box)
            if (item.semantic >= .22 and item.semantic >= 2*item.competing and item.peak >= .42
                    and not any(_overlap(item.box, box) for box in doors)):
                doors.append(item.box)
    # Strong semantic components can capture diagonal openings or a truncated
    # end at the edge of the sheet where an endpoint pair is unavailable.
    for box in semantic_windows:
        if not any(_overlap(box, other) for other in windows+door_endpoints):
            windows.append(box)
    return {1: windows, 2: doors}
