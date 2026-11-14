# Local scan reader on 48 fresh CubiCasa test drawings

The comparison runs two local Planproof readers on the same 398 original English questions and 48 PNGs. The reference reader comes from commit `4d79ac0d2d62150f416f730ff5dbbf38486be208`. The revision reads the original scan through the same product entry point. Both run with a blank hosted endpoint and no credential. Each drawing has a stable SHA-256 identity. The independent freeze pinned four original implementation files and seven revised implementation files. The same verified upstream architecture and weight binary serve both arms. [Frozen inference manifest](scan-revision-inputs.json) · [Evaluation script](../scripts/benchmark_scan_revision.py)

## Observed results

The revised reader returned **167 exact counts on 398 prompts (41.96%)**, up from 156 (39.20%). It gained 15 exact answers and lost four. All four losses were window counts. The paired difference was **+2.76 percentage points**, with a drawing-clustered 95% bootstrap interval of +0.75 to +4.87. [Observed machine-readable results](scan-revision-results-2026-11-14.json)

| Released question | Prompts | Old exact | Revised exact | Old answered | Revised answered |
| --- | ---: | ---: | ---: | ---: | ---: |
| Doors | 35 | 16 | 18 | 35 | 35 |
| Windows | 48 | 20 | 23 | 48 | 48 |
| Toilet bowls | 48 | 38 | 38 | 48 | 48 |
| Sinks | 46 | 29 | 29 | 46 | 46 |
| Bedrooms | 37 | 19 | 20 | 23 | 24 |
| Other room types | 136 | 34 | 34 | 34 | 34 |
| Storeys | 48 | 0 | 5 | 0 | 5 |
| **Total** | **398** | **156** | **167** | **234** | **240** |

The six newly answered prompts comprised one bedroom count and five storey counts. All six matched the sponsor. The revised reader abstained on 158 prompts and returned 73 wrong counts. Conditional accuracy rose from 66.67% to 69.58%. Kitchens, bathrooms, saunas, separate WCs, balconies, sinks and toilet bowls had identical exact totals. The revised door and window counts gained nine exact answers and lost four. Mean absolute error on the 177 object counts fell from 1.254 to 1.028. The largest limitations remain window accuracy (23/48 exact) and floor-count coverage (5/48 answered).

## Drawings and questions

The sampler intersected Stoa’s question-bearing drawings with the authors’ official 400-image test split. It then excluded the previous 32-drawing experiment, the prior preview, hosted checkpoint, MLX model executions and inspected development images listed in the earlier manifest. Together these cover 489 distinct image paths. An earlier release-wide study had scored the legacy bedroom eligibility gate across the corpus. Its 35 actual local model executions were excluded here. The sponsor labels are public, and this is a newly withheld application-development subset within that release. The two developers used earlier drawings for development. The 48 selected files also have distinct byte hashes with no exact matches among the 489 exclusions. This checks file identity only. The original pretrained detector used the upstream train and validation partitions. [Prior exclusion manifest](scan-holdout-inputs.json) · [Original dataset and split archive](https://zenodo.org/records/2613548) · [Pretrained model](scan-objects.md)

There were 43 eligible high-quality drawings and 225 architectural drawings. Every colorful test drawing had already been excluded. The seeded sampler selected 24 per available style, then kept every released English prompt about doors, windows, sinks, toilet bowls, bedrooms, kitchens, bathrooms, saunas, separate WCs, balconies and floors. This gives 177 object questions, 173 room questions and 48 floor questions. The sponsor publishes different questions on different drawings. Equal weighting of the two available styles and the exclusion of showers limit any extrapolation to the full release.

Selection projected paths and question text from the release file. No target count enters selection or inference. A separate preparation stage staged the 48 original images. The run stage has no archive access and explicitly forbids hosted inference. Both arms are independently sealed, including every question, source image hash, response and software fingerprint, before the scorer can read sponsor counts. Source snapshots include transitive imports of product modules. The scorer requires exact integer equality and validates positive responses against the product count/evidence schema. A decision to defer to hosted inference becomes an offline abstention. Zero remains a numeric prediction. The sealed count records retain validated per-instance evidence. A zero has an empty instance list; any auxiliary OCR coverage marks used to justify a zero are outside these normalized records.

## Replay of the earlier 32 drawings

We also ran the frozen revision through the complete scan reader on the 96 questions used for the previous release. These drawings informed development of this revision. Against the previously shipped reader, the hybrid score on the original 77 comparable questions rose from 48 to 52 exact, with no previously correct answer lost. On all 92 questions for which the previous reader had usable service it rose from 56 to 62. The six gains were two windows, two bedrooms, one door and one storey. Two already incorrect window estimates moved farther from the expected count.

The updated reader handled 49 prompts locally. For the other 47 we verified the hosted request URL, HTTP method and body matched the recorded request and reused its observed response, including four rate-limit failures. This replay issued no new hosted calls. The earlier 96-question experiment and the new 398-question offline comparison have different inputs and denominators. [Earlier benchmark](scan-holdout.md)

## Reproduce

Set up the pinned detector and local dependencies using the model guide. The observed runtime uses the macOS Vision and Tesseract OCR engines. Obtain the original sponsor ZIP and extract `train.txt`, `val.txt` and `test.txt` from the official CubiCasa archive if regenerating the selection. The published frozen manifest already contains the inference inputs and source hashes. [Detector installation](scan-objects.md) · [Sponsor archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip)

```sh
python3 scripts/benchmark_scan_revision.py freeze --split-dir /path/to/cubicasa5k --archive /path/to/junction-dataset.zip
python3 scripts/benchmark_scan_revision.py prepare --archive /path/to/junction-dataset.zip
.local/scan-dev/objects/venv/bin/python scripts/benchmark_scan_revision.py run --arm old
.local/scan-dev/objects/venv/bin/python scripts/benchmark_scan_revision.py run --arm new
python3 scripts/benchmark_scan_revision.py score --archive /path/to/junction-dataset.zip
```

The two inference commands read staged PNGs only. Each stores outputs incrementally under `.local/evaluation/scan-revision/{old,new}/outputs/`. Interrupted work resumes only with matching source, runtime, weights and image identity. The old reader loads from Git. The new reader copies the checked-out product sources. Use `--revision <commit>` for a committed new revision. The output report records individual file digests, runtime and device. Both arm commands enforce the pre-registered aggregate digest of those files. Re-running the measurement can produce a different output seal because elapsed inference time is recorded per question. Scoring writes the full, question-by-question audit to `.local/evaluation/scan-revision/paired-rows.json` and the summary to `summary.json`.

Coverage is the fraction of all released prompts answered locally. Exact accuracy uses all released prompts in scope, including abstentions in the denominator. Conditional accuracy uses only answered prompts. Paired gains and losses track the same original question and drawing. The 95% interval for the accuracy difference uses 10,000 paired, within-style bootstrap samples of whole drawings, retaining the selected drawing’s complete prompt set each time. Count and box structure are evaluated here. The location check compares the same predictions against the original SVG annotations. [Object location results and drawing links](scan-revision-marks.md)
