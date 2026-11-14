import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import nemotron, scan_library, scan_reader, scan_rooms as reader

ARCHIVE = Path(os.getenv("PLANPROOF_ARCHIVE") or
               Path(__file__).resolve().parents[1] / ".local/evaluation/swiss-frontier/inputs/junction-dataset.zip")
BEDROOMS = "How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?"


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

    def test_studio_requires_one_designation_and_one_identified_living_room(self):
        title = row("1H+KK",150)
        living = row("OH/KK",240)
        result = decide([title,living,row("ET",340)],"bedroom")
        self.assertEqual((result["answer"],result["evidence"]),(0,[]))
        self.assertEqual([e["box"] for e in result["coverage_evidence"]],[title["box"],living["box"]])
        for words in ([title], [title,row("KK",240)], [row("2H+KK",150),living],
                      [title,living,row("YLÄKERTA",360)], [title,living,row("OH",440)]):
            self.assertIsNone(decide(words,"bedroom"))

    def test_numbered_bedrooms_with_missing_label_abstain(self):
        self.assertIsNone(decide([row("MH2",75),row("MH3",200),row("ET",500)],"bedroom"))
        self.assertEqual(decide([row("MH1",75),row("MH2",200),row("ET",500)],"bedroom")["answer"],2)

    def test_dining_and_kitchen_print_is_one_space(self):
        for caption in ("K+R","RUOKAILU JA KEITTIÖ","KÖK OCH MATSAL"):
            r = decide([row(caption,80),row("ET",500),row("MH",300)],"kitchen")
            self.assertEqual(r["answer"],1)
            self.assertEqual(r["evidence"][0]["label"],caption)
        self.assertIsNone(decide([row("RUOKAILU",80),row("ET",500),row("MH",300)],"kitchen"))

    def test_adjacent_bedroom_is_excluded_only_at_an_actual_sheet_cut(self):
        try:
            import io
            from PIL import Image,ImageDraw
        except ImportError:
            self.skipTest("Optional Pillow raster decoder")
        from scripts.scan_room_labels import enclosed_bedrooms
        image = Image.new("L",(1000,600),255)
        pen = ImageDraw.Draw(image)
        for y in (128,236):
            pen.line((0,y,340,y),fill=0,width=2)
        for x in (83,88,338):
            pen.line((x,128,x,236),fill=0,width=2)
        labels = [row("MH",50,350),row("MH",92,350)]
        labels[0]["box"] = [51,350,70,369]
        labels[1]["box"] = [95,350,113,369]
        def render():
            buf = io.BytesIO()
            image.save(buf,"PNG")
            return buf.getvalue()
        self.assertEqual(enclosed_bedrooms(render(),labels),labels[1:])
        pen.line((5,128,5,236),fill=0,width=2)
        self.assertEqual(enclosed_bedrooms(render(),labels),labels)

    def test_other_targets_and_scoped_questions_do_not_trigger_ocr(self):
        with patch.object(reader,"inventory",side_effect=AssertionError("unexpected OCR")):
            for q in ("How many toilet bowls (WC seats) are drawn on this floor plan?",
                      "How many kitchens on the third floor?","What is the area of the kitchen?"):
                self.assertIsNone(reader.predict(b"anything",q))
        self.assertIsNone(reader.predict(b"broken","Count the bedrooms"))

    def test_inventory_reports_the_reading_direction_it_used(self):
        self.assertEqual(reader.inventory(b"broken"), {})
        png = b"\x89PNG\r\n\x1a\n" + b"\0"*8 + (64).to_bytes(4,"big") + (48).to_bytes(4,"big") + b"\0"*8
        mirrored = [row("MH",100),row("KPH",300),row("OH",500),row("2H+KK",700),row("ET",850)]
        def vision(path, orientation, language="default"):
            return list(mirrored) if orientation == 2 else []
        with patch.object(reader,"_vision",side_effect=vision), patch.object(reader.sys,"platform","darwin"), \
                patch.object(reader.shutil,"which",return_value="/usr/bin/tool"), \
                patch.object(reader,"_tesseract",side_effect=AssertionError("a mirrored sheet skips Tesseract")):
            inv = reader.inventory.__wrapped__(png)
        self.assertEqual((inv["orientation"], len(inv["labels"]["bedroom"])), (2, 1))
        with patch.object(reader,"_vision",return_value=list(mirrored)), patch.object(reader.sys,"platform","darwin"), \
                patch.object(reader.shutil,"which",return_value="/usr/bin/tool"), \
                patch.object(reader,"_tesseract",return_value=[]):
            self.assertEqual(reader.inventory.__wrapped__(png)["orientation"], 1)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("osascript") and ARCHIVE.is_file(),
                         "needs macOS Vision and the sponsor archive")
    def test_studio_scan_1767_still_grounds_zero_bedrooms(self):
        name = "high_quality_architectural-1767.png"
        with ZipFile(ARCHIVE) as archive:
            member = "junction-dataset/data/cubicasa5k/" + name
            if member not in archive.NameToInfo:
                self.skipTest("the staged archive does not hold this drawing")
            data = archive.read(member)
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / name
            image.write_bytes(data)
            with patch.object(scan_reader.nemotron, "run", side_effect=AssertionError("hosted call")), \
                    patch.object(scan_reader.scan_layout, "predict", side_effect=AssertionError("label reader answers first")):
                report = scan_reader.run(image, BEDROOMS, "", nemotron.MODEL, None)
        self.assertEqual((report["status"], report["answer"], report["evidence"]), ("answered", 0, []))
        self.assertEqual((report["method"], report["origin"]), ("local_room_labels", "Local room labels"))
        designation, living = report["coverage_evidence"]
        self.assertEqual(designation["label"], "Apartment designation 1H+KT")
        self.assertEqual(reader.letters(living["label"]), "OH")
        path = "data/cubicasa5k/" + name
        saved = scan_library._safe_report(dict(report, path=path), path, report["image_sha256"], BEDROOMS, report["origin"])
        self.assertEqual((saved["answer"], len(saved["coverage_evidence"])), (0, 2))
        self.assertIn("one habitable room", saved["reason"])


if __name__ == "__main__":
    unittest.main()
