import hashlib
import json
import math
import unittest

from scripts.extract_rooms import DEFAULT_DXF, DEFAULT_JSON, extract_rooms


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


if __name__ == "__main__":
    unittest.main()
