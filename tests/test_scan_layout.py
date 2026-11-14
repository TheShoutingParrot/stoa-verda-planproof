import hashlib
import importlib.util
import json
import unittest
from unittest.mock import patch

from scripts import nemotron, scan_layout, scan_library, scan_reader

RUNTIME = all(importlib.util.find_spec(m) for m in ('numpy', 'cv2', 'PIL'))
STOREYS = 'How many floors (storeys) does this floor plan show?'
QUESTIONS = {
    'kitchen': 'How many kitchens (including kitchenettes, open kitchens and utility kitchens) are on this floor plan?',
    'sauna': 'How many saunas are on this floor plan?',
    'wc': 'How many separate WC rooms (toilet rooms marked WC) are on this floor plan?',
    'washroom': 'How many bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH) are on this floor plan, not counting separate WC rooms?',
    'balcony': 'How many balconies (parveke, including glazed balconies) are on this floor plan?',
    'storeys': STOREYS,
}


def label(kind, text, box, region=0, cls=0, source='sheet'):
    return {'kind': kind, 'label': text, 'box': box, 'region': region, 'cls': cls, 'source': source}


def region(kind, share, box, labels=(), toilets=0, sinks=0, bench=0., panel=1):
    return {'kind': kind, 'share': share, 'box': box, 'panel': panel, 'score': .95, 'toilets': toilets,
            'sinks': sinks, 'bench': bench, 'tub': 0., 'labels': list(labels)}


def plan(regions=(), labels=(), panels=None, benches=(), toilets=0, **extra):
    record = {'size': [600, 400], 'panels': panels if panels is not None else [{'share': 1., 'box': [50, 60, 900, 940]}],
              'regions': list(regions), 'labels': list(labels),
              'symbols': {'bench': list(benches), 'tub': [], 'sink': [],
                          'toilet': [{'share': .002, 'box': [0, 0, 5, 5], 'region': 0, 'score': .9}] * toilets},
              'faint_bench': 0, 'titles': [], 'storeys': [], 'floor_markers': [], 'unclear_wc': 0,
              'explicit_no_sauna': 0, 'ink': [1, 1, 1, 1]}
    record.update(extra)
    return record


def checked(report, question):
    """Every answer must pass the count parser and the saved-report validation of the product."""
    digest = hashlib.sha256(b'drawing').hexdigest()
    raw = dict(report, question=question, image='scan.png', image_sha256=digest, path='data/cubicasa5k/scan.png')
    parsed = nemotron.parse_count(json.dumps(raw, allow_nan=False))
    safe = scan_library._safe_report(raw, 'data/cubicasa5k/scan.png', digest, question, 'Local room map')
    assert safe is not None and safe['answer'] == parsed['answer'] == report['answer']
    return safe


