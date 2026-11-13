import unittest

from scripts.swiss_units import extract_units


def rectangle(x, y, width, height):
    return [(x, y), (x, y + height), (x + width, y + height), (x + width, y)]


def polyline(handle, points, layer='UNIT_OUTLINE'):
    closed = list(points) + [points[0]]
    return {0: ['LWPOLYLINE'], 5: [handle], 8: [layer], 70: ['0'],
            10: [x for x, _ in closed], 20: [y for _, y in closed]}


def marker(name, x, y):
    return {0: ['TEXT'], 8: ['ROOM_TEXT'], 1: ['Whg. ' + name], 10: [x], 20: [y]}


def room(identifier, name, x, y, w, h):
    return {'id': identifier, 'label': name, 'numbered': True, 'area': w*h,
            'polygon': rectangle(x, y, w, h), 'center': [x + w/2, y + h/2]}


class SwissUnitsTests(unittest.TestCase):
    def test_floor_includes_shared_stairs_but_unit_excludes_hole_and_outdoor(self):
        entities = [marker('A', 1, 1), polyline('unit', rectangle(0, 0, 12, 8)),
                    polyline('hole', rectangle(4, 3, 3, 3)[::-1]),
                    polyline('detached', rectangle(15, 0, 2, 2))]
        rooms = [room('01', '', 1, 1, 1, 1), room('02', 'Garten', 8, 1, 2, 2),
                 room('03', 'Treppenhaus', 5, 4, 1, 1), room('04', 'Balcon', 15, 0, 2, 2)]
        result = extract_units(entities, 1, rooms)
        self.assertEqual(result['indoorRoomIds'], ['01', '03'])
        self.assertEqual(len(result['apartments']), 1)
        self.assertEqual(result['apartments'][0]['roomIds'], ['01'])
        self.assertTrue(result['apartments'][0]['complete'])

    def test_detached_room_connects_only_through_a_direct_cad_door(self):
        entities = [marker('A', 1, 1), polyline('main', rectangle(0, 0, 4, 4)),
                    polyline('connected', rectangle(4.4, 0, 4, 4)),
                    polyline('unrelated', rectangle(10, 0, 4, 4)),
                    polyline('door', rectangle(4, 1, .4, 1), 'DOOR')]
        rooms = [room('01', 'Zimmer', 1, 1, 2, 2), room('02', 'Zimmer', 5, 1, 2, 2),
                 room('03', 'Büro', 11, 1, 2, 2)]
        unit, = extract_units(entities, 1, rooms)['apartments']
        self.assertEqual(unit['roomIds'], ['01', '02'])
        self.assertEqual([p['handle'] for p in unit['additionalFootprints']], ['connected'])

    def test_gray_guard_excludes_inside_unit_only_and_fixtures_override_inference(self):
        def guard(handle, x, y=0, width=.1, height=2):
            points = [(0, 0)] + rectangle(x, y, width, height)
            return {0: ['HATCH'], 5: [handle], 8: ['WALL'], 2: ['SOLID'], 62: ['8'],
                    91: ['1'], 92: ['3'], 93: ['4'], 73: ['1'],
                    10: [px for px, _ in points], 20: [py for _, py in points]}
        rooms = [room('O', '', 0, 0, 2, 2), room('I', '', 4, 0, 2, 2),
                 room('S', '', 8, 0, 2, 2), room('K', 'Küche', 1, 3, 2, 1),
                 room('M', '', 12, 0, 2, 2)]
        entities = [marker('A', 1, 1), polyline('main', rectangle(-1, -1, 8, 6)),
                    guard('o', 2), guard('i', 6), guard('s', 10),
                    guard('m-east', 14), guard('m-north', 12, 2, 2, .1),
                    {0: ['CIRCLE'], 8: ['FIXTURE'], 10: [5], 20: [1]}]
        result = extract_units(entities, 1, rooms)
        self.assertEqual(result['outdoorGuardHandles'], {'O': ['o'], 'M': ['m-east', 'm-north']})
        self.assertEqual(result['indoorRoomIds'], ['I', 'S', 'K'])

    def test_duplicate_caption_prevents_unsupported_unit_area(self):
        entities = [marker('A', 1, 1), marker('A', 3, 1), polyline('main', rectangle(0, 0, 5, 4))]
        result = extract_units(entities, 1, [room('01', 'Pièce', 1, 1, 1, 1)])
        self.assertFalse(result['apartments'][0]['complete'])
        self.assertEqual(result['apartments'][0]['roomIds'], [])
        self.assertTrue(result['floorComplete'])


if __name__ == '__main__':
    unittest.main()
