# Pre-registered scan-next comparison on 72 fresh test drawings

This protocol fixes the next before/after measurement of the local scan reader before anyone sees a result. The reference arm is the reader at commit `b948d6744548417b7a037f32b9317c830ea7e52e`, the version that returned 167 exact counts on 398 prompts in the [48-drawing comparison](scan-revision-evaluation.md). The after arm is any later committed revision. Both arms read the same 72 original CubiCasa5K PNGs and the same 608 released English count prompts through `scripts.scan_reader.run`, with a blank hosted endpoint and no key. The cohort was frozen and the reference arm was sealed twice before any implementation work was evaluated. No sponsor answer, unit or vector annotation for these drawings was opened to choose them or to run the reference arm. [Frozen manifest](scan-next-inputs.json) · [Evaluation script](../scripts/benchmark_scan_next.py)

## Drawings and questions

The pool is the set of sponsor drawings with released questions that are also in the authors’ official 400-image test split, minus every drawing an earlier Planproof experiment exposed. The split files are pinned by the SHA-256 digests in `scripts/benchmark_scan_holdout.py`. Three exposure groups come from earlier manifests: 489 distinct paths in the rows and excluded groups of [the 32-drawing holdout](scan-holdout-inputs.json), the 48 drawings of [the revision comparison](scan-revision-inputs.json), and an empty extra list from that comparison. Together they cover 537 distinct paths. The test split minus these groups is the 233-drawing reserved list that the implementers were told not to open (SHA-256 `aac8051cacc451a674ab6a1e6f791f36929700343218ee5babfb849c01688e49`). Thirteen reserved drawings have no released questions. The remaining pool has 220 drawings: 19 high_quality, 201 high_quality_architectural and no colorful drawings.

A new exposure audit searched 14,801 files under `.local/scan-dev`, `.local/scan-rooms-dev`, `.local/scan-results`, `.local/verification`, `.local/evaluation` (except this evaluation’s own directory), `public/data`, `docs` and `tests`. It looked for test-split drawing names in file names, file bytes and ZIP member names, and for the image SHA-256 of every pool PNG in file bytes or as a file digest. Only inventories named reserved drawings: the official split list and split map, the central directory of the public CubiCasa5K archive, the tail and a second copy of the sponsor ZIP, three byte-identical copies of the sponsor question file, and the release-wide bedroom-gate table and its 129 per-drawing gate files. That gate ran on 2026-11-13, before both earlier manifests, and both earlier freezes kept those drawings. Each inventory is pinned by content in the script, so a changed file would count as an exposure. The audit excluded no further drawing. No pool PNG had the same bytes as any of the 537 exposed PNGs, and no two pool PNGs were identical. The one file larger than 512 MB, the second sponsor ZIP copy, was checked by name and member list only. The audit digest is `ec8e6028b4cba42981cb190be235d9883e43e5f87d6c6fd792b988c6490085e2`, and the digest of all exclusion groups is `636fac46b061d8a91554ebb07c477e3ea5b4263663740284402e6bd25312247c`.

Selection used only paths, styles and the set of prompts each drawing has. Within each style the drawings were ordered by SHA-256 of the seed `planproof-scan-next-2026-11-14-evaluator-v1`, the word `drawing` and the path, and the first drawings were taken. The cohort has 12 high_quality and 60 high_quality_architectural drawings. High-quality drawings are the scarce style. Taking 12 of 19 leaves seven for a later round, where the suggested 15 would leave four. Sixty architectural drawings keep the ratio close to the release’s one high-quality drawing for every four architectural ones and give more paired drawings than the earlier 48, which should narrow the interval. The cohort leaves 148 of the 220 pool drawings unused, 7 high_quality and 141 high_quality_architectural.

Every released English count prompt for a selected drawing is in the manifest, across all twelve released families. That gives 608 prompts: 96 on high-quality and 512 on architectural drawings. By family they are 72 windows, 72 toilet bowls, 72 sinks, 72 floors, 66 showers, 51 doors, 47 kitchens, 42 saunas, 40 bedrooms, 30 separate WC rooms, 26 bathrooms and 18 balconies. The 542 prompts outside showers form the comparable subset, which uses the eleven families of the 398-prompt comparison. Each row carries an ID, path, question, style, family and image SHA-256, with no answer or unit. The manifest is read-only, its file SHA-256 is `4d8f1269b306021449464e2622cba51b8aef5f1066c77f089ba93265c1667e1b`, and its canonical JSON digest, pinned in the script as `FINGERPRINT`, is `3c5be563d29d5e3b246e18b9e5e6f1edc3bb7a9c03b139042c911a753b45f1b0`. The 72 PNGs are staged read-only under `.local/evaluation/scan-next/inputs/` and each is checked against its digest before use.

## Arms and seals

