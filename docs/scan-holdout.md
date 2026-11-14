# Blind scan comparison

The frozen comparison has 96 English counting questions on 32 original CubiCasa5K images. Each arm gets the same three sponsor prompts per image. The drawings belong to the authors’ official 400-image test split, disjoint from their 4,200 training and 400 validation images. The selector uses filenames, prompt availability and a fixed seed. It opens no SVG annotations and uses no gold values to select drawings or questions. [Frozen inputs](scan-holdout-inputs.json) · [Official dataset](https://zenodo.org/records/2613548) · [Authors’ model and evaluation](https://github.com/CubiCasa/CubiCasa5k)

The selector excludes 186 drawings previously sent to hosted inference, 241 public preview drawings, 35 drawings processed by the earlier local MLX model, and 12 reviewed, bundled or interactive drawing paths. These groups overlap. Earlier deterministic bedroom-gate screening covered all released bedroom questions. Eight selected bedrooms reuse their original image-hash-bound gate output for the prior system. The remaining 88 baseline questions use the original NVIDIA client from Git revision `d9a440dd5bec10c1ae2828de6e0104f3034390e8`.

After exclusions, the sponsor and upstream test sets had one eligible colorful, 58 high-quality, and 241 high-quality architectural drawings. The frozen sample contains one, 15 and 16 respectively. A hash ordering selects images within each style. Prompt assignment prioritizes each drawing's least-represented available categories, with seeded tie-breaking. Each of 12 categories contributes seven to nine prompts. The colorful stratum has one observation, and the sample does not estimate the score on the whole release.

## Observed paired result

On the 77 questions with usable service in both arms, the prior system matched 36 sponsor counts and the candidate matched 48. Fourteen questions became correct and two ceased to be correct. The gain was 15.58 percentage points, with a descriptive drawing-cluster bootstrap interval of 7.25 to 24.05 points. The candidate returned 65 numeric answers, up from 43. Precision among those answers fell from 83.72% to 73.85%.

| Across all 96 prompts | Correct | Wrong | Model or evidence unknown | Service unavailable |
|---|---:|---:|---:|---:|
| Original | 36 | 7 | 34 | 19 |
| Candidate | 56 | 24 | 12 | 4 |

The baseline attempted all questions. HTTP 429 persisted for 19 original hosted questions after a bounded recovery pass. Four used the identical original route in the candidate and share that final service failure. The 77-prompt paired comparison excludes all 19 rows with an outage in either arm. Of 96 candidate records, 35 used the local object detector, 11 used local room-label recognition, nine used fresh structured hosted inference, and 41 used the unchanged hosted route and its observed result. [Dated numerical results and prediction hashes](scan-holdout-results-2026-11-14.json)

The original drawings provide an independent check on the overlay. Across 24 comparable questions about doors, windows, toilet bowls and sinks, the old reader matched 8 of 111 annotated objects and the new reader matched 91. In 13 cases the new reader located every object without an extra mark, up from two. [Marked-object audit and all 96 individual results](scan-review.md)

## Reproduction

Download the official split files `cubicasa5k/train.txt`, `val.txt` and `test.txt` from the upstream ZIP linked above. Their SHA-256 digests are in the manifest. Place the sponsor release under the path described in [the full English evaluation](full-english.md), or supply `--archive`. The following commands use the frozen exclusions and stage only the public prompts and unmodified input PNGs.

```sh
python3 scripts/benchmark_scan_holdout.py freeze --split-dir /path/to/cubicasa5k --exclusions docs/scan-holdout-inputs.json
python3 scripts/benchmark_scan_holdout.py inputs
```

Inference writes one atomic record per prompt and skips completed IDs on resume. Each arm is sealed with a SHA-256 digest over all 96 predictions in manifest order before scoring opens the answers. For an identical legacy hosted request, the candidate may reuse the previously sealed baseline prediction; the harness checks its answer, evidence and timestamp. A fresh model response can differ on replay.

```sh
hsec exec --only NEMOTRON_API_KEY -- python3 scripts/benchmark_scan_holdout.py run --arm baseline --run --workers 4 --rpm 12
```

A candidate run requires an explicit frozen source fingerprint. Use the same Python interpreter, model weight file and upstream checkout for the fingerprint and execution. The hash includes the scan modules, pinned weights, upstream Git revision and upstream source file hashes and installed inference package versions. The evaluation environment uses Python in `.local/scan-dev/objects/venv`, weights `.local/scan-dev/objects/model_best_val_loss_var.pkl`, and the upstream checkout at `.local/scan-dev/objects/CubiCasa5k`. The `local` action runs the frozen candidate with no hosted credentials and checkpoints every verified local response. After that, `run --arm candidate --direct-only` can evaluate changed hosted requests while the baseline is still running; the final replay command seals the candidate after the baseline finishes. A prior outage carries over only when local readers decline and the dispatcher's hosted request is unchanged.

```sh
scan_python=.local/scan-dev/objects/venv/bin/python
scan_weights=.local/scan-dev/objects/model_best_val_loss_var.pkl
scan_source=.local/scan-dev/objects/CubiCasa5k
scan_hash=$("$scan_python" scripts/benchmark_scan_holdout.py candidate-id --artifact "$scan_weights" --external-repo "$scan_source")
"$scan_python" scripts/benchmark_scan_holdout.py local --freeze-id "$scan_hash" --artifact "$scan_weights" --external-repo "$scan_source"
hsec exec --only NEMOTRON_API_KEY -- "$scan_python" scripts/benchmark_scan_holdout.py run --arm candidate --direct-only --run --freeze-id "$scan_hash" --artifact "$scan_weights" --external-repo "$scan_source"
"$scan_python" scripts/benchmark_scan_holdout.py run --arm candidate --replay-only --freeze-id "$scan_hash" --artifact "$scan_weights" --external-repo "$scan_source"
python3 scripts/benchmark_scan_holdout.py score
```

The scorer checks each answer against the released integer, verifies that its evidence meets the product's count-and-box contract and reports paired gains and losses. Its 95% descriptive bootstrap interval resamples whole drawings to preserve the three within-drawing prompts. Sponsor counts alone cannot verify the meaning or position of a proposed box.
