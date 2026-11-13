import math
import unittest

from scripts.extract_rooms import DEFAULT_DXF, read_entities
from scripts.swiss_objects import extract_objects


def polyline(layer, handle, xy, closed=False):
    return {0: ["LWPOLYLINE"], 5: [handle], 8: [layer], 70: [str(int(closed))],
            10: [str(x) for x, y in xy], 20: [str(y) for x, y in xy]}


class SwissObjectTests(unittest.TestCase):
    def test_sponsor_sheet_and_evidence(self):
        scale, entities = read_entities(DEFAULT_DXF)
        objects = extract_objects(entities, scale)
        self.assertEqual({key: len(items) for key, items in objects.items()},
                         {"doors": 21, "windows": 13, "toilets": 3, "washbasins": 3,
                          "bathtubs": 2, "showers": 0})
        for kind, items in objects.items():
            with self.subTest(kind=kind):
                self.assertEqual(len({item["id"] for item in items}), len(items))
                for item in items:
                    self.assertEqual(item["lines"][0][0], item["lines"][0][-1])
                    self.assertTrue(all(math.isfinite(axis) for xy in item["lines"][0] for axis in xy))

    def test_counts_one_door_frame_even_with_multiple_leaves_and_swings(self):
        entities = [
            polyline("DOOR", "A", [[1000, 0], [2000, 0], [2000, 100], [1000, 100], [1000, 0]]),
            polyline("DOOR", "B", [[1000, 0], [1200, 200]]),
            polyline("DOOR", "C", [[2000, 0], [1800, 200]]),
            {0: ["ARC"], 5: ["D"], 8: ["DOOR"]}, {0: ["ARC"], 5: ["E"], 8: ["DOOR"]},
        ]
        doors = extract_objects(entities, 0.001)["doors"]
        self.assertEqual(len(doors), 1)
        self.assertEqual(doors[0]["center"], [1.5, 0.05])

    def test_basin_inside_counter_is_one_basin(self):
        counter = polyline("FIXTURE", "C", [[0, 0], [3, 0], [3, 0.6], [0, 0.6]], True)
        basin = polyline("FIXTURE", "B", [[0.2, 0.1], [0.8, 0.1], [0.8, 0.5], [0.2, 0.5]], True)
        oval = [[0.5 + 0.22 * math.cos(i * math.tau / 47),
                 0.3 + 0.14 * math.sin(i * math.tau / 47)] for i in range(48)]
        drain = {0: ["CIRCLE"], 5: ["D"], 8: ["FIXTURE"], 10: ["0.5"], 20: ["0.3"], 40: ["0.024"]}
        objects = extract_objects([counter, basin, polyline("FIXTURE", "O", oval), drain], 1)
        self.assertEqual([item["id"] for item in objects["washbasins"]], ["washbasins-B"])
        self.assertFalse(objects["bathtubs"])

    def test_narrow_tub_with_offset_drain_and_no_inner_curve(self):
        tub = polyline("FIXTURE", "T", [[0, 0], [0, 1.70], [0.15, 1.70], [0.15, 0]], True)
        drain = {0: ["CIRCLE"], 5: ["D"], 8: ["FIXTURE"], 10: ["0.075"], 20: ["1.5"], 40: ["0.025"]}
        objects = extract_objects([tub, drain], 1)
        self.assertEqual([item["id"] for item in objects["bathtubs"]], ["bathtubs-T"])

    def test_other_fixtures_with_crossed_lines_do_not_pass_as_showers(self):
        entities = [
            polyline("FIXTURE", "F", [[0, 0], [1, 0], [1, 1], [0, 1]], True),
            polyline("FIXTURE", "G", [[0, 0], [1, 1]]),
            polyline("FIXTURE", "H", [[0, 1], [1, 0]]),
        ]
        self.assertFalse(any(extract_objects(entities, 1).values()))


if __name__ == "__main__":
    unittest.main()
