import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.extract_rooms import DEFAULT_DXF, DEFAULT_JSON, encloses_ring, extract_rooms


class SwissDrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.floor = extract_rooms(DEFAULT_DXF)

    def test_regeneration_matches_supplied_sheet(self):
        self.assertEqual(hashlib.sha256(DEFAULT_DXF.read_bytes()).hexdigest(),
                         "4070c5f19eb921bc08e2f5a23e957086f76abcca03fafbb8b62ca30c8a60b58d")
        self.assertEqual(self.floor, json.loads(DEFAULT_JSON.read_text(encoding="utf-8")))
        self.assertEqual(len(self.floor["rooms"]), 23)
        self.assertEqual(len(self.floor["walls"]), 18)
        self.assertEqual(len(self.floor["detailLines"]), 4)
        self.assertFalse(self.floor["unassignedLabels"])

    def test_total_uses_full_precision_geometry(self):
        rooms = [r for r in self.floor["rooms"] if r["label"] == "Stanza"]
        self.assertEqual(len(rooms), 9)
        self.assertAlmostEqual(math.fsum(r["printedArea"] for r in rooms), 124.49)
        self.assertEqual(round(math.fsum(r["area"] for r in rooms), 2), 124.50)
        room = next(r for r in rooms if r["id"] == "5.11")
        self.assertEqual(room["handle"], "9E")
        self.assertEqual(len(room["polygon"]), 4)
        self.assertAlmostEqual(room["area"], 13.61707, places=5)
        self.assertEqual(room["printedArea"], 13.62)

    def test_partial_annotations_remain_inspectable(self):
        rooms = self.floor["rooms"]
        self.assertEqual(sum(r["numbered"] for r in rooms), 21)
        self.assertEqual(sum(r["label"] == "Balcone" for r in rooms), 2)
        self.assertEqual(sum(r["label"] == "Corridoio" for r in rooms), 3)
        for room_id in ("5.06", "5.21"):
            record = next(r for r in rooms if r["id"] == room_id)
            self.assertFalse(record["labelled"])
            self.assertIsNone(record["printedArea"])
            self.assertGreater(record["area"], 0)


def extract_synthetic(rectangles, annotations):
    """Draw a metric ASCII DXF with explicitly ordered shell/interior rings."""
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 6), (0, "ENDSEC"),
             (0, "SECTION"), (2, "ENTITIES")]
    for handle, x0, y0, x1, y1, ccw in rectangles:
        points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if ccw:
            points.reverse()
        pairs.extend([(0, "LWPOLYLINE"), (5, handle), (8, "ROOM_OUTLINE"), (70, 1)])
        for x, y in points:
            pairs.extend([(10, x), (20, y)])
    for text, x, y in annotations:
        pairs.extend([(0, "TEXT"), (8, "ROOM_TEXT"), (1, text), (10, x), (20, y)])
    pairs.extend([(0, "ENDSEC"), (0, "EOF")])
    with TemporaryDirectory() as temp:
        path = Path(temp) / "example.dxf"
        path.write_text("".join(f"{code}\n{value}\n" for code, value in pairs))
        return extract_rooms(path)


class RoomIdentifierAndHoleTests(unittest.TestCase):
    def test_basement_and_negative_labels_remain_separate_room_identifiers(self):
        floor = extract_synthetic([("A", 0, 0, 4, 4, False), ("B", 5, 0, 9, 4, False)],
                                  [("U1.01", 1, 2), ("Küche", 1, 3),
                                   ("Bad", 6, 3), ("-1.01", 6, 2)])
        self.assertEqual([(r["id"], r["label"], r["numbered"]) for r in floor["rooms"]],
                         [("U1.01", "Küche", True), ("-1.01", "Bad", True)])

    def test_duplicate_identifiers_do_not_hide_other_rooms_or_point_to_a_guess(self):
        floor = extract_synthetic([("A", 0, 0, 4, 4, False), ("B", 5, 0, 9, 4, False),
                                   ("C", 10, 0, 14, 4, False), ("D", 15, 0, 19, 4, False)],
                                  [("0.01", 1, 2), ("0.01", 6, 2), ("0.02", 11, 2),
                                   ("0.03", 16, 2), ("0.04", 16, 3)])
        self.assertEqual([r["id"] for r in floor["rooms"]], ["outline-A", "outline-B", "0.02", "outline-D"])
        self.assertEqual(floor["rooms"][3]["ambiguousRoomIds"], ["0.03", "0.04"])
        self.assertEqual([r["numbered"] for r in floor["rooms"]], [False, False, True, False])

    def test_concave_room_does_not_capture_a_ring_crossing_a_recess(self):
        u_shape = [(0, 0), (8, 0), (8, 8), (5, 8), (5, 2), (3, 2), (3, 8), (0, 8)]
        self.assertFalse(encloses_ring(u_shape, [(1, 5), (7, 5), (7, 6), (1, 6)]))
        self.assertFalse(encloses_ring(u_shape, [(0, 1), (1, 1), (1, 1.5), (0, 1.5)]))

    def test_interior_ring_is_subtracted_once_and_lift_remains_separate(self):
        floor = extract_synthetic([("A", 0, 0, 10, 10, False), ("B", 2, 2, 8, 8, True),
                                   ("C", 3, 3, 7, 7, False), ("D", 15, 0, 20, 5, True)],
                                  [("4.15", 1, 1), ("Korridor", 1, 1.5), ("4.16", 4, 4),
                                   ("Lift", 4, 4.5), ("Void", 2.5, 2.5), ("4.17", 16, 1)])
        self.assertEqual([(r["id"], r["area"]) for r in floor["rooms"]],
                         [("4.15", 64), ("4.16", 16), ("4.17", 25)])
        self.assertEqual(floor["rooms"][0]["holeHandles"], ["B"])
        self.assertEqual(floor["unassignedLabels"], [{"text": "Void", "xy": [2.5, 2.5]}])


if __name__ == "__main__":
    unittest.main()
