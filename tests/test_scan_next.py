"""Check the scan-next freeze, seals, blinding order, leak check and reference builder offline."""

import io
import json
import socket
import struct
import sys
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import benchmark_scan_next as nxt


def rows_for(paths, categories=("windows", "bedrooms")):
    rows = []
    for path in paths:
        for category in categories:
            question = f"How many {category} are shown on this floor plan?"
            rows.append(dict(id=nxt.stable(path, question)[:16], path=path, question=question,
                             style=nxt.style(path), category=category, image_sha256=nxt.sha(path.encode())))
    return rows


def make_arm(work, manifest, arm, records, source=b"VALUE = 1\n", revision=nxt.BASE, seal=True):
    root = work / arm
    (root / "outputs").mkdir(parents=True)
    (root / "src/scripts").mkdir(parents=True)
    (root / "src/scripts/scan_reader.py").write_bytes(source)
    config = dict(source_sha256={"scripts/scan_reader.py": nxt.sha(source)}, revision=revision,
                  manifest_sha256=nxt.fingerprint_of(manifest), weights_sha256="w", detector_source={},
                  detector_revision="r", environment={}, network="disabled")
    nxt.save(root / "config.json", config)
    for q, (status, answer) in zip(manifest["rows"], records):
        nxt.save(root / "outputs" / (q["id"] + ".json"),
                 dict(id=q["id"], question=q["question"], image_sha256=q["image_sha256"], status=status,
                      answer=answer, evidence=[], method="synthetic", elapsed_ms=1))
    if not seal:
        return root
    _, seal, _ = nxt.seal_of(work, manifest, arm)
    nxt.save(root / "seal.json", seal)
    return root


class FrozenManifest(unittest.TestCase):
    def test_manifest_is_frozen_label_free_and_disjoint_from_exposed_drawings(self):
        manifest = json.loads(nxt.FROZEN.read_text())
        self.assertEqual(nxt.fingerprint_of(manifest), nxt.FINGERPRINT)
        nxt.load_manifest(nxt.FROZEN)
        rows = manifest["rows"]
        paths = {r["path"] for r in rows}
        self.assertEqual(Counter(map(nxt.style, paths)), nxt.QUOTAS)
        self.assertEqual(len(rows), manifest["questions"])
        self.assertEqual(sum(r["category"] in nxt.COMPARABLE for r in rows), manifest["comparable_questions"])
        self.assertEqual(set(manifest["category_counts"]), nxt.FAMILIES)
        self.assertNotIn('"answer"', nxt.FROZEN.read_text())
        self.assertNotIn('"unit"', nxt.FROZEN.read_text())
        for r in rows:
            self.assertEqual(len({x["image_sha256"] for x in rows if x["path"] == r["path"]}), 1)
        history = json.loads(nxt.HOLDOUT_MANIFEST.read_text())
        exposed = {r["path"] for r in history["rows"]}.union(*map(set, history["excluded"].values()))
        exposed |= {r["path"] for r in json.loads(nxt.REVISION_MANIFEST.read_text())["rows"]}
        self.assertFalse(paths & exposed)
        self.assertEqual(len({r["image_sha256"] for r in rows}), len(paths))
        if not nxt.RESERVED.exists():
            self.skipTest("Reserved list is a local asset")
        self.assertTrue(paths <= set(nxt.RESERVED.read_text().split()))
        self.assertEqual(manifest["reserved_list_sha256"], nxt.sha(nxt.RESERVED.read_bytes()))

    def test_selection_is_seeded_stratified_and_refuses_small_pools(self):
        pool = {f"data/cubicasa5k/high_quality-{i}.png" for i in range(9)}
        pool |= {f"data/cubicasa5k/high_quality_architectural-{i}.png" for i in range(30)}
        quotas = {"high_quality": 3, "high_quality_architectural": 7}
        picked = nxt.select(pool, quotas, "seed-a")
        self.assertEqual(picked, nxt.select(set(sorted(pool, reverse=True)), quotas, "seed-a"))
        self.assertEqual(Counter(map(nxt.style, picked)), quotas)
        self.assertNotEqual(picked, nxt.select(pool, quotas, "seed-b"))
        with self.assertRaisesRegex(ValueError, "Not enough"):
            nxt.select(pool, {"high_quality": 10}, "seed-a")


