from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import scan_library as scan
from scripts.drawing_library import DrawingError


class Library:
    path = 'data/cubicasa5k/fixture.png'
    content = b'fixture image'
    def metadata(self, path):
        if path != self.path:
            raise DrawingError(404, 'Not found')
        return {'kind': 'scan', 'fileUrl': '/fixture', 'name': 'fixture.png', 'path': path}

    def read_bytes(self, path):
        return self.content


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.lib = Library()
        self.path = self.lib.path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.checkpoint = root / 'predictions.sqlite'
        self.local = root / 'local'
        self.storage = root / 'interactive'
        env = patch.dict(os.environ, {
            'PLANPROOF_SCAN_CHECKPOINT': str(self.checkpoint), 'PLANPROOF_SCAN_LOCAL': str(self.local),
            'PLANPROOF_SCAN_RESULTS': str(self.storage), 'NEMOTRON_BASE_URL': '', 'NEMOTRON_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.q = 'How many doors?'
        self.raw = dict(path=self.path, image='fixture.png', question=self.q, status='answered',
                        answer=1, evidence=[dict(label='door 1', box=[10, 30, 16, 64])],
                        image_sha256=hashlib.sha256(self.lib.content).hexdigest(), coordinate_system=scan.COORDS,
                        model='test', gold=9001)

    def store(self, entries):
        with closing(sqlite3.connect(self.checkpoint)) as db, db:
            db.execute('CREATE TABLE results (path TEXT, question TEXT, report TEXT)')
            db.executemany('INSERT INTO results VALUES (?, ?, ?)',
                           [(self.path, q, json.dumps(raw)) for q, raw in entries])

    def test_replay_only_matching_image_question_coordinates_and_evidence(self):
        self.store([(self.q, self.raw), ('different', self.raw),
                    (self.q, dict(self.raw, path='other')), (self.q, dict(self.raw, image_sha256='stale')),
                    (self.q, dict(self.raw, coordinate_system='bottom')), (self.q, dict(self.raw, answer=9))])
        with patch.object(scan.nemotron, 'run', side_effect=AssertionError('No inference on replay')):
            info = scan.scan_info(self.lib, self.path)
            self.assertFalse(info['configured'])
            self.assertEqual(len(info['saved']), 1)
            report = scan.scan_answer(self.lib, self.path, self.q)
            self.assertTrue(report['reused'])
            self.assertEqual(report['answer'], 1)
            self.assertNotIn('gold', json.dumps(info))
            self.assertFalse(self.storage.exists())

    def test_local_gate_and_measured_zero_are_distinct(self):
        (self.local / 'gates').mkdir(parents=True)
        (self.local / 'gates/fixture.json').write_text(json.dumps(dict(self.raw, status='unknown', method='grayscale_invariant')))
        self.store([(self.q, dict(self.raw, status='answered', answer=0, evidence=[]))])
        reports = scan.scan_info(self.lib, self.path)['saved']
        self.assertEqual([r['answer'] for r in reports], [0, None])
        self.assertEqual(reports[1]['evidence'], [])

    def test_fresh_result_survives_restart_and_keeps_credentials_private(self):
        with patch.dict(os.environ, NEMOTRON_BASE_URL='https://example.test/v1', NEMOTRON_API_KEY='fixture-secret'):
            with patch.object(scan.nemotron, 'run', return_value=self.raw.copy()) as run:
                self.assertFalse(scan.scan_answer(self.lib, self.path, self.q)['reused'])
                replay = scan.scan_answer(self.lib, self.path, self.q)
                self.assertTrue(replay['reused'])
                self.assertEqual(run.call_count, 1)
            self.assertEqual(scan.scan_info(self.lib, self.path)['saved'][0]['origin'], 'Interactive inference')
        self.assertNotIn('fixture-secret', next(self.storage.rglob('*.json')).read_text())
        self.lib.content = b'changed file'
        self.assertEqual(scan.scan_info(self.lib, self.path)['saved'], [])

    def test_recheck_preserves_last_answer_and_replaces_it_on_success(self):
        self.store([(self.q, self.raw)])
        abstention = dict(self.raw, status='unknown', answer=None, evidence=[], reason='Unreadable')
        with patch.object(scan.scan_reader, 'run', return_value=abstention):
            fresh = scan.scan_answer(self.lib, self.path, self.q, refresh=True)
        self.assertEqual(fresh['status'], 'unknown')
        self.assertFalse(fresh['saved'])
        self.assertEqual(scan.scan_answer(self.lib, self.path, self.q)['answer'], 1)
        correction = dict(self.raw, answer=0, evidence=[], method='cubicasa_pixel_objects', origin='Local object detector')
        with patch.object(scan.scan_reader, 'run', return_value=correction):
            self.assertFalse(scan.scan_answer(self.lib, self.path, self.q, refresh=True)['reused'])
        replay = scan.scan_info(self.lib, self.path)['saved'][0]
        self.assertEqual((replay['answer'], replay['origin']), (0, 'Local object detector'))

    def test_bad_questions_offline_and_provider_errors(self):
        for question, expected in [(' ', 400), ('What area is the kitchen?', 422), ('How many square meters?', 422), (self.q, 503)]:
            with self.assertRaises(DrawingError) as ctx:
                scan.scan_answer(self.lib, self.path, question)
            self.assertEqual(ctx.exception.status, expected)
        with patch.dict(os.environ, NEMOTRON_BASE_URL='https://example.test', NEMOTRON_API_KEY='test'):
            with scan.RUN_LOCK, self.assertRaises(DrawingError) as ctx:
                scan.scan_answer(self.lib, self.path, self.q)
            self.assertEqual(ctx.exception.status, 409)
            with patch.object(scan.nemotron, 'run', return_value=dict(status='unavailable', reason='HTTP 429.')):
                with self.assertRaisesRegex(DrawingError, '429'):
                    scan.scan_answer(self.lib, self.path, self.q)
        self.assertFalse(self.storage.exists())
