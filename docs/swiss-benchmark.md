# Swiss room question benchmark

The paired comparison uses 1,080 English sponsor questions on the same 60 Swiss Dwellings sites for both code revisions. The baseline is commit `32b2941ea5108140a81f44ea484d40b22f4c6b78`. The revised result is identified by the SHA-256 hashes of its frontend and extractor in the results JSON.

The later [full-corpus and fresh-site evaluation](swiss-frontier.md) covers the expanded takeoff engine, with results for all 18,792 released English Swiss questions.

## Paired results

Correct scope and numeric value improved from **360/1,080 (33.3%)** to **487/1,080 (45.1%)**, a change of 127 questions. The sample and the 2% area tolerance are identical in both columns.

| Question family | Questions | Baseline correct intent | Revised correct intent | Revised numeric matches |
| --- | ---: | ---: | ---: | ---: |
| Room count by label | 361 | 308 | 314 | 316 |
| Combined area by label | 60 | 52 | 53 | 53 |
| Area of a named room | 120 | 0 | 120 | 120 |
| Doors, windows and fixture counts | 308 | 0 | 0 | 0 |
| Apartment count | 60 | 0 | 0 | 0 |
| Apartment area | 111 | 0 | 0 | 0 |
| Indoor floor area | 60 | 0 | 0 | 0 |

Of all 1,080 questions, the baseline displayed 478 numeric answers, with 367 in tolerance. The revised app displayed 499, with 489 in tolerance. The earlier offline audit counted 479 baseline parser returns. One was an empty area selection shown as a dash in the page, so this form measurement counts 478 displayed answers. The 360 intent-correct and 367 numeric baseline matches reproduce the frozen audit exactly.

On the original two supported families, accuracy changed from 360/421 to 367/421. Including the newly supported named-room lookup, the revised supported-family score is 487/541. The fixed all-question denominator above avoids conflating wider scope with accuracy.

127 questions changed from a miss or refusal to a correct answer, 360 stayed correct, 0 regressed, and 593 remained wrong or unanswered. 124 displayed numeric values changed, including moves to or from abstention.

On site 777, room 4.05, the baseline returned **49.63 m²** for the full corridor group. The revised answer is **7.25 m²** with room 4.05 selected, matching the published 7.25 m².

| Local timing (ms), p50 / p95 | Baseline | Revised |
| --- | ---: | ---: |
| DXF extraction, per sheet | 6.203 / 19.528 | 7.474 / 25.603 |
| Submit handler and in-memory DOM update, per question | 0.033 / 0.643 | 0.108 / 1.445 |

One sequential baseline/revised run on an Apple M5 (3.14.6 Python, v24.16.0 Node). Hardware load and the ratio of refusals to rendered results affect timing. No network, geometry download, browser paint or model inference is included in these timings. [Machine-readable summary](swiss-benchmark-results.json).

## Reproduce

From a full checkout with the baseline commit, run:

```sh
python3 scripts/benchmark_swiss.py
```

Requirements are Python 3.10+, Node.js 18+, Git, curl and HTTPS access to the sponsor dataset on the first run. No Python or Node packages are needed. The runner range-reads the ZIP and caches the selected DXFs and original question file under `.local/evaluation/swiss-paired/inputs/`. It checks their hashes on subsequent runs. To use another cache, pass `--cache path`. Per-question answers, the rendered value, evidence room IDs and elapsed times are written to `.local/evaluation/swiss-paired/pairs.json`. The adjacent `summary.json` contains aggregate results and code fingerprints.

## Sampling and scoring

The full sponsor archive contains 1,040 Swiss DXFs. We excluded all 65 preview sites, sorted the remaining 975 stems by SHA-256 of `planproof-heldout-2026-11-13-v1|<stem>` and kept the first 60. There is one sheet per selected site. The [input manifest](swiss-benchmark-inputs.json) pins every DXF and the ordered 1,080-question data to their original checksums. These were held out of preview development. This comparison reuses the exact sample that identified the lookup and basement-label problems. It measures the repair on those known cases. The final apostrophe-handling change was also tested against a known miss on this same sample. The separately bundled example, site 1006 / building 2088 / floor 9498, is absent from all 60 test sites; it is a demonstration and contributes no questions to these totals. A new untouched sample is needed for an independent estimate of generalization.

Each revision extracts the DXFs with its own `scripts/extract_rooms.py`. A Node harness runs the complete unmodified `public/app.js` entry point and form submit listener, including selection, evidence generation, and numerical formatting. The harness supplies the extracted sheets through the loader in memory so the same page can process the 60 test assets; it does not add those assets to the shipped site. The document objects implement the calls the renderer needs. This measures application logic and displayed answers, without browser layout, GPU rendering, or an upload workflow. Gold values and expected labels/IDs are joined after inference. The default calculation uses room outlines.

An exact count or a displayed area within 2% of gold passes the numerical check. Intent additionally requires the requested metric and room label; a direct room lookup must select the requested room ID and display one piece of evidence for that ID. A message that keeps an older result on screen counts as a refusal. A dash counts as no numeric answer. Neither receives credit. Numerically matching a total for a different room scope earns numerical credit only. The Swiss comparison exercises deterministic extraction and query handling without model calls.

The 60-site source contains a further 1,080 translations (743 German, 302 French and 35 Italian). Those translations and Finnish scans are outside these scores. All examined drawings are Swiss Dwellings CAD geometry. Site-level splits do not establish results on other source collections, images, arbitrary CAD standards or unscripted question phrasing.

Data and attribution: [Stoa full challenge archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip), [Swiss Dwellings v3.0.0](https://doi.org/10.5281/zenodo.7788422), [source credits and CC BY 4.0 notice](../public/data/SWISS-SOURCE.md). The benchmark writes raw sponsor files and individual question text only to ignored local storage.
