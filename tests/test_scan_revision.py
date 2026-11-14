"""Check independent sampling, bounds on scoring and offline fallback accounting."""

import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import benchmark_scan_revision as revision
import nemotron


class ScanRevisionTest(unittest.TestCase):
    def test_manifest_has_disjoint_images_and_inference_fields_only(self):
        manifest = json.loads(revision.FROZEN.read_text())
        history = json.loads(revision.PREVIOUS.read_text())
        self.assertEqual(revision.sha(revision.canonical(manifest)), revision.FINGERPRINT)
        paths = {r["path"] for r in manifest["rows"]}
        excluded = {r["path"] for r in history["rows"]}
        excluded.update(p for items in history["excluded"].values() for p in items)
        self.assertFalse(paths & excluded)
        self.assertEqual(Counter(map(revision.style, paths)), revision.QUOTAS)
        self.assertEqual(len(manifest["rows"]), 398)
        self.assertEqual(len({r["id"] for r in manifest["rows"]}), 398)
        self.assertEqual(set(manifest["category_counts"]), revision.FAMILIES)
        for row in manifest["rows"]:
            self.assertEqual(set(row), {"id", "question", "path", "category", "image_sha256", "style"})

    def test_golds_stay_closed_until_both_seals_match(self):
        manifest = json.loads(revision.FROZEN.read_text())
        with TemporaryDirectory() as tmp, patch.object(revision, "ZipFile") as archive:
            folder = Path(tmp)
            args = SimpleNamespace(work=folder, archive=folder / "unused.zip")
            with self.assertRaisesRegex(ValueError, "Missing sealed arm"):
                revision.score(args, manifest)
            archive.assert_not_called()

    def test_answered_zero_abstention_and_malformed_positive(self):
        reader = SimpleNamespace(nemotron=nemotron)

        def predict(result):
            return revision.normalize(reader, result, "Question?", "123", 1)

        result = predict(dict(status="answered", answer=0, evidence=[]))
        self.assertEqual((result["status"], result["answer"]), ("answered", 0))
        abstained = predict(dict(status="unavailable", answer=None, evidence=[]))
        self.assertEqual((abstained["status"], abstained["answer"]), ("abstained", None))
        with self.assertRaises(nemotron.InvalidEvidence):
            predict(dict(status="answered", answer=1, evidence=[]))

    def test_numeric_accuracy_does_not_reward_abstention_as_zero(self):
        records = [
            {
                "gold": 0,
                "old": {"answer": 0, "status": "answered", "correct": True},
                "new": {"answer": None, "status": "abstained", "correct": False},
            },
            {
                "gold": 3,
                "old": {"answer": 7, "status": "answered", "correct": False},
                "new": {"answer": 3, "status": "answered", "correct": True},
            },
        ]
        result = revision.paired_metrics(records)
        self.assertEqual(result["old"]["answered"], 2)
        self.assertEqual(result["new"]["answered"], 1)
        self.assertEqual(result["old"]["accuracy"], result["new"]["accuracy"])
        self.assertEqual(result["paired"]["lost_exact"], 1)
        self.assertEqual(result["mean_absolute_error_on_both_answered"], {"old": 4, "new": 0})

    def test_bootstrap_resamples_whole_unequal_drawings(self):
        records = [
            dict(path=path, style="test", old={"correct": False}, new={"correct": True})
            for path in ("a", "b", "b", "b")
        ]
        self.assertEqual(revision.clustered_interval(records, 200), [100, 100])

    def test_snapshot_rejects_changed_code_and_includes_private_helpers(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "scan_reader.py").write_text("from . import helper\nfrom scripts import nested\n")
            (scripts / "nested.py").write_text("VALUE = 0\n")
            helper = scripts / "helper.py"
            helper.write_text("VALUE = 1\n")
            with patch.object(revision, "ROOT", root):
                _, files = revision.snapshot(root / "old", "working", [])
                self.assertEqual(
                    set(files), {"scripts/scan_reader.py", "scripts/helper.py", "scripts/nested.py"}
                )
                helper.write_text("VALUE = 2\n")
                with self.assertRaisesRegex(ValueError, "Source changed"):
                    revision.snapshot(root / "old", "working", [])


if __name__ == "__main__":
    unittest.main()
