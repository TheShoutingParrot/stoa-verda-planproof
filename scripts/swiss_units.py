"""Find apartment boundaries, their numbered indoor rooms and floor-wide contributors."""

from collections import defaultdict
import math
import re

if __package__:
    from .extract_rooms import APARTMENT, contains, edges, encloses_ring, signed_area, xy_points
else:
    from extract_rooms import APARTMENT, contains, edges, encloses_ring, signed_area, xy_points


OUTDOOR_OR_VOID = re.compile(
    r"balkon|balcon|loggia|terrass|terraz|garten|sitzplatz|jardin|giardino|patio|arkade|"
    r"atrium ouvert|lichthof|schacht|luft(?:raum|schacht)|vide|gaine|cavedio|"
    r"pozzo|vuoto|aussen|außen|extérieur|esterno", re.I)
BALCONY = re.compile(r'balkon|balcon|loggia', re.I)


def _unit_geometry(entities, scale):
    labels, rings = defaultdict(list), []
    for entity in entities:
        kind = entity[0][0]
        layer = (entity.get(8) or [None])[0]
        if layer == 'ROOM_TEXT' and kind == 'TEXT':
            value = entity[1][0]
            match = APARTMENT.match(value)
            if match:
                apt_id = value[match.end():].strip().upper()
                if re.fullmatch(r'[A-Z]+', apt_id):
                    labels[apt_id].append(xy_points(entity, scale)[0])
        elif layer == 'UNIT_OUTLINE' and kind == 'LWPOLYLINE':
            points = xy_points(entity, scale)
            closed = len(points) >= 3 and (int((entity.get(70) or ['0'])[0]) & 1 or points[0] == points[-1])
            if not closed or any(float(k) != 0 for k in entity.get(42, [])):
                continue
            if points[0] == points[-1]:
                points.pop()
            area = signed_area(points)
            if area:
                rings.append(dict(polygon=points, winding=area, handle=entity[5][0], holes=[]))
    shells = [ring for ring in rings if ring['winding'] < 0]
    for ring in rings:
        if ring['winding'] <= 0:
            continue
        parents = [s for s in shells if abs(s['winding']) > ring['winding'] and encloses_ring(s['polygon'], ring['polygon'])]
        if parents:
            min(parents, key=lambda s: abs(s['winding']))['holes'].append(ring['polygon'])
    return labels, shells


def _owns(ring, point):
    return contains(ring['polygon'], point) and not any(contains(hole, point) for hole in ring['holes'])


def _rectangular_dimensions(room):
    polygon = room['polygon']
    if len(polygon) != 4 or room.get('holes'):
        return None
    lengths = sorted(math.dist(a, b) for a, b in edges(polygon))
    short, long = (lengths[0] + lengths[1]) / 2, (lengths[2] + lengths[3]) / 2
    # Product of adjacent sides equals the area only for a rectangle.
    if not short or not math.isclose(room['area'], short * long, rel_tol=0.005):
        return None
    return short, long


def _exposed_edges(room, rooms):
    """Count edges facing clear space across a typical Swiss drawing wall."""
    polygon = room['polygon']
    sign = 1 if signed_area(polygon) < 0 else -1
    count = 0
    for a, b in edges(polygon):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        # Probe along the outward normal, beyond the wall, across the edge.
        # Three samples across each edge avoid counting an opening as a facade.
        distance = sign * .6 / length
        points = [(a[0] + dx * t - dy * distance, a[1] + dy * t + dx * distance)
                  for t in (.25, .5, .75)]
        if not any(contains(other['polygon'], point) for other in rooms if other is not room for point in points):
            count += 1
    return count


def _matching_balconies(rooms):
    """Transfer a printed balcony label only to a matching exposed rectangle on this sheet."""
    named = [(r, _rectangular_dimensions(r)) for r in rooms if r['label']]
    if not any(BALCONY.search(r['label']) and dims for r, dims in named):
        return {}
    matches = {}
    for room in rooms:
        if room['label'] or not room['numbered']:
            continue
        dims = _rectangular_dimensions(room)
        if not dims:
            continue
        peers = [r for r, other in named if other and all(abs(a-b) <= .05 for a, b in zip(dims, other))]
        if not peers or not all(BALCONY.search(r['label']) for r in peers):
            continue
        exposed = _exposed_edges(room, rooms)
        if exposed >= 2:
            ids = [r['id'] for r in peers if _exposed_edges(r, rooms) == exposed]
            if ids:
                matches[room['id']] = ids
    return matches


def _guard_hatches(entities, scale):
    """Gray solid WALL hatches form balcony/loggia guards in this DXF export."""
    hatches = []
    for entity in entities:
        if not (entity[0] == ['HATCH'] and entity.get(8) == ['WALL'] and entity.get(62) == ['8']
                and entity.get(2) == ['SOLID'] and entity.get(91) == ['1'] and entity.get(92) == ['3']
                and entity.get(73) == ['1'] and not any(float(b) for b in entity.get(42, []))):
            continue
        # The first 10/20 pair stores the HATCH elevation; the boundary follows.
        points = xy_points(entity, scale)[1:]
        if len(points) == int(entity[93][0]) and len(points) >= 3:
            hatches.append((entity[5][0], points))
    return hatches


def _guard_handles(room, rooms, hatches):
    """Find an actual guard running along an edge with exterior space beyond it."""
    polygon = room['polygon']
    orientation = 1 if signed_area(polygon) < 0 else -1
    found = set()
    for a, b in edges(polygon):
        length = math.dist(a, b)
        if length < .6:
            continue
        dx, dy = b[0] - a[0], b[1] - a[1]
        nx, ny = -dy * orientation / length, dx * orientation / length
        hits = defaultdict(int)
        for t in (.2, .4, .6, .8):
            x, y = a[0] + t * dx, a[1] + t * dy
            if any(contains(r['polygon'], (x + nx * .6, y + ny * .6)) for r in rooms
                   if r is not room and (r['numbered'] or r['label'])):
                continue
            for handle, patch in hatches:
                if any(contains(patch, (x + nx * gap, y + ny * gap)) for gap in (.007, .03, .07)):
                    hits[handle] += 1
        found.update(handle for handle, samples in hits.items() if samples >= 3)
    return sorted(found)


