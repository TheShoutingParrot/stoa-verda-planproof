import unittest
from unittest.mock import patch

from scripts import scan_rooms as reader


def row(text, x, y=200, confidence=1, engine="vision"):
    return {"text":text, "box":[x,y,x+50,y+20], "confidence":confidence, "engine":engine}


def decide(words, name):
    return reader.from_inventory(reader._summarize(words),name)


class ScanRoomTests(unittest.TestCase):
    def test_recognizes_swedish_and_visually_equivalent_finnish_glyphs(self):
        words = [row("SOVRUM",10),row("КРН",100),row("BASTU",200),row("BALKONG",300),row("KÖK",400)]
        for name in ("bedroom","washroom","sauna","balcony","kitchen"):
            with self.subTest(name=name):
                result = decide(words,name)
                self.assertEqual(result["answer"],1)
                self.assertEqual(len(result["evidence"]),1)

    def test_maps_flipped_coordinates_and_deduplicates_overlapping_words(self):
        self.assertEqual(reader._restore([40,90,200,190],2),[800,90,960,190])
        self.assertEqual(reader._restore([40,90,200,190],3),[800,810,960,910])
        self.assertEqual(reader._restore([40,90,200,190],4),[40,810,200,910])
        original = row("MH",100)
        copy = dict(original,engine="tesseract",confidence=.8)
        rooms = [original,copy,row("MH 2",400),row("ETEINEN",500)]
        self.assertEqual(decide(rooms,"bedroom")["answer"],2)

    def test_excludes_wc_in_combined_bathroom_and_appliance_names(self):
        words = [row("KPH/WC",10), row("WC",100),row("KHH",200),row("APK",300),row("PARVEKELASITUS",400),
                 row("MH",500),row("ET",600)]
        self.assertEqual(decide(words,"wc")["answer"],1)
        self.assertEqual(decide(words,"washroom")["answer"],1)
        self.assertIsNone(decide(words,"balcony"))
        self.assertIsNone(decide(words,"kitchen"))

    def test_explicit_unit_designation_is_not_a_second_kitchen_or_a_bedroom(self):
        words = [row("2H+KT+S",10), row("KT",110),row("VH",200),row("MH 1",300)]
        result = decide(words,"kitchen")
        self.assertEqual(result["answer"],1)
        self.assertEqual(result["evidence"][0]["label"],"KT")
        self.assertEqual(decide(words,"bedroom")["answer"],1)
        self.assertEqual(decide(words,"sauna")["evidence"][0]["label"],"Apartment designation 2H+KT+S")

    def test_only_explicit_absence_can_evidence_zero(self):
        words = [row("2H+KT",10),row("KK",100),row("KPH",200),row("MH",300),row("ET",400)]
        self.assertIsNone(decide(words,"sauna"))
        words.append(row("ASUNNOSSA EI OLE SAUNAA",500))
        r = decide(words,"sauna")
        self.assertEqual((r["answer"],r["evidence"]),(0,[]))
        self.assertEqual(r["coverage_evidence"],[{"label":"ASUNNOSSA EI OLE SAUNAA","box":[500,200,550,220]}])
        self.assertIsNone(decide([words[-1]],"sauna"))
        self.assertIsNone(decide(words+[row("YLÄKERTA",600)],"sauna"))

    def test_advertising_or_comparison_cannot_imply_a_count(self):
        words = [row("ET",10),row("MH",110),row("KPH",210)]
        for desc in ("MODEL APARTMENT NEXT DOOR: 2H+K+S", "SAUNA OPTION", "EI SAUNAA VIELÄ",
                     "THE OTHER APARTMENT HAS NO SAUNA", "SAUNAS: 0 IN THE ANNEX"):
            with self.subTest(desc=desc):
                self.assertIsNone(decide(words+[row(desc,400)],"sauna"))

    def test_ambiguous_kitchen_and_multiple_levels_abstain(self):
        words = [row("OH+KK",10),row("KK",200),row("PH",300),row("WC",400)]
        self.assertIsNone(decide(words,"kitchen"))
        self.assertIsNone(decide(words+[row("ALAKERTA",500),row("YLÄKERTA",600)],"wc"))
        self.assertIsNone(decide(words+[row("WG",500)],"wc"))

    def test_other_targets_and_scoped_questions_do_not_trigger_ocr(self):
        with patch.object(reader,"inventory",side_effect=AssertionError("unexpected OCR")):
            for q in ("How many toilet bowls (WC seats) are drawn on this floor plan?",
                      "How many kitchens on the third floor?","What is the area of the kitchen?"):
                self.assertIsNone(reader.predict(b"anything",q))
        self.assertIsNone(reader.predict(b"broken","Count the bedrooms"))


if __name__ == "__main__":
    unittest.main()