class ArmsAndSeals(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.work = Path(self.tmp.name)
        paths = ["data/cubicasa5k/high_quality-1.png", "data/cubicasa5k/high_quality_architectural-2.png"]
        self.manifest = dict(images=2, rows=rows_for(paths))

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_arms_are_pinned_and_after_needs_a_commit(self):
        self.assertEqual(nxt.arm_revision("before", None), nxt.BASE)
        self.assertEqual(nxt.arm_revision("before-repeat", nxt.BASE), nxt.BASE)
        for arm, rev in (("before", "HEAD"), ("after", None), ("after", "working"), ("Bad Name", "HEAD")):
            with self.assertRaises(ValueError):
                nxt.arm_revision(arm, rev)

    def test_seal_detects_changed_outputs_and_snapshot_files(self):
        root = make_arm(self.work, self.manifest, "before", [("answered", 0), ("abstained", None)] * 2)
        nxt.verify_arm(self.work, self.manifest, "before")
        (root / "src/scripts/scan_reader.py").write_text("VALUE = 2\n")
        with self.assertRaisesRegex(ValueError, "Snapshot file changed"):
            nxt.verify_arm(self.work, self.manifest, "before")
        (root / "src/scripts/scan_reader.py").write_text("VALUE = 1\n")
        output = root / "outputs" / (self.manifest["rows"][0]["id"] + ".json")
        record = json.loads(output.read_text())
        nxt.save(output, dict(record, elapsed_ms=2))
        with self.assertRaisesRegex(ValueError, "Broken arm seal"):
            nxt.verify_arm(self.work, self.manifest, "before")

    def test_scoring_never_opens_answers_unless_both_arms_are_sealed(self):
        args = SimpleNamespace(work=self.work, archive=self.work / "unused.zip", before="before", after="after",
                               report=None)
        with patch.object(nxt, "FINGERPRINT", None), patch.object(nxt.revision, "read_targets") as targets, \
                patch.object(nxt.revision, "ZipFile") as archive:
            with self.assertRaisesRegex(ValueError, "Missing sealed arm: before"):
                nxt.score(args, self.manifest)
            make_arm(self.work, self.manifest, "before", [("answered", 0)] * 4)
            with self.assertRaisesRegex(ValueError, "Missing sealed arm: after"):
                nxt.score(args, self.manifest)
            for action in (nxt.localize, nxt.fetch_refs, nxt.example):
                with self.assertRaisesRegex(ValueError, "Missing sealed arm: after"):
                    action(SimpleNamespace(**vars(args), references=self.work / "r.zip", limit=1), self.manifest)
            targets.assert_not_called()
            archive.assert_not_called()

    def test_noise_counts_answer_and_evidence_differences_only(self):
        make_arm(self.work, self.manifest, "before", [("answered", 0), ("abstained", None), ("answered", 0), ("unknown", None)])
        make_arm(self.work, self.manifest, "before-repeat", [("answered", 0), ("answered", 0), ("answered", 0), ("unknown", None)])
        result = nxt.noise(SimpleNamespace(work=self.work, arms=["before", "before-repeat"]), self.manifest)
        self.assertEqual((result["answers_differing"], result["evidence_lists_differing"]), (1, 0))

    def test_offline_guard_blocks_sockets(self):
        with nxt.offline():
            with self.assertRaises(AssertionError):
                socket.create_connection(("127.0.0.1", 9))
            with socket.socket() as s, self.assertRaises(AssertionError):
                s.connect(("127.0.0.1", 9))


def fake_reader(outcomes):
    """A reader whose run() returns or raises the next outcome."""
    outcomes = iter(outcomes)

    def run(image, question, base, model, key):
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome, question=question) if isinstance(outcome, dict) else outcome

    nemotron = nxt.revision.nemotron
    return SimpleNamespace(run=run, nemotron=SimpleNamespace(
        MODEL="m", run=None, parse_count=nemotron.parse_count, InvalidEvidence=nemotron.InvalidEvidence))


def answered(n, **extra):
    return dict(status="answered", answer=n, evidence=[dict(label="x", box=[i, i, i + 5, i + 5]) for i in range(n)],
                coordinate_system=nxt.COORDS, method="local", **extra)


