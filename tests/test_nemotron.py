"""Check model-to-UI evidence contracts without calling inference providers."""

import io
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError, URLError

from scripts import nemotron


SAMPLE = Path(__file__).resolve().parents[1] / 'public/data/finnish/high_quality_architectural-13066.png'


class Capture:
    def __init__(self, reply):
        self.reply = reply
        self.request = None

    def open(self, req, *, timeout):
        self.request = req
        if isinstance(self.reply, Exception):
            raise self.reply
        return io.BytesIO(json.dumps(self.reply).encode())


class NemotronEvidence(unittest.TestCase):
    def setUp(self):
        self.answer = {'status': 'answered', 'answer': 2, 'evidence': [
            {'label': 'Example A', 'box': [200, 400, 250, 450]},
            {'label': 'Example B', 'box': [600, 250, 680, 300]}]}

    def call(self, provider):
        return nemotron.run(SAMPLE, 'Find marked examples.', 'https://example.invalid/v1',
                            'test-vision-model', 'test-token-123', opener=provider)

    def test_preserves_independent_coordinates_and_sends_real_image(self):
        c = Capture({'model': 'provider-model-version', 'choices': [{'message': {'content': '```json\n' + json.dumps(self.answer) + '\n```'}}],
                     'usage': {'prompt_tokens': 400, 'completion_tokens': 45, 'total_tokens': 445,
                               'completion_tokens_details': {'reasoning_tokens': 3}}})
        report = self.call(c)
        self.assertEqual(report['status'], 'answered')
        self.assertEqual(report['evidence'], self.answer['evidence'])
        self.assertEqual(report['usage']['reasoning_tokens'], 3)
        self.assertEqual(report['served_model'], 'provider-model-version')
        self.assertEqual(c.request.full_url, 'https://example.invalid/v1/chat/completions')
        body = json.loads(c.request.data)
        self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,iVBOR'))
        self.assertNotIn('test-token-123', json.dumps(report))

    def test_direct_reader_reserves_the_response_for_json(self):
        reply = Capture({'choices':[{'message':{'content':json.dumps(self.answer)}}]})
        report = nemotron.run(SAMPLE, 'Count rooms', 'https://example.invalid', 'model', 'test',
                              opener=reply, thinking=False, json_output=True)
        self.assertEqual(report['status'], 'answered')
        payload = json.loads(reply.request.data)
        self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(payload['response_format'], {'type':'json_object'})

    def test_unknown_for_malformed_missing_or_unverifiable_boxes(self):
        for data in ('not JSON', json.dumps(dict(self.answer, answer=3)),
                     json.dumps(dict(self.answer, evidence=self.answer['evidence'][:1] * 2))):
            with self.subTest(data=data):
                report = self.call(Capture({'choices': [{'message': {'content': data}}]}))
                self.assertEqual((report['status'], report['answer'], report['evidence']), ('unknown', None, []))
        for box in ([0, 0, 1000, 1000], [20, 500, 19, 510], [20, 500, 510, 1010], [False, 20, 200, 500]):
            with self.subTest(box=box):
                with self.assertRaises(nemotron.InvalidEvidence):
                    nemotron.parse_count(json.dumps({'status': 'answered', 'answer': 1, 'evidence': [{'label': 'x', 'box': box}]}))

    def test_model_abstention_and_service_failure_have_distinct_status(self):
        ack = json.dumps({'status': 'unknown', 'reason': 'label unreadable'})
        self.assertEqual(self.call(Capture({'choices': [{'message': {'content': ack}}]}))['status'], 'unknown')
        for err in (URLError('host down'), HTTPError('https://example.invalid/v1', 429, 'limit', {}, None)):
            self.assertEqual(self.call(Capture(err))['status'], 'unavailable')
        self.assertEqual(self.call(Capture({'choices': []}))['status'], 'unavailable')

    def test_valid_zero_differs_from_abstention(self):
        self.assertEqual(nemotron.parse_count('{"status":"answered","answer":0,"evidence":[]}'),
                         {'status': 'answered', 'answer': 0, 'evidence': []})

    def test_unavailable_still_identifies_original_unchanged_image(self):
        report = nemotron.run(SAMPLE, 'Count labels.', 'https://example.invalid/v1', 'test-model', None)
        self.assertEqual(report['status'], 'unavailable')
        self.assertEqual(report['image_sha256'], 'f1cf7f64462f9687e41b4a5848534cc409c32212cc3c6ae02b9e315039d6f6af')
        self.assertIsNone(report['latency_ms'])

    def test_credentials_go_only_to_a_configured_https_destination(self):
        for bad_url in ('', 'ftp://example.org', 'https://u:p@example.org/v1', 'https://example.org/?secret=abc'):
            with self.subTest(url=bad_url):
                with self.assertRaises(ValueError):
                    nemotron.endpoint_url(bad_url)
        self.assertEqual(nemotron.endpoint_url('https://example.org/v1/chat/completions'), 'https://example.org/v1/chat/completions')


if __name__ == '__main__':
    unittest.main()