Each arm loads the reader from a snapshot of a Git revision under `.local/evaluation/scan-next/<arm>/src/`, never from working files. The snapshot follows the reader’s imports of product modules. For an after arm it also copies every tracked non-Python file under `scripts/` and any file passed with `--source`. The run step drops the harness directory from the import path and refuses to continue if any reader module loads from outside the snapshot. It reads staged PNGs only and receives no archive path. It forbids hosted calls by replacing the hosted client with an error, blocks socket connections and name lookups during inference, and refuses to start if `NEMOTRON_BASE_URL` or `NEMOTRON_API_KEY` is set. A hand-off to the hosted model therefore becomes a deferral. Outputs are written one prompt at a time and resume only with an identical configuration.

The configuration records the per-file source digests, the revision, the manifest digest, the detector source digests, the weight digest, the detector revision, the Python, macOS, package and Tesseract versions and the device. The seal records the digests of the configuration, the predictions in manifest order and the manifest, the per-file source digests and their combined digest. It is written once, after the last prompt, and every later command recomputes it from the files before use. Sealed outputs are read-only. Scoring requires the two arms to share weights, detector source, detector revision, environment, network setting and manifest.

The baseline arm `before` is pinned to `b948d67`. Its seven snapshot files have the same digests as the sources recorded in `.local/evaluation/scan-revision/new/config.json`, the reader that produced 167 of 398, so it is the published reader. Their combined digest is `9e5bc7772a72c25e7435f31d779913e73335a63a0c3b6f5239f47ccfb94de54d`.

The baseline ran on 2026-11-14 on the Apple M5 GPU (MPS) with Python 3.12.13, torch 2.15.0, numpy 2.5.4, Pillow 13.0.0, opencv-python-headless 5.0.0.93, Tesseract 5.5.3 and macOS 26.5.1, with the detector weights `dd20b4e1bf1d670f2125107b079df06958b1ccd36e49a464ab739aeb00b8e7a2` at upstream revision `c34440266665a11f4484eb06cd2e4b7d72ad76c1`. It took 854 seconds for 608 prompts. Its configuration digest is `bc9b120e654b3f2b3e734835805cd3beef768de0839ec9ee79b1a7ec43c4f7d6`, its predictions digest is `b5523194532929d32e2d56c61ad98d9518a755f8010fedd63a720e017deadd6e`, and the canonical digest of its seal is `412ddb3f9ea6297ce8d81a26ff45a320167a7b2ed4662a28b73395f9f8767a3a`. The same reader then ran again into a separate arm, `before-repeat`, with an identical configuration (seal `6310e14408bbdc47163919f5df241dabf7b79982d3647b7ef08fedef97bab2ca`). The two runs differed in no answer, no status, no method and no evidence list on any of the 608 prompts. Their prediction digests differ only because each record keeps its own elapsed time. Only structure was checked before scoring: every seal, every record’s schema and status, and the coverage of the manifest. No count, coverage or distribution of the baseline was summarised.

## Endpoints

Scoring opens the sponsor question file only after both seals verify, and it keeps answers for the 608 frozen rows only. A count is exact only when the arm answered and the integer equals the sponsor answer. A deferral counts in every denominator and is never treated as zero. Zero is a numeric answer.

**Primary endpoint.** The paired difference in exact accuracy over all 608 frozen prompts, after minus before, in percentage points. Its 95% interval comes from 10,000 bootstrap resamples of whole drawings within each style, keeping every prompt of a drawing together, with the seed string above plus `-bootstrap`. The round shows a measured improvement only if the lower end of this interval is above zero. The repeat-run agreement above says how large a difference the reader’s own variation can produce.

**Secondary endpoints.** For each arm: exact, wrong and deferred counts, coverage, and accuracy among answered prompts. These are reported overall, by family group, by family, by style, for the comparable eleven-family subset and as an equal-style-weighted exact accuracy, the mean of the two style accuracies. The comparable subset and the equal-style figure are the ones to set beside the 24 + 24 cohort. The family groups are objects (doors, windows, toilet bowls, sinks, showers; 333 prompts), rooms (bedrooms, saunas, kitchens, bathrooms, separate WC rooms, balconies; 203) and storeys (floors; 72). Paired gains and losses, newly answered prompts and mean absolute error on prompts both arms answered are reported for every block, and the clustered interval is reported for every block as a description.

**Per-track readout.** Track 1 is doors and windows (123 prompts). Track 2 is rooms, storeys and showers (341 prompts). Toilet bowls and sinks (144 prompts) belong to neither track and are reported as an untouched control. Each track reports the same paired block.

**Regressions.** The score lists every regression, a prompt that was exact before and not exact after, and every newly wrong prompt, deferred before and wrong after, with its ID, drawing, family, question, sponsor count and both arms’ status and answer. Gains are listed the same way.