class InvalidReports(unittest.TestCase):
    BAD = [
        ("count 2 with one box", dict(answered(1), answer=2)),
        ("box equal to the whole sheet", dict(answered(1), evidence=[dict(label="x", box=[0, 0, 1000, 1000])])),
        ("coordinate 1000.5", dict(answered(1), evidence=[dict(label="x", box=[1, 1, 1000.5, 5])])),
        ("status error", dict(status="error", answer=None, evidence=[])),
        ("not a dict", None),
        ("zero with invalid coverage evidence", answered(0, coverage_evidence=[dict(label="x", box=[0, 0, 1000, 1000])])),
        ("answered without the coordinate system", dict(answered(1), coordinate_system="pixels")),
    ]

    def test_invalid_reports_and_reader_errors_become_recorded_deferrals(self):
        for label, report in self.BAD:
            result = nxt.read_prompt(fake_reader([report]), Path("x.png"), "q", "d")
            self.assertEqual((result["status"], result["answer"], result["evidence"], result["method"]),
                             ("abstained", None, [], "invalid_report"), label)
            self.assertLessEqual(len(result["reason"]), 220)
        result = nxt.read_prompt(fake_reader([IndexError("x" * 500)]), Path("x.png"), "q", "d")
        self.assertEqual((result["status"], result["method"]), ("abstained", "reader_error"))
        self.assertTrue(result["reason"].startswith("IndexError: x") and len(result["reason"]) == 220)
        good = answered(0, coverage_evidence=[dict(label="Apartment", box=[1, 1, 9, 9])])
        self.assertEqual(nxt.read_prompt(fake_reader([good]), Path("x.png"), "q", "d")["answer"], 0)
        unavailable = dict(status="unavailable", answer=None, evidence=[], reason="r")
        self.assertEqual(nxt.read_prompt(fake_reader([unavailable]), Path("x.png"), "q", "d")["method"],
                         "offline_fallback")
        for guard in nxt.GUARDS:
            with self.assertRaises(AssertionError):
                nxt.read_prompt(fake_reader([AssertionError(guard)]), Path("x.png"), "q", "d")

    def test_one_bad_report_neither_aborts_nor_unseals_an_arm(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            paths = ["data/cubicasa5k/high_quality-1.png", "data/cubicasa5k/high_quality_architectural-2.png"]
            for p in paths:
                (work / "inputs").mkdir(exist_ok=True)
                (work / "inputs" / Path(p).name).write_bytes(p.encode())
            manifest = dict(images=2, rows=rows_for(paths))
            root = make_arm(work, manifest, "after", [], seal=False)
            reader = fake_reader([answered(1), self.BAD[0][1], ValueError("cv2.error"), answered(2)])
            nxt.infer(reader, manifest, work / "inputs", root, "after")
            _, seal, _ = nxt.seal_of(work, manifest, "after")
            nxt.save(root / "seal.json", seal)
            rows, _, _ = nxt.verify_arm(work, manifest, "after")
            methods = [rows[q["id"]]["method"] for q in manifest["rows"]]
            self.assertEqual(methods, ["local", "invalid_report", "reader_error", "local"])
            with patch.object(nxt, "FINGERPRINT", None), redirect_stdout(io.StringIO()) as out:
                nxt.verify(SimpleNamespace(work=work, arm="after"), manifest)
            self.assertIn("reader_error 1, invalid_report 1", out.getvalue())


class Summary(unittest.TestCase):
    def record(self, path, category, gold, before, after):
        def arm(value):
            status = "answered" if value is not None else "abstained"
            return dict(status=status, answer=value, correct=status == "answered" and value == gold, evidence=[])
        return dict(id=path + category, path=path, style=nxt.style(path), category=category, question=category,
                    gold=gold, old=arm(before), new=arm(after))

    def test_tracks_regressions_newly_wrong_and_equal_style_weighting(self):
        hq, arch = "data/cubicasa5k/high_quality-1.png", "data/cubicasa5k/high_quality_architectural-2.png"
        records = [
            self.record(hq, "windows", 3, 3, 4),        # regression in track 1
            self.record(hq, "floors", 1, None, 1),      # gain in track 2
            self.record(arch, "showers", 2, None, 5),   # deferred before, wrong after
            self.record(arch, "sinks", 1, 1, 1),
        ]
        summary = nxt.summarize(records, {"high_quality": 1, "high_quality_architectural": 1}, "seed")
        self.assertEqual([r["category"] for r in summary["regressions"]], ["windows"])
        self.assertEqual([r["category"] for r in summary["newly_wrong"]], ["showers"])
        self.assertEqual([r["category"] for r in summary["gains"]], ["floors"])
        self.assertEqual(summary["by_track"]["track1_openings"]["paired"]["lost_exact"], 1)
        self.assertEqual(summary["by_track"]["track2_deferred"]["after"]["questions"], 2)
        self.assertEqual(summary["comparable_eleven_families"]["before"]["questions"], 3)
        self.assertEqual(summary["by_group"]["objects"]["before"]["questions"], 3)
        weighted = summary["equal_style_weighted_exact_accuracy"]
        self.assertEqual((weighted["before"], weighted["after"]), (0.5, 0.5))
        self.assertEqual(summary["overall"]["delta_exact_pp"], 0.0)


class LeakCheck(unittest.TestCase):
    def test_names_hashes_and_copies_are_found(self):
        stems = {"data/cubicasa5k/high_quality-12.png"}
        hashes = {nxt.sha(b"png bytes")}
        for text in (b"x high_quality-12.png", b"cubicasa5k/high_quality/12/model.svg",
                     b"path=data%2Fcubicasa5k%2Fhigh_quality-12.png", ("digest " + next(iter(hashes))).encode()):
            self.assertTrue(nxt.scan_text(text, stems, hashes), text)
        self.assertFalse(nxt.scan_text(b"high_quality-123 high_quality_architectural-12", stems, hashes))
        self.assertEqual(nxt.scan_text(b"png bytes", stems, hashes), {"identical image bytes"})

    def test_git_and_scratch_findings_respect_the_frozen_manifest_exception(self):
        path = "data/cubicasa5k/high_quality-12.png"
        manifest = dict(rows=rows_for([path]))
        frozen = json.dumps(manifest).encode()
        blobs = {"a": {"docs/scan-next-inputs.json"}, "b": {"scripts/scan_rooms.py"}, "c": {"notes/high_quality-12.txt"}}
        contents = {"a": frozen, "b": b"SKIP = 'high_quality-12'\n", "c": b"nothing"}
        with TemporaryDirectory() as tmp, patch.object(nxt, "git_blobs", return_value=blobs), \
                patch.object(nxt, "read_blobs", return_value=contents), \
                patch.object(nxt, "FINGERPRINT", nxt.fingerprint_of(json.loads(frozen))):
            scratch = Path(tmp)
            (scratch / "cache.json").write_text(json.dumps({"image": manifest["rows"][0]["image_sha256"]}))
            (scratch / "clean.txt").write_text("high_quality-13")
            findings = nxt.leak_findings(manifest, "f" * 40, [scratch])
        where = sorted((f["where"], f["paths"][0].rsplit("/", 1)[-1]) for f in findings)
        self.assertEqual(where, [("git", "high_quality-12.txt"), ("git", "scan_rooms.py"), ("scratch", "cache.json")])


class References(unittest.TestCase):
    def test_reference_zip_is_built_from_ranges_and_checked_against_frozen_pngs(self):
        path = "data/cubicasa5k/high_quality-12.png"
        original = b"\x89PNG original"
        manifest = dict(rows=[dict(rows_for([path], ("windows",))[0], image_sha256=nxt.sha(original))])
        with TemporaryDirectory() as tmp:
            upstream = Path(tmp) / "upstream.zip"
            with ZipFile(upstream, "w", ZIP_DEFLATED) as z:
                z.writestr("cubicasa5k/high_quality/11/model.svg", "<svg/>")
                for member, data in (("model.svg", b"<svg>windows</svg>"), ("F1_scaled.png", b"scaled" * 50),
                                     ("F1_original.png", original)):
                    z.writestr("cubicasa5k/high_quality/12/" + member, data)
            raw = upstream.read_bytes()
            end = raw.rindex(b"PK\x05\x06")
            size, offset = struct.unpack_from("<II", raw, end + 12)
            central = raw[offset : offset + size]
            fetched = []

            def fetch(start, stop):
                fetched.append((start, stop))
                return raw[start : stop + 1]

            out = Path(tmp) / "refs" / "references.zip"
            self.assertEqual(nxt.build_references(manifest, central, fetch, lambda p: original, out), 3)
            with ZipFile(out) as z:
                self.assertEqual(z.read("cubicasa5k/high_quality/12/model.svg"), b"<svg>windows</svg>")
                self.assertEqual(z.read("cubicasa5k/high_quality/12/F1_original.png"), original)
                self.assertNotIn("cubicasa5k/high_quality/11/model.svg", z.namelist())
            self.assertEqual(len(fetched), 2)  # the original PNG came from the sponsor copy
            wrong = dict(rows=[dict(manifest["rows"][0], image_sha256="0" * 64)])
            with self.assertRaisesRegex(ValueError, "differs from the frozen PNG"):
                nxt.build_references(wrong, central, fetch, None, out)


class Audit(unittest.TestCase):
    def test_inventory_rules_are_pinned_by_content(self):
        rel = ".local/evaluation/scan-holdout/test.txt"
        self.assertTrue(nxt.classify(rel, nxt.SPLITS["test"], True))
        self.assertIsNone(nxt.classify(rel, "0" * 64, True))
        self.assertTrue(nxt.classify("anything/questions.jsonl", nxt.MANIFEST, True))
        self.assertTrue(nxt.classify(nxt.GATE_DIR + "/high_quality-1.json", "x", True))
        self.assertIsNone(nxt.classify(nxt.GATE_DIR + "/high_quality-1.json", "x", False))
        self.assertIsNone(nxt.classify(".local/scan-dev/notes.json", "x", True))

    def test_file_scan_reads_names_bytes_and_zip_members(self):
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "cache.npz"
            with ZipFile(archive, "w") as z:
                z.writestr("high_quality_architectural-77.npy", b"")
            digest, names, _ = nxt.file_scan(archive)
            self.assertIn("data/cubicasa5k/high_quality_architectural-77.png", names)
            self.assertEqual(digest, nxt.sha(archive.read_bytes()))


if __name__ == "__main__":
    unittest.main()