class LayoutRuleTests(unittest.TestCase):
    def test_one_body_of_rooms_is_one_storey_unless_captions_or_ink_disagree(self):
        one = scan_layout.answer(plan(), 'storeys')
        self.assertEqual((one['answer'], one['evidence'][0]['box']), (1, [50, 60, 900, 940]))
        checked(one, STOREYS)
        caption = {'level': '2', 'label': '2. krs', 'box': [100, 20, 180, 40]}
        self.assertIsNone(scan_layout.answer(plan(storeys=[caption]), 'storeys'))
        self.assertIsNone(scan_layout.answer(plan(floor_markers=['YLÄKERTA']), 'storeys'))
        self.assertIsNone(scan_layout.answer(plan(ink=[2, 2, 2, 2]), 'storeys'))
        self.assertIsNone(scan_layout.answer(plan(ink=[3, 3, 3, 2]), 'storeys'))
        self.assertEqual(scan_layout.answer(plan(ink=[2, 1, 3, 1]), 'storeys')['answer'], 1)
        self.assertEqual(scan_layout.answer(plan(ink=[0, 0, 0, 0]), 'storeys')['answer'], 1)
        self.assertIsNone(scan_layout.answer(plan(panels=[]), 'storeys'))

    def test_separate_bodies_count_storeys_and_an_ambiguous_body_declines(self):
        left, right = {'share': 1., 'box': [40, 100, 460, 900]}, {'share': .8, 'box': [520, 100, 960, 900]}
        two = scan_layout.answer(plan(panels=[left, right]), 'storeys')
        self.assertEqual((two['answer'], [e['box'] for e in two['evidence']]), (2, [left['box'], right['box']]))
        checked(two, STOREYS)
        shed = {'share': .15, 'box': [470, 20, 510, 80]}
        self.assertIsNone(scan_layout.answer(plan(panels=[left, right, shed]), 'storeys'))
        speck = {'share': .05, 'box': [470, 20, 480, 30]}
        self.assertEqual(scan_layout.answer(plan(panels=[left, right, speck]), 'storeys')['answer'], 2)
        captions = [{'level': str(n), 'label': '%d. krs' % n, 'box': [100*n, 20, 100*n+60, 40]} for n in (1, 2, 3)]
        self.assertIsNone(scan_layout.answer(plan(panels=[left, right], storeys=captions), 'storeys'))
        self.assertEqual(scan_layout.answer(plan(panels=[left, right], storeys=captions[:2]), 'storeys')['answer'], 2)

    def test_single_kitchen_region_and_signs_of_a_second_kitchen(self):
        kitchen = region(scan_layout.KITCHEN, .12, [100, 100, 300, 300])
        result = scan_layout.answer(plan([kitchen]), 'kitchen')
        self.assertEqual((result['answer'], result['evidence'][0]['box']), (1, [100, 100, 300, 300]))
        checked(result, QUESTIONS['kitchen'])
        self.assertIsNone(scan_layout.answer(plan([kitchen, region(scan_layout.KITCHEN, .05, [500, 100, 600, 200])]), 'kitchen'))
        self.assertIsNone(scan_layout.answer(plan([region(scan_layout.KITCHEN, .02, [100, 100, 150, 150])]), 'kitchen'))
        labels = [label('kitchen', 'K', [150, 150, 170, 170], 1, scan_layout.KITCHEN),
                  label('kitchen', 'APUK', [700, 150, 760, 170], 0, scan_layout.STORAGE)]
        self.assertIsNone(scan_layout.answer(plan([dict(kitchen, labels=[0])], labels), 'kitchen'))
        named = scan_layout.answer(plan([dict(kitchen, labels=[0])], labels[:1]), 'kitchen')
        self.assertEqual(named['evidence'][0]['label'], 'Kitchen area labelled K')
        titles = [{'label': '2H+K', 'box': [10, 10, 60, 30]}, {'label': '3H+K', 'box': [510, 10, 560, 30]}]
        self.assertIsNone(scan_layout.answer(plan([kitchen], titles=titles), 'kitchen'))

    def test_sauna_needs_a_bench_or_label_and_zero_needs_every_wet_room_identified(self):
        bath = region(scan_layout.BATH, .06, [400, 400, 520, 560], toilets=1, sinks=1)
        bench = {'share': .02, 'box': [530, 400, 600, 440], 'region': 2, 'score': .9}
        steam = region(scan_layout.BATH, .03, [525, 400, 610, 560], bench=.02)
        positive = scan_layout.answer(plan([bath, steam], benches=[bench], faint_bench=.03), 'sauna')
        self.assertEqual((positive['answer'], positive['evidence']), (1, [{'label': 'Sauna bench', 'box': [530, 400, 600, 440]}]))
        checked(positive, QUESTIONS['sauna'])
        # Bench pieces in one room count once; a second bench far away may be another sauna; specks are ignored.
        near, far = dict(bench, share=.006, box=[530, 450, 560, 520]), dict(bench, share=.006, box=[100, 100, 160, 130])
        self.assertEqual(scan_layout.answer(plan([bath, steam], benches=[bench, near]), 'sauna')['answer'], 1)
        self.assertIsNone(scan_layout.answer(plan([bath, steam], benches=[bench, far]), 'sauna'))
        self.assertEqual(scan_layout.answer(plan([bath, steam], benches=[bench, dict(far, share=.001)]), 'sauna')['answer'], 1)
        self.assertIsNone(scan_layout.answer(plan([bath, steam], benches=[dict(bench, share=.003)], faint_bench=.01), 'sauna'))
        zero = scan_layout.answer(plan([bath]), 'sauna')
        self.assertEqual((zero['answer'], zero['evidence']), (0, []))
        self.assertEqual([e['box'] for e in zero['coverage_evidence']], [[400, 400, 520, 560]])
        self.assertEqual(checked(zero, QUESTIONS['sauna'])['coverage_evidence'][0]['box'], [400, 400, 520, 560])
        # A wet room with no fixture and no name could be the sauna; faint bench traces or a title also forbid zero.
        unknown = region(scan_layout.BATH, .03, [525, 400, 610, 560])
        self.assertIsNone(scan_layout.answer(plan([bath, unknown]), 'sauna'))
        self.assertIsNone(scan_layout.answer(plan([bath], faint_bench=.001), 'sauna'))
        self.assertEqual(scan_layout.answer(plan([bath], faint_bench=.0001), 'sauna')['answer'], 0)
        self.assertIsNone(scan_layout.answer(plan([bath], titles=[{'label': '2H+K+S', 'box': [1, 1, 9, 9], 'sauna': 1}]), 'sauna'))
        self.assertIsNone(scan_layout.answer(plan([]), 'sauna'))
        # A sauna label read inside a wet room is a positive; one read elsewhere is not enough.
        inside = label('sauna', 'S', [550, 470, 570, 490], 2, scan_layout.BATH, 'zoom')
        named = scan_layout.answer(plan([bath, dict(unknown, labels=[0])], [inside]), 'sauna')
        self.assertEqual((named['answer'], named['evidence'][0]['box']), (1, [550, 470, 570, 490]))
        outside = label('sauna', 'S', [50, 50, 70, 70], 0, 0)
        self.assertIsNone(scan_layout.answer(plan([bath], [outside]), 'sauna'))

    def test_wc_rooms_follow_labels_in_wet_rooms_and_one_bathroom_means_none(self):
        bath = region(scan_layout.BATH, .07, [400, 400, 520, 560], toilets=1, sinks=1)
        small = region(scan_layout.BATH, .015, [100, 400, 160, 470], labels=[0], toilets=1)
        wc = label('wc', 'WC', [110, 410, 140, 430], 2, scan_layout.BATH, 'zoom')
        one = scan_layout.answer(plan([dict(bath, labels=[1]), small],
                                      [wc, label('washroom', 'KPH', [420, 420, 460, 440], 1, scan_layout.BATH)], toilets=2), 'wc')
        self.assertEqual((one['answer'], one['evidence'][0]['box']), (1, [110, 410, 140, 430]))
        checked(one, QUESTIONS['wc'])
        # A bathroom-sized wet room without a name is the bathroom, not a second WC.
        self.assertEqual(scan_layout.answer(plan([bath, small], [wc], toilets=2), 'wc')['answer'], 1)
        # A small unnamed second toilet room, an unclear reading or a label outside the wet rooms declines.
        tiny = region(scan_layout.BATH, .012, [700, 400, 750, 460], toilets=1)
        self.assertIsNone(scan_layout.answer(plan([bath, small, tiny], [wc], toilets=3), 'wc'))
        self.assertIsNone(scan_layout.answer(plan([dict(bath, labels=[1]), small], [wc], unclear_wc=1), 'wc'))
        self.assertIsNone(scan_layout.answer(plan([bath], [label('wc', 'WC', [10, 10, 40, 30], 0, 0)]), 'wc'))
        zero = scan_layout.answer(plan([bath], toilets=1), 'wc')
        self.assertEqual((zero['answer'], zero['evidence'], len(zero['coverage_evidence'])), (0, [], 1))
        checked(zero, QUESTIONS['wc'])
        self.assertIsNone(scan_layout.answer(plan([dict(small, labels=[])], toilets=1), 'wc'))
        self.assertIsNone(scan_layout.answer(plan([bath], toilets=2), 'wc'))
        self.assertIsNone(scan_layout.answer(plan([bath, dict(small, labels=[])], toilets=1), 'wc'))

    def test_bathrooms_follow_labels_or_the_single_sized_wet_room_of_a_labelled_plan(self):
        bath = region(scan_layout.BATH, .07, [400, 400, 520, 560], labels=[0], toilets=1, sinks=1)
        kph = label('washroom', 'KPH', [420, 420, 460, 440], 1, scan_layout.BATH, 'zoom')
        result = scan_layout.answer(plan([bath], [kph]), 'washroom')
        self.assertEqual((result['answer'], result['evidence'][0]['box']), (1, [420, 420, 460, 440]))
        checked(result, QUESTIONS['washroom'])
        other = region(scan_layout.BATH, .05, [600, 400, 700, 560], sinks=1)
        self.assertIsNone(scan_layout.answer(plan([bath, other], [kph]), 'washroom'))
        self.assertEqual(scan_layout.answer(plan([bath, dict(other, share=.015)], [kph]), 'washroom')['answer'], 1)
        self.assertIsNone(scan_layout.answer(plan([bath], [dict(kph, region=0, cls=0)]), 'washroom'))
        # Without a bathroom label the plan must carry printed room names and exactly one sized wet room.
        names = [label('bedroom', 'MH', [100, 100, 130, 120]), label('bedroom', 'MH', [200, 100, 230, 120]),
                 label('other', 'OH', [300, 100, 330, 120])]
        unnamed = dict(bath, labels=[])
        area = scan_layout.answer(plan([unnamed], names), 'washroom')
        self.assertEqual((area['answer'], area['evidence'][0]['box']), (1, [400, 400, 520, 560]))
        checked(area, QUESTIONS['washroom'])
        self.assertIsNone(scan_layout.answer(plan([unnamed], names[:2]), 'washroom'))
        self.assertIsNone(scan_layout.answer(plan([unnamed, other], names), 'washroom'))
        self.assertIsNone(scan_layout.answer(plan([dict(unnamed, toilets=0, sinks=0)], names), 'washroom'))

    def test_balconies_follow_labels_on_outdoor_areas_and_zero_needs_no_candidate_area(self):
        nothing = scan_layout.answer(plan([]), 'balcony')
        self.assertEqual((nothing['answer'], nothing['evidence']), (0, []))
        checked(nothing, QUESTIONS['balcony'])
        outdoor = region(scan_layout.OUTDOOR, .12, [50, 60, 200, 300], panel=0)
        self.assertIsNone(scan_layout.answer(plan([outdoor]), 'balcony'))
        terrace = label('other', 'TERASSI', [80, 100, 160, 120], 1, scan_layout.OUTDOOR)
        named = scan_layout.answer(plan([dict(outdoor, labels=[0])], [terrace]), 'balcony')
        self.assertEqual((named['answer'], named['coverage_evidence'][0]['box']), (0, [50, 60, 200, 300]))
        checked(named, QUESTIONS['balcony'])
        parveke = label('balcony', 'PARVEKE', [80, 100, 160, 120], 1, scan_layout.OUTDOOR)
        one = scan_layout.answer(plan([dict(outdoor, labels=[0])], [parveke]), 'balcony')
        self.assertEqual((one['answer'], one['evidence'][0]['box']), (1, [80, 100, 160, 120]))
        checked(one, QUESTIONS['balcony'])
        self.assertIsNone(scan_layout.answer(plan([outdoor], [dict(parveke, region=0, cls=0)]), 'balcony'))

    def test_bedrooms_need_a_label_in_every_bedroom_region(self):
        rooms = [region(scan_layout.BEDROOM, .15, [100, 100, 300, 300], labels=[0]),
                 region(scan_layout.BEDROOM, .12, [320, 100, 500, 300], labels=[1])]
        names = [label('bedroom', 'MH', [180, 180, 210, 200], 1, scan_layout.BEDROOM, 'zoom'),
                 label('bedroom', 'MH 2', [400, 180, 440, 200], 2, scan_layout.BEDROOM)]
        both = scan_layout.answer(plan(rooms, names), 'bedroom')
        self.assertEqual((both['answer'], [e['box'] for e in both['evidence']]), (2, [names[0]['box'], names[1]['box']]))
        checked(both, 'How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?')
        self.assertIsNone(scan_layout.answer(plan(rooms, names[:1]), 'bedroom'))
        self.assertIsNone(scan_layout.answer(plan(rooms, []), 'bedroom'))
        self.assertIsNone(scan_layout.answer(plan(rooms, [names[0], dict(names[1], region=0, cls=0)]), 'bedroom'))
        self.assertIsNone(scan_layout.answer(plan(rooms, [names[0], dict(names[1], label='MH 3')]), 'bedroom'))
        nook = region(scan_layout.BEDROOM, .02, [520, 100, 560, 160])
        self.assertEqual(scan_layout.answer(plan(rooms + [nook], names), 'bedroom')['answer'], 2)

    def test_second_look_is_read_once_per_room_kind_and_never_for_other_families(self):
        png = b'\x89PNG\r\n\x1a\n' + b'synthetic'
        layout = {'size': (300, 200), 'interior': 1000, 'panels': [], 'regions': [], 'symbols': {name: [] for name in scan_layout.SYMBOLS},
                  'faint_bench': 0}
        looks = []
        def look(data, described, orientation=1, kinds=()):
            looks.append((orientation, kinds))
            return []
        with patch.object(scan_layout, 'CACHE', scan_layout.OrderedDict()), \
                patch.object(scan_layout.scan_objects, 'available', return_value=True), \
                patch.object(scan_layout.scan_objects, '_load', return_value=('model', 'cpu')), \
                patch.object(scan_layout, '_infer', return_value=('rooms', 'icons')) as infer, \
                patch.object(scan_layout, 'describe', return_value=layout), \
                patch.object(scan_layout.scan_rooms, 'inventory', return_value={'labels': {}, 'orientation': 3}), \
                patch.object(scan_layout.scan_storeys, 'panel_views', return_value=[]), \
                patch.object(scan_layout, 'zoom_rows', side_effect=look):
            for name in ('storeys', 'kitchen', 'balcony', 'sauna', 'wc', 'washroom', 'bedroom', 'sauna', 'storeys'):
                self.assertEqual(scan_layout.plan(png, name)['regions'], [])
            self.assertIs(scan_layout.plan(png, 'wc'), scan_layout.plan(png, 'sauna'))
            self.assertIsNot(scan_layout.plan(png, 'wc'), scan_layout.plan(png, 'storeys'))
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(looks, [(3, (scan_layout.BATH,)), (3, (scan_layout.BEDROOM,))])

    def test_evidence_boxes_are_valid_and_never_the_whole_sheet(self):
        whole = scan_layout.answer(plan(panels=[{'share': 1., 'box': [0, 0, 1000, 1000]}]), 'storeys')
        self.assertEqual(whole['evidence'][0]['box'], [1, 1, 999, 999])
        checked(whole, STOREYS)
        self.assertEqual(scan_layout._mark('x', [5, 7, 5, 7])['box'], [5, 7, 6, 8])
        self.assertEqual(scan_layout._mark('x', [1000, 990, 1000, 1000])['box'], [999, 990, 1000, 1000])
        twin = {'share': 1., 'box': [10, 10, 500, 900]}
        self.assertIsNone(scan_layout.answer(plan(panels=[twin, dict(twin)]), 'storeys'))

    def test_unsupported_questions_and_inputs_never_load_the_model(self):
        with patch.object(scan_layout, 'plan', side_effect=AssertionError('unexpected inference')):
            for question in ('How many windows are shown on this floor plan?', 'How many kitchens on the third floor?',
                             'How many showers and bathtubs are drawn on this floor plan in total?',
                             'How many bedrooms are in the largest apartment?', None):
                self.assertIsNone(scan_layout.predict(b'\x89PNG\r\n\x1a\n', question))
        with patch.object(scan_layout.scan_objects, '_load', side_effect=AssertionError('unexpected model load')):
            self.assertIsNone(scan_layout.predict(b'not a png', STOREYS))
            with patch.object(scan_layout.scan_objects, 'available', return_value=False):
                self.assertIsNone(scan_layout.predict(b'\x89PNG\r\n\x1a\n', STOREYS))

    def test_reader_asks_the_room_map_only_after_the_label_and_panel_readers_decline(self):
        from pathlib import Path
        import tempfile
        local = {'status': 'answered', 'answer': 1, 'evidence': [{'label': 'KPH', 'box': [1, 2, 30, 40]}],
                 'method': 'local_room_labels', 'coordinate_system': scan_layout.COORDS}
        mapped = scan_layout.answer(plan([region(scan_layout.KITCHEN, .12, [100, 100, 300, 300])]), 'kitchen')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scan.png'
            path.write_bytes(b'synthetic image bytes')
            with patch.object(scan_reader.scan_rooms, 'predict', return_value=local), \
                    patch.object(scan_reader.scan_layout, 'predict', side_effect=AssertionError('answered already')):
                first = scan_reader.run(path, QUESTIONS['washroom'], '', 'unused', None)
            self.assertEqual((first['method'], first['origin']), ('local_room_labels', 'Local room labels'))
            with patch.object(scan_reader.scan_rooms, 'predict', return_value=None), \
                    patch.object(scan_reader.scan_layout, 'predict', return_value=mapped):
                second = scan_reader.run(path, QUESTIONS['kitchen'], '', 'unused', None)
            self.assertEqual((second['method'], second['origin'], second['answer']), (scan_layout.METHOD, 'Local room map', 1))
            raw = dict(second, path='data/cubicasa5k/scan.png')
            self.assertIsNotNone(scan_library._safe_report(raw, raw['path'], second['image_sha256'], QUESTIONS['kitchen'],
                                                           second['origin']))