def _unlabelled_guards(entities, scale, rooms):
    unlabelled = [r for r in rooms if r['numbered'] and not r['label']]
    if not unlabelled:
        return {}
    hatches = _guard_hatches(entities, scale)
    if not hatches:
        return {}
    fixtures = []
    for entity in entities:
        if entity.get(8) == ['FIXTURE'] and entity[0][0] in ('CIRCLE', 'LWPOLYLINE'):
            points = xy_points(entity, scale)
            fixtures.append(tuple(sum(coords) / len(coords) for coords in zip(*points)))
    guards = {}
    for room in unlabelled:
        if any(contains(room['polygon'], p) for p in fixtures):
            continue
        handles = _guard_handles(room, rooms, hatches)
        if handles:
            guards[room['id']] = handles
    return guards


def _door_connections(entities, scale, rings):
    """Identify unit outline components directly connected by a CAD door threshold."""
    links = defaultdict(set)
    for entity in entities:
        if entity[0] != ['LWPOLYLINE'] or entity.get(8) != ['DOOR']:
            continue
        points = xy_points(entity, scale)
        if len(points) != 5 or points[0] != points[-1] or not signed_area(points):
            continue
        # Four-sided thresholds span the wall between two rooms. Step across
        # each opposite pair of edges, halfway along the clear door opening.
        center = tuple(sum(coords) / 4 for coords in zip(*points[:4]))
        sides = []
        for a, b in edges(points[:4]):
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            vx, vy = mx - center[0], my - center[1]
            radius = math.hypot(vx, vy)
            probe = (mx + .10 * vx / radius, my + .10 * vy / radius) if radius else center
            sides.append([r['handle'] for r in rings if _owns(r, probe)])
        for first, second in zip(sides[:2], sides[2:]):
            if len(first) == len(second) == 1 and first != second:
                links[first[0]].add(second[0])
                links[second[0]].add(first[0])
    return links


def extract_units(entities, scale, rooms):
    """Use DXF label positions and unit outlines; never sum floor or unit envelope area."""
    labels, rings = _unit_geometry(entities, scale)
    matched_balconies = _matching_balconies(rooms)
    guards = _unlabelled_guards(entities, scale, rooms)
    # A shared gallery can have one exposed guard. Outside unit outlines,
    # require multiple distinct exterior guards before treating it as outdoor.
    guards = {r['id']: guards[r['id']] for r in rooms if r['id'] in guards
              and (len(guards[r['id']]) > 1 or any(_owns(ring, r['center']) for ring in rings))}
    indoor = [r for r in rooms if r['numbered'] and not OUTDOOR_OR_VOID.search(r['label'])
              and r['id'] not in matched_balconies and r['id'] not in guards]
    ambiguous = [r for r in rooms if r.get('ambiguousRoomIds') and not OUTDOOR_OR_VOID.search(r['label'])]
    candidates = {identifier: [ring for ring in rings if len(points) == 1 and _owns(ring, points[0])]
                  for identifier, points in labels.items()}
    assigned, used = {}, set()
    for identifier, hits in candidates.items():
        if len(hits) == 1 and sum(hits[0] in other for other in candidates.values()) == 1:
            assigned[identifier] = hits[0]
            used.add(hits[0]['handle'])
    # The renderer can place a unit caption beside the footprint. If every other
    # residential footprint has an ID, there is one remaining valid assignment.
    missing = [name for name in labels if name not in assigned]
    unused = [ring for ring in rings if ring['handle'] not in used and any(_owns(ring, r['center']) for r in indoor)]
    if len(missing) == len(unused) == 1 and len(labels[missing[0]]) == 1 and not candidates[missing[0]]:
        assigned[missing[0]] = unused[0]
    used = {r['handle'] for r in assigned.values()}
    extras = defaultdict(list)
    detached = [ring for ring in rings if ring['handle'] not in used and any(_owns(ring, r['center']) for r in indoor)]
    if detached:
        links = _door_connections(entities, scale, rings)
        for ring in detached:
            owners = [identifier for identifier, primary in assigned.items()
                      if primary['handle'] in links[ring['handle']]]
            if len(owners) == 1:
                extras[owners[0]].append(ring)
    apartments = []
    for identifier, points in labels.items():
        ring = assigned.get(identifier)
        components = ([ring] if ring else []) + extras[identifier]
        rooms_here = [r['id'] for r in indoor if any(_owns(part, r['center']) for part in components)]
        apartments.append({'id': identifier, 'labelPoint': points[0], 'handle': ring['handle'] if ring else None,
                           'polygon': ring['polygon'] if ring else [], 'holes': ring['holes'] if ring else [],
                           'roomIds': rooms_here, 'complete': bool(ring and rooms_here)
                           and not any(_owns(part, r['center']) for r in ambiguous for part in components)})
        if extras[identifier]:
            apartments[-1]['additionalFootprints'] = [{k: v for k, v in part.items() if k != 'winding'}
                                                       for part in extras[identifier]]
    result = {'apartments': apartments, 'indoorRoomIds': [r['id'] for r in indoor],
              'floorComplete': bool(indoor) and not ambiguous}
    if matched_balconies:
        result['balconyMatches'] = matched_balconies
    if guards:
        result['outdoorGuardHandles'] = guards
    return result
