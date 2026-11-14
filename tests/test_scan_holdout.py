"""Exercise frozen-input and no-leakage guarantees without using a network provider."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
import benchmark_scan_holdout as eval_scan


class ScanHoldout(unittest.TestCase):
    def test_frozen_manifest_never_sends_answers_or_exposed_paths(self):
        manifest=eval_scan.load_frozen(eval_scan.FROZEN)
        self.assertEqual(eval_scan.sha(eval_scan.canonical(manifest)),eval_scan.FINGERPRINT)
        prior={p for excluded in manifest["excluded"].values() for p in excluded}
        rows=manifest["rows"]
        self.assertTrue(prior.isdisjoint({r["path"] for r in rows}))
        self.assertEqual(set(manifest["questions_by_category"]),set(eval_scan.NAMES))
        for p in {r["path"] for r in rows}:
            selected=[r for r in rows if r["path"]==p]
            self.assertEqual(len({r["question"] for r in selected}),3)
            self.assertEqual(len({r["image_sha256"] for r in selected}),1)

    def test_outage_replay_preserves_local_and_changed_hosted_routes(self):
        from scripts import scan_reader
        with TemporaryDirectory() as temp:
            work = Path(temp)
            image = work / "scan.png"
            image.write_bytes(b"synthetic drawing")
            digest = eval_scan.sha(image.read_bytes())
            query = "How many floors (storeys) does this floor plan show?"
            direct_query = "How many windows are shown on this floor plan?"
            answered = {"status": "answered", "answer": 0, "evidence": []}
            for question, local_answer, expected in (
                (query, {**answered, "method":"synthetic_local"}, "synthetic_local"),
                (direct_query, None, "nemotron_direct"),
                (query, None, "nemotron_original"),
            ):
                with self.subTest(expected=expected):
                    row = {"path":"scan.png", "question":question, "id":"trial", "image_sha256":digest, "category":"test"}
                    old = {**row, "method":"original_full_image", "status":"unavailable", "answer":None,
                           "evidence":[], "reason":"Inference endpoint returned HTTP 429."}
                    eval_scan.save(work/"baseline/trial.json", old)
                    direct = eval_scan.uses_direct_fallback(scan_reader, image, question)
                    args = SimpleNamespace(arm="candidate", work=work, timeout=5, record_failures=True,
                                           replay_only=False, direct_only=False, unchanged_outages=set() if direct else {"trial"})
                    fresh = {**answered, "method":"nemotron_direct", "image_sha256":digest, "question":question}
                    with patch.object(scan_reader.scan_rooms, "predict", return_value=local_answer), \
                            patch.object(scan_reader.scan_objects, "predict", return_value=None), \
                            patch.object(scan_reader, "hosted_count", return_value=fresh) as structured, \
                            patch.object(scan_reader.nemotron, "run", side_effect=AssertionError("Unplanned provider request")):
                        actual = eval_scan.infer(args,row,work,scan_reader,Mock(),"synthetic-credential")
                    self.assertEqual(actual["method"], expected)
                    self.assertEqual(actual["status"], "unavailable" if expected == "nemotron_original" else "answered")
                    self.assertEqual(structured.call_count, int(expected == "nemotron_direct"))

    def test_seal_rejects_missing_or_rewritten_predictions(self):
        with TemporaryDirectory() as d:
            root=Path(d);q={"id":"abc","path":"x.png","question":"How many?", "image_sha256":"90"}
            report={**q,"status":"answered","answer":0,"evidence":[]}
            eval_scan.save(root/"a/abc.json",report)
            eval_scan.save(root/"a/seal.json",{"predictions_sha256":eval_scan.sha(eval_scan.canonical([report])),
                                               "manifest_sha256":eval_scan.FINGERPRINT})
            self.assertEqual(eval_scan.read_arm(root,"a",[q])[0],[report])
            eval_scan.save(root/"a/abc.json",{**report,"answer":1})
            with self.assertRaisesRegex(ValueError,"seal"):
                eval_scan.read_arm(root,"a",[q])

    def test_cluster_bootstrap_uses_each_replicates_available_prompt_count(self):
        records = [{"path":p,"baseline":{"correct":False},"candidate":{"correct":True}}
                   for p in ("a.png","b.png","b.png","b.png")]
        self.assertEqual(eval_scan.paired_intervals(records), [100.0,100.0])

    def test_accuracy_treats_unknown_as_attempted_not_numeric(self):
        states=eval_scan.metrics([{"correct":True,"status":"answered"},{"correct":False,"status":"unknown"},
                                  {"correct":False,"status":"answered"}])
        self.assertEqual((states["correct"],states["wrong"],states["unknown"]),(1,1,1))
        self.assertEqual(states["precision_pct"],50.0)
        self.assertEqual(states["correct_pct_all"],33.33)


if __name__=="__main__":
    unittest.main()
