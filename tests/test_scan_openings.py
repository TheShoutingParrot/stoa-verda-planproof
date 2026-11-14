import hashlib
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import scan_objects, scan_openings
from scripts.score_scan_evidence import match_count

RUNTIME = all(importlib.util.find_spec(m) for m in ('numpy', 'cv2'))
TORCH = RUNTIME and importlib.util.find_spec('torch') is not None
LOCAL = Path(__file__).resolve().parents[1] / '.local/evaluation'


def drawing(stem, digest):
    """Bytes of a development scan from the local staging folder or the sponsor ZIP, else None."""
    staged = LOCAL / 'scan-revision/inputs' / (stem + '.png')
    data = staged.read_bytes() if staged.is_file() else None
    archive = Path(os.environ.get('PLANPROOF_ARCHIVE') or LOCAL / 'swiss-frontier/inputs/junction-dataset.zip')
    if data is None and archive.is_file():
        with ZipFile(archive) as source:
            data = source.read('junction-dataset/data/cubicasa5k/' + stem + '.png')
    return data if data is not None and hashlib.sha256(data).hexdigest() == digest else None


class ScaleTests(unittest.TestCase):
    def test_door_length_needs_three_doors(self):
        self.assertIsNone(scan_openings.door_length([]))
        self.assertIsNone(scan_openings.door_length([30, 34]))
        self.assertEqual(scan_openings.door_length([30, 90, 34]), 34)
        self.assertEqual(scan_openings.door_length([30, 34], 2), 32)
        self.assertIsNone(scan_openings.door_length([30], 2))

    def test_drawing_keeps_its_pixels_inside_the_door_band(self):
        door = scan_openings.DOOR
        self.assertEqual(scan_openings.resize_factor(door), 1)
        self.assertEqual(scan_openings.resize_factor(1.5*door), 1)
        self.assertEqual(scan_openings.resize_factor(2*door), 1)
        self.assertAlmostEqual(scan_openings.resize_factor(door/2.6), 2.6)
        self.assertAlmostEqual(scan_openings.resize_factor(4*door), .5)

    def test_tiles_cover_the_sheet_with_overlap_and_a_bounded_count(self):
        tile, overlap = scan_objects.TILE, scan_objects.OVERLAP
        self.assertEqual(scan_objects._starts(tile), [0])
        self.assertEqual(scan_objects._starts(300), [0])
        for length in (tile+1, 2*tile-overlap, 2*tile-overlap+1, 5000):
            starts = scan_objects._starts(length)
            self.assertEqual((starts[0], starts[-1]+tile), (0, length))
            self.assertTrue(all(b-a <= tile-overlap for a, b in zip(starts, starts[1:])))
        count = lambda factor: (len(scan_objects._starts(round(3000*factor)))
                                * len(scan_objects._starts(round(2000*factor))))
        factor = scan_objects._fit(3000, 2000, 4.)
        self.assertLessEqual(count(factor), scan_objects.MAX_TILES)
        self.assertGreater(count(factor/.96), scan_objects.MAX_TILES)
        self.assertEqual(scan_objects._fit(600, 400, 1.5), 1.5)

    @unittest.skipUnless(TORCH, 'optional scan object runtime')
    def test_tiled_reading_blends_to_the_untiled_result(self):
        import torch

        def model(x):
            # Pointwise stand-in for the network: every output channel repeats the red plane.
            return x[:, :1].expand(-1, 44, -1, -1)

        torch.manual_seed(1)
        x = torch.rand(1, 3, 150, 230)
        with patch.object(scan_objects, 'TILE', 64), patch.object(scan_objects, 'OVERLAP', 8):
            for rotations in ((0,), (0, 1, 2, 3)):
                out = scan_objects._tiled(model, x, rotations)
                self.assertEqual(tuple(out.shape), (15, 150, 230))
                self.assertLess(float((out - x[0, :1]).abs().max()), 1e-5)
            small = scan_objects._tiled(model, x[:, :, :40, :50], (0,))
            self.assertLess(float((small - x[0, :1, :40, :50]).abs().max()), 1e-5)