@unittest.skipUnless(RUNTIME, 'optional scan object runtime')
class LayoutGeometryTests(unittest.TestCase):
    def planes(self, height=200, width=300):
        import numpy as np
        rooms = np.zeros((12, height, width), np.uint8)
        icons = np.zeros((11, height, width), np.uint8)
        rooms[0] = icons[0] = 255
        return rooms, icons

    @staticmethod
    def paint(plane, cls, box):
        x0, y0, x1, y1 = box
        plane[:, y0:y1, x0:x1] = 0
        plane[cls, y0:y1, x0:x1] = 255

    def two_panels(self):
        rooms, icons = self.planes()
        for left in (20, 160):
            self.paint(rooms, scan_layout.WALL, (left, 40, left+120, 160))
            self.paint(rooms, scan_layout.LIVING, (left+4, 44, left+116, 156))
        self.paint(rooms, scan_layout.KITCHEN, (24, 44, 70, 90))
        self.paint(rooms, scan_layout.BATH, (164, 44, 204, 84))
        self.paint(rooms, scan_layout.WALL, (204, 44, 207, 84))
        self.paint(rooms, scan_layout.BATH, (207, 44, 247, 84))
        self.paint(rooms, scan_layout.OUTDOOR, (140, 60, 160, 100))
        self.paint(icons, scan_layout.TOILET, (168, 48, 178, 62))
        self.paint(icons, scan_layout.BENCH, (212, 48, 244, 60))
        return rooms, icons

    def test_panels_regions_and_symbols_are_read_from_the_class_planes(self):
        layout = scan_layout.describe(*self.two_panels())
        self.assertEqual([p['box'] for p in layout['panels']], [(20, 40, 140, 160), (160, 40, 280, 160)])
        kinds = [r['kind'] for r in layout['regions']]
        self.assertEqual(kinds.count(scan_layout.BATH), 2)
        self.assertEqual(kinds.count(scan_layout.KITCHEN), 1)
        self.assertEqual(kinds.count(scan_layout.OUTDOOR), 1)
        toilet, bench = layout['symbols']['toilet'][0], layout['symbols']['bench'][0]
        self.assertEqual(layout['regions'][toilet['region']-1]['box'], (164, 44, 204, 84))
        self.assertEqual(layout['regions'][bench['region']-1]['box'], (207, 44, 247, 84))
        self.assertEqual(layout['regions'][toilet['region']-1]['panel'], 2)

    def test_plan_joins_labels_to_regions_and_answers_in_source_coordinates(self):
        layout = scan_layout.describe(*self.two_panels())
        inv = {'labels': {'kitchen': [{'label': 'K', 'box': [100, 300, 180, 380]}], 'bedroom': [], 'washroom': [],
                          'wc': [], 'sauna': [], 'balcony': [], 'other': [{'label': 'OH', 'box': [200, 500, 260, 560]}]},
               'titles': [], 'storeys': [], 'floor_markers': [], 'possible_wc': [], 'explicit_no_sauna': []}
        zoomed = [{'text': 'WC', 'confidence': .9, 'box': [570, 250, 630, 300], 'engine': 'vision'},
                  {'text': 'WC', 'confidence': .8, 'box': [572, 252, 632, 302], 'engine': 'vision'},
                  {'text': 'WC', 'confidence': .2, 'box': [700, 250, 760, 300], 'engine': 'vision'}]
        box = [20, 100, 480, 900]
        record = scan_layout.build_plan(inv, layout, zoomed, [[box], [box], [box, box], [box, box]])
        self.assertEqual(json.loads(json.dumps(record)), record)
        self.assertEqual([p['box'] for p in record['panels']], [[67, 200, 467, 800], [533, 200, 933, 800]])
        named = {(item['kind'], item['source']): item for item in record['labels']}
        self.assertEqual(len(record['labels']), 3)
        self.assertEqual(record['regions'][named['kitchen', 'sheet']['region']-1]['kind'], scan_layout.KITCHEN)
        self.assertEqual(record['regions'][named['wc', 'zoom']['region']-1]['kind'], scan_layout.BATH)
        self.assertEqual(record['ink'], [1, 1, 2, 2])
        self.assertEqual(scan_layout.answer(record, 'storeys')['answer'], 2)
        self.assertEqual(scan_layout.answer(record, 'kitchen')['evidence'][0]['label'], 'Kitchen area labelled K')
        self.assertEqual(scan_layout.answer(record, 'sauna')['evidence'], [{'label': 'Sauna bench', 'box': [707, 240, 813, 300]}])
        self.assertEqual(scan_layout.answer(record, 'wc')['answer'], 1)
        self.assertIsNone(scan_layout.answer(record, 'balcony'))

    def test_enlarged_wet_rooms_map_back_to_the_source_image(self):
        from PIL import Image
        layout = scan_layout.describe(*self.two_panels())
        image = Image.new('RGB', (600, 400), 'white')
        sheet, tiles = scan_layout.zoom_tiles(image, layout)
        self.assertEqual(len(tiles), 2)
        self.assertEqual([(t['scale'], t['size']) for t in tiles], [(4., (416, 416))] * 2)
        self.assertEqual(sheet.size[1], sum(t['size'][1] for t in tiles) + 3*scan_layout.ZOOM_MARGIN)
        first = tiles[0]
        # A word in the middle of the first tile comes back to the middle of that wet room.
        cx, cy = scan_layout.ZOOM_MARGIN + first['size'][0]/2, first['top'] + first['size'][1]/2
        row = {'text': 'KPH', 'confidence': 1, 'box': [1000*(cx-20)/sheet.size[0], 1000*(cy-10)/sheet.size[1],
                                                       1000*(cx+20)/sheet.size[0], 1000*(cy+10)/sheet.size[1]]}
        margin = {'text': 'stray', 'confidence': 1, 'box': [10, 0, 60, 1000*4/sheet.size[1]]}
        restored = scan_layout.zoom_restore([row, margin], sheet.size, tiles, image.size)
        self.assertEqual(len(restored), 1)
        left, upper, right, lower = first['source']
        box = restored[0]['box']
        self.assertAlmostEqual((box[0]+box[2])/2, 1000*(left+right)/2/600, delta=1)
        self.assertAlmostEqual((box[1]+box[3])/2, 1000*(upper+lower)/2/400, delta=1)
        self.assertEqual(scan_layout.zoom_tiles(image, dict(layout, regions=[])), (None, []))


if __name__ == '__main__':
    unittest.main()
