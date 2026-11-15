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

    def replay_fixture(self):
        replay = self.local.parent / 'replay.json'
        base = dict(self.raw, origin='Measured scan reader · reused hosted response', method='synthetic_reader')
        reports = [base, dict(base, question='How many saunas?', status='unknown', answer=None, evidence=[],
                              reason='Indistinct scan.'),
                   dict(base, question='How many windows?', status='unavailable', answer=None, evidence=[],
                        reason='Inference endpoint returned HTTP 429.')]
        replay.write_text(json.dumps(dict(version=1, reports=reports)))
        digest = hashlib.sha256(replay.read_bytes()).hexdigest()
        patcher = patch.multiple(scan, REPLAY_FILE=replay, REPLAY_SHA256=digest,
                                 REVISION_REPLAY_FILE=replay.with_name('missing-revision-bundle'))
        patcher.start()
        self.addCleanup(patcher.stop)
        return replay

    def test_sealed_results_are_bound_and_read_once_with_weak_results_retained(self):
        self.replay_fixture()
        with patch.object(scan.scan_reader, 'run', side_effect=AssertionError('unexpected inference')):
            previous = scan._replay_index.cache_info()
            info = scan.scan_info(self.lib, self.path)
            saved = {r['question']:r for r in info['saved']}
            self.assertEqual({k:v['status'] for k,v in saved.items()}, {
                self.q:'answered', 'How many saunas?':'unknown', 'How many windows?':'unavailable'})
            self.assertEqual(saved[self.q]['method'],'synthetic_reader')
            self.assertNotIn('gold',json.dumps(info))
            self.assertEqual(scan.scan_answer(self.lib,self.path,self.q)['evidence'],self.raw['evidence'])
            final = scan._replay_index.cache_info()
            self.assertEqual(final.misses,previous.misses+1)
            self.assertGreater(final.hits,previous.hits)
            self.lib.content = b'different bytes'
            self.assertEqual(scan.scan_info(self.lib,self.path)['saved'],[])

    def test_changed_or_missing_bundle_falls_back_then_recovers(self):
        replay = self.replay_fixture()
        original = replay.read_bytes()
        self.assertEqual(len(scan.scan_info(self.lib,self.path)['saved']),3)
        replay.write_bytes(original.replace(b'synthetic_reader',b'synthetic_broken'))
        self.assertEqual(scan.scan_info(self.lib,self.path)['saved'],[])
        replay.unlink()
        self.assertEqual(scan.scan_info(self.lib,self.path)['saved'],[])
        replay.write_bytes(original)
        self.assertEqual(len(scan.scan_info(self.lib,self.path)['saved']),3)

    def test_shipped_bundle_contains_only_ui_fields_and_distinct_drawing_questions(self):
        from scripts.export_scan_replay import UI_FIELDS
        data = scan.REPLAY_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),scan.REPLAY_SHA256)
        bundle = json.loads(data)
        self.assertEqual(set(bundle), {'version','reports'})
        self.assertEqual(len(bundle['reports']),96)
        self.assertEqual(len({r['path'] for r in bundle['reports']}),32)
        self.assertEqual(len({(r['path'],r['question']) for r in bundle['reports']}),96)
        for r in bundle['reports']:
            self.assertFalse(set(r) - set(UI_FIELDS))
            for item in r['evidence'] + r.get('coverage_evidence',[]):
                self.assertEqual(set(item),{'label','box'})
        self.assertTrue(all(f not in UI_FIELDS for f in
                            ('gold','correct','latency_ms','timestamp','usage','attempts','headers','api_key')))

    def test_revision_replay_contains_only_measured_counts_and_preserves_studio_evidence(self):
        from scripts.export_scan_replay import UI_FIELDS
        data = scan.REVISION_REPLAY_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), scan.REVISION_REPLAY_SHA256)
        reports = json.loads(data)['reports']
        self.assertEqual(len(reports),240)
        self.assertEqual(len({(r['path'],r['question']) for r in reports}),240)
        historical = json.loads(scan.REPLAY_FILE.read_bytes())['reports']
        self.assertTrue({r['path'] for r in historical}.isdisjoint(r['path'] for r in reports))
        for r in reports:
            self.assertFalse(set(r)-set(UI_FIELDS))
            self.assertEqual((r['status'],len(r['evidence'])),('answered',r['answer']))
            for item in r['evidence'] + r.get('coverage_evidence',[]):
                self.assertEqual(set(item),{'label','box'})
        rooms = [r for r in reports if r['method']=='local_room_labels' and r['answer']==0]
        self.assertEqual(len(rooms),1)
        self.assertEqual(len(rooms[0]['coverage_evidence']),2)

    def test_next_replay_holds_the_sealed_after_arm_with_zero_evidence(self):
        from scripts.export_scan_replay import UI_FIELDS
        data = scan.NEXT_REPLAY_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), scan.NEXT_REPLAY_SHA256)
        reports = json.loads(data)['reports']
        self.assertEqual(len(reports), 465)
        self.assertEqual(len({(r['path'], r['question']) for r in reports}), 465)
        earlier = json.loads(scan.REPLAY_FILE.read_bytes())['reports'] + json.loads(scan.REVISION_REPLAY_FILE.read_bytes())['reports']
        self.assertTrue({r['path'] for r in earlier}.isdisjoint(r['path'] for r in reports))
        for r in reports:
            self.assertFalse(set(r) - set(UI_FIELDS))
            self.assertEqual((r['status'], len(r['evidence'])), ('answered', r['answer']))
            for item in r['evidence'] + r.get('coverage_evidence', []):
                self.assertEqual(set(item), {'label', 'box'})
        zeros = [r for r in reports if r['answer'] == 0 and r['method'] == 'local_room_layout']
        self.assertTrue(zeros and all(r.get('coverage_evidence') and r.get('reason') for r in zeros))

    def test_distinct_portable_bundles_coexist_and_degrade_independently(self):
        historical = self.replay_fixture()
        revision = historical.with_name('revision.json')
        second = dict(self.raw, origin='Measured scan revision · local floor panels',
                      question='Count the storeys', method='local_storey_panels')
        revision.write_text(json.dumps(dict(version=1, reports=[second])))
        with patch.multiple(scan, REVISION_REPLAY_FILE=revision,
                            REVISION_REPLAY_SHA256=hashlib.sha256(revision.read_bytes()).hexdigest()):
            saved = {r['question']:r for r in scan.scan_info(self.lib,self.path)['saved']}
            self.assertEqual(len(saved),4)
            self.assertEqual(saved[second['question']]['method'],'local_storey_panels')
            historical.unlink()
            self.assertEqual([r['question'] for r in scan.scan_info(self.lib,self.path)['saved']], [second['question']])
            revision.write_bytes(b'corrupted')
            self.assertEqual(scan.scan_info(self.lib,self.path)['saved'],[])

    def test_newer_interactive_wins_and_weak_candidate_preserves_saved_answers(self):
        self.replay_fixture()
        prior = dict(self.raw, question='How many saunas?', answer=0,evidence=[])
        self.store([(prior['question'],prior),(self.q,dict(self.raw,model='old-model'))])
        saved = {r['question']:r for r in scan.scan_info(self.lib,self.path)['saved']}
        self.assertEqual(saved[prior['question']]['status'],'answered')
        self.assertEqual(saved[self.q]['origin'],'Measured scan reader · reused hosted response')
        location = self.storage/self.raw['image_sha256']
        location.mkdir(parents=True)
        (location/'interactive.json').write_text(json.dumps(dict(self.raw,answer=0,evidence=[],origin='Rechecked locally')))
        new = scan.scan_answer(self.lib,self.path,self.q)
        self.assertEqual((new['answer'],new['origin']),(0,'Rechecked locally'))


