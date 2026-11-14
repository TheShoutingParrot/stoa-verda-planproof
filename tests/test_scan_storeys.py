import unittest
from unittest.mock import patch
from scripts import scan_reader, scan_storeys


def word(text, box, confidence=.95):
    return {"text":text,"box":box,"confidence":confidence}


class StoreyReaderTests(unittest.TestCase):
    def setUp(self):
        self.labels = {"bedroom":[{"box":[120,140,160,160]}],
                       "kitchen":[{"box":[220,340,260,360]}], "other":[{"box":[420,240,460,260]}]}
        self.panel = [50,70,790,880]

    def test_single_plan_requires_sensible_extent_and_labels_in_all_views(self):
        inv = {"labels":self.labels,"storeys":[]}
        views = [[self.panel] for _ in range(4)]
        self.assertEqual(scan_storeys.read_panels(inv, views)[0]["box"], self.panel)
        for partial in ([[400,70,790,880]], [self.panel,[810,100,990,400]], []):
            self.assertIsNone(scan_storeys.read_panels(inv, views[:3]+[partial]))
        self.assertIsNone(scan_storeys.read_panels({"labels":{}, "storeys":[]}, views))

    def test_caption_deduplication_and_extra_panel(self):
        a = word("1. kerros", [100,850,210,900])
        b = word("2 KRS.", [680,850,760,900])
        rows = [a, b, word("1. KERROS", [101,851,212,903]), word("talo on 3 kerrosta", [240,810,440,840])]
        marks = scan_storeys.captions(rows)
        inv = {"labels":self.labels,"storeys":marks}
        left,right = [80,25,400,800],[620,25,980,800]
        self.assertEqual(len(scan_storeys.read_panels(inv, [[left,right]]*4)),2)
        self.assertIsNone(scan_storeys.read_panels(inv, [[left,right]]*2+[[left,right,[400,10,550,500]]]*2))
        self.assertIsNone(scan_storeys.read_panels(dict(inv,storeys=[marks[0]]), [[left,right]]*4))

    def test_normal_dispatch_and_scoped_questions(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"floor.png"
            path.write_bytes(b"synthetic image bytes")
            with patch("scripts.scan_rooms.inventory",return_value={"storeys":[],"labels":self.labels}), \
                    patch.object(scan_storeys,"panel_views",return_value=[[self.panel]]*4):
                result=scan_reader.run(path, "How many floors (storeys) does this floor plan show?", "", "unused", None)
                self.assertEqual((result["method"],result["answer"]),("local_storey_panels",1))
        self.assertIsNone(scan_storeys.predict(b"", "How many floors are in the whole building?"))
