import hashlib
import importlib.util
import unittest
from unittest.mock import patch

from scripts import scan_objects, scan_openings


class ObjectReaderTests(unittest.TestCase):
    def test_scope_and_supply_of_optional_model(self):
        self.assertEqual(scan_objects.category('How many windows are shown on this floor plan?'), 1)
        self.assertEqual(scan_objects.category('How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan?'), 6)
        self.assertEqual(scan_objects.category('How many toilet bowls (WC seats) are drawn on this floor plan?'), 5)
        for question in ('How many separate WC rooms are there?', 'How many doors in the bedroom?',
                         'How many windows and doors are shown on this floor plan?', 'What is the area of a window?'):
            with self.subTest(question=question), patch.object(scan_objects, '_cached_inventory', side_effect=AssertionError):
                self.assertIsNone(scan_objects.predict(b'scan', question))
        with patch.dict('os.environ', {'PLANPROOF_OBJECT_WEIGHTS':'/missing-planproof-object-checkpoint'}):
            self.assertFalse(scan_objects.available())
            self.assertIsNone(scan_objects.predict(b'scan', 'Count doors'))

    def test_inventory_is_bound_to_exact_bytes_and_supports_zero(self):
        source = b'input drawing'
        evidence = [{'label':'Door', 'box':[200,100,280,130]}]
        record = {'image_sha256': hashlib.sha256(source).hexdigest(), 'classes':{1:[], 2:evidence}}
        self.assertIsNone(scan_objects.predict(b'another drawing', 'Count windows', record))
        self.assertEqual(scan_objects.predict(source, 'Count windows', record)['answer'], 0)
        pred = scan_objects.predict(source, 'Count doors', record)
        self.assertEqual((pred['answer'], pred['evidence']), (1, evidence))

    @unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('numpy','cv2')), 'optional scan object runtime')
    def test_components_and_coordinates_preserve_separate_fixture_instances(self):
        import numpy as np
        p = np.zeros((11, 80, 100), dtype=np.float32)
        p[0] = .2
        p[5, 8:24, 10:19] = .94
        p[5, 32:48, 30:39] = .95
        p[5, 2:4, 4:6] = .99
        p[2, 55:59, 50:80] = .64
        parts = scan_objects._extract(p)
        self.assertEqual([e['box'] for e in parts[5]], [[100,100,190,300],[300,400,390,600]])
        self.assertEqual(parts[2], [])

    @unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('numpy','cv2')), 'optional scan object runtime')
    def test_facing_endpoints_separate_two_windows_in_one_semantic_component(self):
        import numpy as np
        prob = np.zeros((2, 80, 100), dtype=np.uint8)
        prob[0, 27:34, 10:86] = 230
        ends = np.zeros((4, 80, 100), dtype=np.uint8)
        for x in (10, 50):
            ends[0, 30, x] = 220
        for x in (44, 85):
            ends[1, 30, x] = 220
        result = scan_openings.decode(prob, ends, [(10, 27, 86, 34)], [])
        self.assertEqual(sorted(result[1]), [(10, 27, 44, 34), (50, 27, 85, 34)])
        rotated = scan_openings.decode(prob.transpose(0, 2, 1), ends[[2, 3, 0, 1]].transpose(0, 2, 1), [], [])
        self.assertEqual(sorted(rotated[1]), [(27, 10, 34, 44), (27, 50, 34, 85)])
        self.assertEqual(result[2], [])

    @unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('numpy','cv2')), 'optional scan object runtime')
    def test_opening_requires_semantics_and_keeps_single_door_component(self):
        import numpy as np
        prob = np.zeros((2, 80, 100), dtype=np.uint8)
        ends = np.zeros((4, 80, 100), dtype=np.uint8)
        ends[0, 25, 10] = ends[1, 25, 55] = 220
        self.assertEqual(scan_openings.decode(prob, ends, [], []), {1: [], 2: []})
        prob[1, 22:29, 10:56] = 235
        existing = (10, 22, 55, 29)
        self.assertEqual(scan_openings.decode(prob, ends, [], [existing]), {1: [], 2: [existing]})
        self.assertEqual(scan_openings.decode(prob, ends, [], []), {1: [], 2: [existing]})

    def test_rotation_channel_order_matches_point_geometry(self):
        offsets = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        points = offsets
        for order in scan_openings.ENDPOINT_ORDER:
            self.assertEqual([offsets[index] for index in order], points)
            points = [(-x, y) for y, x in points]


if __name__ == '__main__':
    unittest.main()