class RevisionExportTests(unittest.TestCase):
    def test_export_verifies_source_and_omits_offline_abstentions_and_private_fields(self):
        from scripts import export_scan_replay as exporter
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base/'new/outputs').mkdir(parents=True)
            (base/'old').mkdir()
            archive = base/'synthetic.zip'
            rows, predictions = [], {}
            with ZipFile(archive,'w') as originals:
                for n in range(48):
                    image = f'data/cubicasa5k/fixture-{n}.png'
                    data = str(n).encode()
                    originals.writestr('junction-dataset/'+image,data)
                    digest = exporter.sha(data)
                    for q in range(8 + (n<14)):
                        text = f'Count synthetic target {q}'
                        rid = exporter.sha((image+'|'+text).encode())[:16]
                        rows.append(dict(id=rid,path=image,question=text,image_sha256=digest))
                        out = dict(id=rid,question=text,image_sha256=digest,status='abstained',answer=None,
                                   evidence=[],method='offline_fallback',elapsed_ms=12345)
                        if n==0 and q==0:
                            out.update(status='answered',answer=1,method='local_room_labels',
                                       evidence=[dict(label='MH',box=[10,20,30,40],private_metadata='discard')])
                        predictions[rid] = out
                        (base/'new/outputs'/(rid+'.json')).write_bytes(exporter.canonical(out))
            manifest = dict(images=48,rows=rows)
            manifest_file = base/'inputs.json'
            manifest_file.write_bytes(exporter.canonical(manifest))
            manifest_sha = exporter.sha(exporter.canonical(manifest))
            pins = {}
            for arm in ('old','new'):
                seal = dict(rows=398, manifest_sha256=manifest_sha, config_sha256='synthetic',
                            predictions_sha256=exporter.sha(exporter.canonical(predictions)))
                (base/arm/'seal.json').write_bytes(exporter.canonical(seal))
                pins[arm] = exporter.sha(exporter.canonical(seal))
            with patch.multiple(exporter, REVISION_MANIFEST_SHA=manifest_sha, REVISION_SEALS=pins):
                result = json.loads(exporter.export_revision(manifest_file,base,archive))
                self.assertEqual(len(result['reports']),1)
                report = result['reports'][0]
                self.assertEqual((report['status'],report['model']),('answered','Room label OCR'))
                self.assertEqual(report['evidence'],[{'label':'MH','box':[10,20,30,40]}])
                self.assertNotIn('elapsed_ms',report)
                output = base/'new/outputs'/(rows[-1]['id']+'.json')
                changed = json.loads(output.read_bytes())
                changed['elapsed_ms'] = 1
                output.write_bytes(exporter.canonical(changed))
                with self.assertRaisesRegex(ValueError,'do not match the seal'):
                    exporter.export_revision(manifest_file,base,archive)