**Localization.** After scoring, `scripts/score_scan_evidence.py` compares the marks on door, window, toilet-bowl and sink prompts with the original CubiCasa5K vector annotations at IoU 0.25, one mark per annotated object. It reports marks matched over marks placed, annotated objects located, and questions with every object marked and no extra mark, per class and in total. It checks each upstream original PNG against the frozen image digest.

## Validation of the scoring path

The same scoring functions reproduced every published figure of the 48-drawing comparison from its sealed arms and the existing reference ZIP: 156 and 167 exact of 398, 78 and 73 wrong, 164 and 158 deferred, 234 and 240 answered, 15 gains and 4 losses, 6 newly answered and all 6 exact, accuracy among answered 66.67% and 69.58%, mean absolute error 0.966 and 0.795 on prompts both answered and 1.254 and 1.028 on object prompts, a difference of +2.76 points with the interval +0.75 to +4.87, and every localization figure in [the marks table](scan-revision-marks.md), including 346 of 458 windows located and 346 of 373 window marks matched. Thirty of thirty figures matched. Run `python3 scripts/benchmark_scan_next.py validate --references .local/scan-dev/revision-scoring/references.zip` under the `uv` command below to repeat it.

## Runbook for the scoring session

Run these from a checkout that contains this protocol and the script, with the sponsor ZIP at its default path and the shared `.local` directory linked. Replace `<commit>` with the full SHA of the improved revision. The baseline arms stay as they are.

```sh
PY=.local/scan-dev/objects/venv/bin/python
GPU=.local/scan-next/with-gpu

# Confirm both baseline seals (structure only)
python3 scripts/benchmark_scan_next.py verify --arm before
python3 scripts/benchmark_scan_next.py verify --arm before-repeat

# Leak check: must exit 0. Run it before the after arm and again before scoring.
python3 scripts/benchmark_scan_next.py leak-check --revision <commit>

# Run and seal the after arm (about 15 minutes on the M5 GPU)
unset NEMOTRON_BASE_URL NEMOTRON_API_KEY
$GPU $PY scripts/benchmark_scan_next.py run --arm after --revision <commit> > .local/evaluation/scan-next/after-run.log 2>&1
python3 scripts/benchmark_scan_next.py verify --arm after

# Score counts; only now are sponsor answers read
python3 scripts/benchmark_scan_next.py score --report docs/scan-next-results-<date>.json

# Fetch the annotations from the public archive on Zenodo (network), then measure localization
python3 scripts/benchmark_scan_next.py fetch-refs
uv run --no-project --python 3.12 --with svgpathtools==1.8.0 python scripts/benchmark_scan_next.py localize

# Replay bundle and clickable links to gained prompts
python3 scripts/benchmark_scan_next.py example --limit 3
```

The leak check fails if any frozen drawing name, in sponsor, upstream or URL-encoded form, or any frozen image digest appears in a tracked file of the candidate revision, in any blob of a commit between `b948d67` and the candidate, or in a file name, file, ZIP member name or symlink target under `.local/scan-next/openings` and `.local/scan-next/deferred`. A file byte-identical to a frozen PNG also fails it. The frozen manifest itself is allowed only at its exact digest. A resized or cropped copy of a fresh PNG would not be detected by this check. It writes its findings to `.local/evaluation/scan-next/leak-check-<commit>.json`. If the reader at `<commit>` reads a data file outside `scripts/`, pass it with `--source`; otherwise the snapshot will not contain it.

`score` writes `.local/evaluation/scan-next/paired-rows.json` and `summary.json`. In the paired rows `old` is the before arm and `new` is the after arm. `fetch-refs` refuses to run until both arms are sealed. It reuses the cached central directory of the public archive at `.local/scan-dev/grounding/central` when its digest matches, takes each original PNG from the sponsor ZIP when its CRC matches the upstream member, downloads `model.svg` and `F1_scaled.png` for each drawing with a door, window, toilet-bowl or sink prompt by HTTP range requests from `https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content`, and writes `.local/evaluation/scan-next/references/references.zip`. `localize` writes `grounding.json` and `localization.json`.

`example` writes `.local/evaluation/scan-next/scan-next-replay.json`, a replay bundle in the format of `scripts/export_scan_replay.py`, and prints its SHA-256 with links of the form `http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2F<drawing>.png&question=<question>` for up to three prompts the after arm gained, track prompts first. The library page reads only replay bundles registered in `scripts/scan_library.py` with their digest. To make a link open the sealed answer, copy the bundle to `public/data/finnish/scan-next-replay.json` and register it beside `REVISION_REPLAY_FILE` in a product commit. Without that change, start `python3 server.py` with the specialist Python at the after revision, open the link and choose **Run count**.