class DecoderScaleTests(unittest.TestCase):
    @unittest.skipUnless(RUNTIME, 'optional scan object runtime')
    def test_unit_rescales_the_pixel_constants(self):
        import numpy as np
        prob = np.zeros((2, 80, 100), dtype=np.uint8)
        prob[0, 27:34, 10:86] = 230
        ends = np.zeros((4, 80, 100), dtype=np.uint8)
        for x in (10, 50):
            ends[0, 30, x] = 220
        for x in (44, 85):
            ends[1, 30, x] = 220
        base = sorted(scan_openings.decode(prob, ends, [], [])[1])
        self.assertEqual(base, [(10, 27, 44, 34), (50, 27, 85, 34)])
        big_prob = np.kron(prob, np.ones((2, 2), dtype=np.uint8))
        big_ends = np.zeros((4, 160, 200), dtype=np.uint8)
        big_ends[:, ::2, ::2] = ends
        doubled = sorted(scan_openings.decode(big_prob, big_ends, [], [], 2.)[1])
        self.assertEqual(len(doubled), 2)
        for small, large in zip(base, doubled):
            self.assertTrue(all(abs(2*a - b) <= 2 for a, b in zip(small, large)), (small, large))


    @unittest.skipUnless(RUNTIME, 'optional scan object runtime')
    def test_short_sash_joins_the_window_it_adjoins_once_the_drawing_is_sized(self):
        import numpy as np
        prob = np.zeros((2, 80, 100), dtype=np.uint8)
        prob[0, 27:34, 10:86] = 230
        ends = np.zeros((4, 80, 100), dtype=np.uint8)
        for x in (10, 26):
            ends[0, 30, x] = 220
        for x in (22, 85):
            ends[1, 30, x] = 220
        self.assertEqual(sorted(scan_openings.decode(prob, ends, [], [])[1]), [(10, 27, 22, 34), (26, 27, 85, 34)])
        self.assertEqual(scan_openings.decode(prob, ends, [], [], 1.)[1], [(10, 27, 85, 34)])
        # Two windows of ordinary length stay apart, and a short window standing alone stays.
        ends[0, 30, 26] = ends[1, 30, 22] = 0
        ends[0, 30, 50] = ends[1, 30, 44] = 220
        self.assertEqual(len(scan_openings.decode(prob, ends, [], [], 1.)[1]), 2)
        alone = np.zeros_like(prob)
        alone[0, 27:34, 10:23] = 230
        lone = np.zeros_like(ends)
        lone[0, 30, 10] = lone[1, 30, 22] = 220
        self.assertEqual(scan_openings.decode(alone, lone, [], [], 1.)[1], [(10, 27, 22, 34)])


class DrawingRegressionTests(unittest.TestCase):
    """Whole-reader checks on development scans. They need the detector assets and the local drawings."""

    # Window footprints of the original CubiCasa annotation, as 0-1000 boxes.
    CASES = {
        'high_quality_architectural-1767': (
            '7c4f922a07e659f4af6144b8727e916652d48402f36c9d649664a9b7de470629',
            [[425, 223, 733, 259], [854, 465, 959, 600]]),
        'high_quality-6058': (
            '59bb95ba3f13aabc388540edf60ecbeec68d691e34b26b0b795146b1af8454e8',
            [[107, 138, 259, 154], [358, 278, 477, 294], [297, 901, 449, 917], [30, 901, 53, 917],
             [607, 138, 764, 154], [863, 278, 984, 294], [593, 900, 632, 916], [705, 900, 741, 916],
             [800, 900, 951, 916]]),
    }

    def test_every_window_is_marked_once_on_known_drawings(self):
        if not scan_objects.available():
            self.skipTest('optional detector assets')
        for stem, (digest, windows) in self.CASES.items():
            with self.subTest(drawing=stem):
                data = drawing(stem, digest)
                if data is None:
                    self.skipTest('local development drawing')
                found = scan_objects.inventory(data)
                self.assertIsNotNone(found)
                marks = [mark['box'] for mark in found['classes'][1]]
                self.assertEqual(len(marks), len(windows))
                self.assertEqual(match_count(marks, windows), len(windows))


if __name__ == '__main__':
    unittest.main()
