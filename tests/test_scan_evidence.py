import hashlib
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from scripts.score_scan_evidence import match_count, reference_boxes, run


class GroundingScore(unittest.TestCase):
    def test_transformed_fixture_and_opening_use_scaled_raster_dimensions(self):
        svg = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 100">
        <g transform="matrix(1,0,0,1,50,10)"><g class="FixedFurniture Sink"
        transform="matrix(2,0,0,1,0,5)"><g class="BoundaryPolygon"><rect width="10" height="4"/>
        </g><desc>Width:10 Height:20 Depth:4</desc></g></g><g id="Door"><polygon
        points="0,10 40,10 40,14 0,14 "/></g></svg>"""
        self.assertEqual(reference_boxes(svg, (200,100), 'sinks'), [[250,150,350,190]])
        self.assertEqual(reference_boxes(svg, (200,100), 'doors'), [[0,100,200,140]])

    def test_two_neighboring_predictions_cannot_claim_the_same_opening(self):
        labels = [[0,0,20,10], [70,60,80,85]]
        proposals = [[0,0,20,10], [3,0,23,10]]
        self.assertEqual(match_count(proposals,labels), 1)
        self.assertEqual(match_count(proposals+[labels[1]], labels), 2)

    def test_transformed_rectangle_geometry_precedes_misleading_size_metadata(self):
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(3 4)">
        <g class="FixedFurniture Sink" transform="translate(12 8) scale(2 3)">
        <g class="BoundaryPolygon"><rect x="5" y="7" width="8" height="4"/></g>
        <desc>Width:82 Height:3 Depth:42</desc></g></g></svg>'''
        self.assertEqual(reference_boxes(svg, (1000,1000), 'sinks'), [[25,33,41,45]])

    def test_bezier_uses_curve_extrema_and_ignores_unrelated_decorations(self):
        import importlib.util
        if not importlib.util.find_spec('svgpathtools'):
            self.skipTest('Optional evaluation dependency svgpathtools==1.8.0')
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><g class="FixedFurniture Sink">
        <g class="BoundaryPolygon"><g transform="translate(30 40) rotate(90)">
        <path d="M0,0 C0,10 10,10 10,0 Z"/></g></g>
        <circle cx="200" cy="300" r="80"/><desc>Width:30 Depth:90</desc></g></svg>'''
        for actual, expected in zip(reference_boxes(svg, (1000,1000), 'sinks')[0], (22.5,40,30,50)):
            self.assertAlmostEqual(actual, expected)

    def test_reflected_elliptical_arc_extrema_remain_on_the_actual_arc(self):
        import importlib.util
        if not importlib.util.find_spec('svgpathtools'):
            self.skipTest('Optional evaluation dependency svgpathtools==1.8.0')
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><g class="FixedFurniture Toilet"
        transform="translate(30 40) scale(-2 3)"><g class="BoundaryPolygon">
        <path d="M10 0 A10 5 0 0 1 -10 0"/></g></g></svg>'''
        for actual, expected in zip(reference_boxes(svg, (1000,1000), 'toilet bowls')[0], (10,40,50,55)):
            self.assertAlmostEqual(actual, expected)

    def test_fallback_uses_visible_geometry_without_a_boundary_group(self):
        import math
        svg = b'''<svg xmlns="http://www.w3.org/2000/svg"><g class="FixedFurniture Toilet">
        <g transform="matrix(1 0 2 1 50 60)"><circle r="5"/></g>
        <g style="display:none"><rect width="1000" height="2000"/></g>
        <g class="Name"><text>TOILET</text></g></g></svg>'''
        for actual,expected in zip(reference_boxes(svg,(1000,1000),'toilet bowls')[0],
                                   (50-5*math.sqrt(5),55,50+5*math.sqrt(5),65)):
            self.assertAlmostEqual(actual,expected)

    def test_unhandled_shapes_and_metadata_only_footprints_fail(self):
        for inner in ('<g class="BoundaryPolygon"><use href="#a"/></g>', '<desc>Width:42 Depth:100</desc>'):
            svg = f'<svg xmlns="http://www.w3.org/2000/svg"><g class="FixedFurniture Sink">{inner}</g></svg>'
            with self.assertRaises(ValueError):
                reference_boxes(svg, (1000,1000), 'sinks')

    def test_providers_and_true_zeros_have_separate_denominators(self):
        image = b'fixture'
        digest = hashlib.sha256(image).hexdigest()
        path = 'data/cubicasa5k/colorful-1.png'
        cats = ['doors', 'sinks', 'windows']
        questions = [dict(path=path, image_sha256=digest, category=c, question=c, gold=int(c=='doors'))
                     for c in cats]
        def predictions(statuses):
            return {(path, c): dict(image_sha256=digest, status=status,
                        evidence=[{'box': [0,100,200,140]}] if c=='doors' and status=='answered' else [])
                    for c, status in zip(cats, statuses)}
        with TemporaryDirectory() as directory:
            archive = Path(directory)/'sources.zip'
            with ZipFile(archive,'w') as z:
                prefix = 'cubicasa5k/colorful/1/'
                z.writestr(prefix+'F1_original.png', image)
                z.writestr(prefix+'F1_scaled.png', bytes(16)+struct.pack('>II',200,100))
                z.writestr(prefix+'model.svg', '<svg xmlns="http://www.w3.org/2000/svg"><g id="Door">'
                          '<polygon points="0,10 40,10 40,14 0,14"/></g></svg>')
            audit = run(questions, archive, predictions(['unknown','answered','unavailable']),
                        predictions(['answered','answered','answered']))
        self.assertEqual(audit['by_reader']['after']['all']['fully_grounded'], 3)
        self.assertEqual(audit['common_service_available']['after']['all']['fully_grounded'], 2)
        self.assertEqual(audit['positive_common_service_available']['after']['fully_grounded'], 1)
        self.assertEqual(audit['positive_common_service_available']['before']['matched'], 0)
        self.assertTrue(all(row['reference_count_agrees_with_gold'] for row in audit['questions']))
