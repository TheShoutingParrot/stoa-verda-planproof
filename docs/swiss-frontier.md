# Swiss Dwellings full-corpus evaluation

The sponsor publishes 37,584 Swiss questions on 1,040 drawing paths. Half are English, with 18,792 original prompts and the same number of translations. The full English denominator covers all question families on every Swiss sheet in the release. It includes the demo and previously examined sites. The fixed 1,080-row audit remains available as a [historical comparison](swiss-benchmark.md).

The [fresh split](swiss-frontier-split.json) was selected from filenames before opening source drawings, question values, or predictions for this evaluation. It contains 120 distinct sites, excluding 65 preview sites, the earlier 60 evaluated sites, the second demo site 1006 and the previously inspected site 3387. The manifest gives the selection seed and order. A model or system later tuned on the misses cannot treat this sample as untouched.

## First evaluation before full-corpus feedback

The deterministic drawing pipeline and its browser form returned a numeric answer for every released English Swiss question. Commit `3139ea8` is the previous version. Both versions saw the same sheet, prompt and public scoring tolerances. Fresh sites were scored without prior selection based on their answers. The full set includes previously seen examples.

| Swiss slice | Number of questions | Previous correct | Current correct | Current counts | Current areas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Historical 60 sites | 1,080 | 487 (45.09%) | 1,079 (99.91%) | 729 / 729 | 350 / 351 |
| Fresh 120 sites | 2,161 | 1,001 (46.32%) | 2,157 (99.81%) | 1,468 / 1,469 | 689 / 692 |
| All 1,040 drawings | 18,792 | 8,548 (45.49%) | 18,693 (99.47%) | 12,774 / 12,784 | 5,919 / 6,008 |

On the original 60, room counts by label and combined room area increased from 367/421 to 421/421. On that same sample, apartment D on site 886 measured 66.43 m² against the sponsor's 65.01 m². On the full release, 56 apartment areas, 33 whole-floor areas, seven washbasin counts and three bathtub counts missed. Named-room areas (2,076), room counts by label (6,365), area sums by label (1,017) and apartment counts (1,040) all passed. Each result validates scope using the displayed evidence against the structured source extraction. Expert-adjudicated symbol boxes were unavailable. Every question here supplies a drawing path. This benchmark measures taking off quantities on that sheet, without evaluating cross-document retrieval.

Across all 18,792, the new version kept all 8,548 previously correct, gained 10,145 and still missed 99. On the fresh 120 sites it kept all 1,001 previously correct, gained 1,156 and missed four. The frozen 60 gained 592 and lost none. For a model-independent comparison on the frozen 1,080, numerical score alone is 489 previous and 1,079 current, regardless of cited scope. Add `--numeric-original path/to/rows.jsonl` to the comparison command to export gold, raw numbers and passes in the frozen visual benchmark’s order.

The saved [paired results](swiss-frontier-results.json) record per-family failures and abstentions, prior/candidate hashes, numeric-only results, changed-correctness counts, and the released inventory. To compare two cached runs, use `python3 scripts/compare_swiss_frontier.py PREVIOUS_RUN_DIR CURRENT_RUN_DIR --output paired.json`. For the historical product use `--revision 3139ea8` when running the full benchmark.

## Recheck after inspecting the first results

The first full-corpus result exposed 99 misses. After the team inspected those failures and revised the handling of plumbing symbols, guards and balconies, the same inputs yielded **18,789 / 18,792 (99.98%)**, including **12,784 / 12,784** exact counts and **6,005 / 6,008** areas. The 60-site set reached **1,080 / 1,080** and the previously inspected 120-site sample reached **2,161 / 2,161**. The independent first evaluation for those 120 sites remains 2,157 / 2,161. Treat the later result as a regression check on known data.

Three area questions still fell outside tolerance. On site 333, apartments D and E returned 83.78 and 75.48 m² against 81.74 and 73.52 m²; the floor returned 528.74 against 517.18 m². The cumulative full-corpus gain over `3139ea8` was 10,241 strict answers, with none of the original 8,548 correct answers lost. [Recheck results and source fingerprints](swiss-frontier-recheck.json).

## Running the evaluation

Use Python 3.10+, Node 18+, and the sponsor's full 9.77 GB ZIP. Keep the archive and generated files outside Git.

```sh
mkdir -p .local/evaluation/swiss-frontier/inputs
curl -fL --retry 3 -C - -o .local/evaluation/swiss-frontier/inputs/junction-dataset.zip \
  https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip
python3 scripts/benchmark_swiss_frontier.py
```

Pass `--archive PATH` to reuse an existing ZIP, `--split original60` to run only the 1,080 questions, or `--split fresh120` to run the newly frozen split. `--jobs` and `--batch` control concurrency and sheets per process. A normal full run scores once then slices the same predictions. The drawing files, versioned source snapshots, cached geometry, and per-row `rows.jsonl.gz` are under `.local/evaluation/swiss-frontier/`. The command prints the exact result location. It validates the sponsor question file's frozen SHA-256, source member CRC, the original paired rows' SHA-256, and the fresh split's deterministic selection.

The runner snapshots the working frontend, extractor and its local Swiss modules. Extraction sees the original same-stem DXF accompanying each labelled PDF. The JS harness submits each original English question through the unmodified form listener and reads the rendered number, semantic scope, metric, and IDs on the interactive evidence rows. It supplies held-out assets through the in-memory catalog; the standard website only offers its bundled drawings. The prediction process receives drawing geometry and question text. The separate scorer joins expected numbers, labels and IDs after the predictions finish.

A strict pass requires the correct target scope and metric, a numeric match (counts exact, areas within 2% of sponsor gold), and linked evidence. The scorer checks that every displayed ID belongs to a distinct source entity of the selected type, the evidence set is complete relative to the extracted sheet, the displayed count equals its size, and displayed areas reproduce the sum of the cited room polygons to the UI's rounding precision. Printed scope and marks are not independently human-adjudicated on 1,040 sheets. A matching number with the wrong scope is reported separately. An extraction failure counts against every question on that sheet; a form refusal or unmeasurable dash is an abstention.

## Other sources

The 127,044 released rows have no explicit language field. Source-specific question prefixes identify 64,132 English rows. The Finnish CubiCasa plans contribute 42,757 English count questions, Swiss Dwellings 18,792, IFC Models 1,699, IFC-Bench 820 free-form text questions, and Opening Design 64. Finna, HABS, Wikimedia and Europeana have drawings without released QA rows. The Swiss score applies to its 18,792 English prompts. Scans, arbitrary DWGs, IFC models, other languages and paraphrases need their own evaluation.

[Full sponsor archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip) · [Swiss source, credits and licence](../public/data/SWISS-SOURCE.md)
