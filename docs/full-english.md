# Planproof on every released English question

Planproof answered **18,801 of 64,132 questions correctly (29.32%)** on the sponsor's 9.77 GB archive. It returned 18,807 answers, of which 99.97% were correct. The table keeps every released English question in its source denominator. [Machine-readable results](full-english-results.json)

| Source | Questions | Correct | Wrong | Abstained | Service unavailable | Unsupported document | Correct / all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Swiss Dwellings | 18,792 | 18,789 | 3 | 0 | 0 | 0 | 99.98% |
| CubiCasa5K | 42,757 | 12 | 3 | 2,945 | 39,797 | 0 | 0.03% |
| IFC Models | 1,699 | 0 | 0 | 0 | 0 | 1,699 | 0.00% |
| IFC-Bench | 820 | 0 | 0 | 0 | 0 | 820 | 0.00% |
| Opening Design | 64 | 0 | 0 | 0 | 0 | 64 | 0.00% |
| **All sources** | 64,132 | 18,801 | 6 | 2,945 | 39,797 | 2,583 | 29.32% |

The local Finnish bedroom reader returned 15 counts across 2,960 drawings. It matched the sponsor on 12. It ran full-sheet Nemotron inference on 35 images. For example, it correctly counted three bedrooms on `high_quality-12564.png` and returned two against four on `high_quality_architectural-7084.png`.

## What ran

The release contains 127,044 question rows. It has no language column. The source-specific question openings identify 64,132 English prompts on 5,939 distinct drawing paths. The join key is the full drawing path and original prompt. Counts require an exact match. Areas, lengths and volumes allow 2% relative error. The 836 free-form questions all reached an unsupported document reader. Finna, HABS, Europeana and Wikimedia have files in the archive and zero released questions. [Sponsor archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip)

- **Swiss Dwellings.** The runner loaded each labelled PDF's matching DXF and submitted the English prompt through the application's quantity form. A pass also required the right scope and links to the contributing source elements. All 12,784 counts were exact and 6,005 of 6,008 areas were within tolerance. The three misses were two apartments and their floor on site 333. This is a rerun on a release previously used to improve the Swiss extractor. [Swiss evaluation history](swiss-frontier.md)
- **CubiCasa5K bedrooms.** The existing local reader recognizes Finnish bedroom labels and uses Tesseract word boxes and green apartment outlines to locate them. We applied that operation to every English bedroom question. We skipped model generation only when the pixels or Tesseract output proved the reader would abstain for every possible transcript. All other eligible sheets went through the pinned 8-bit Nemotron Parse v1.2 model with the original whole-sheet prompt and decoding settings. The numeric comparison uses the sponsor's exact bedroom count. The sponsor provides no per-question bedroom-box adjudication. The reader needs a positive label to answer, so it cannot return the correct zero on 516 bedroom questions. [Reader](../scripts/local_parse.py) · [Batch evaluation](../scripts/benchmark_cubicasa.py)
- **Other CubiCasa5K counts.** The remaining 39,797 prompts cover windows, doors, floors, fixtures and other room types. The shipped counting CLI accepted each original PNG, then returned an unavailable status because its hosted endpoint and credential were unset. This measures the installed prototype's coverage. Model accuracy on those prompts remains unmeasured. [Hosted reader](../scripts/nemotron.py)
- **IFC Models, IFC-Bench and Opening Design.** The drawing readers returned no prediction on these 2,583 questions. IFC Models has 1,347 questions on PDF sheets and 352 on raw IFC files. IFC-Bench has 820 free-form questions on 25 IFC models. Opening Design has 64 questions on three PDF sheets. None of the labelled documents has a matching DXF compatible with the Swiss extractor. The scan reader accepts PNG or JPEG. [Document checks](../scripts/benchmark_non_swiss_cad.py)

## Reproduce

Evaluate product revision `de11ebd4113798b2564a5b07e98d9185dc16078c` with the benchmark scripts alongside this report. The archive is 9,768,952,082 bytes. Its SHA-256 is `506dddc7537d992bc6797c9617e9b747c754d28406f181f2b23887b01a231692`. Put it at `.local/evaluation/swiss-frontier/inputs/junction-dataset.zip`. Use Python, Node and the pinned Apple Silicon MLX environment with Tesseract and a local copy of the weights. The hosted step below reproduces the endpoint configuration at evaluation time. [Model setup and checkpoint](../public/data/FINNISH-SOURCE.md)

```sh
archive=.local/evaluation/swiss-frontier/inputs/junction-dataset.zip
work=.local/evaluation/full-english
python3 scripts/benchmark_swiss_frontier.py --archive "$archive" --work "$work/swiss" --revision de11ebd
python3 scripts/benchmark_non_swiss_cad.py --archive "$archive" --out "$work/non-swiss-cad"
python3 scripts/benchmark_full_english.py hosted
.local/parse-venv/bin/python scripts/benchmark_cubicasa.py --stage gate
.local/parse-venv/bin/python scripts/benchmark_cubicasa.py --stage model --weights "$NEMOTRON_PARSE_CHECKPOINT"
.local/parse-venv/bin/python scripts/benchmark_cubicasa.py --stage report
python3 scripts/benchmark_full_english.py score
```

Set `NEMOTRON_PARSE_CHECKPOINT` to the pinned local MLX weights directory before the model step. Each Finnish stage can resume from completed images. The scorer checks the released questions, drawing hashes for scan predictions, product fingerprints, exact row coverage and numeric scores. It writes `rows.jsonl.gz` and `summary.json` under the work directory. The compressed file gives each question's original path and text, gold, prediction, status and route. Answered questions include the evidence that the reader produced.

With access to the hosted image model, a separate pass can replace the service-unavailable rows. Configure the base and model in the environment, keep the credential in the vault, and start with one image. The full run resumes the same checkpoint. Set `--rpm` and `--workers` for the provider's limits.

```sh
hsec exec --only NEMOTRON_API_KEY -- python3 scripts/benchmark_hosted_counts.py --run --limit 1 --timeout 300
hsec exec --only NEMOTRON_API_KEY -- python3 scripts/benchmark_hosted_counts.py --run --timeout 300
python3 scripts/benchmark_full_english.py score --hosted-rows .local/evaluation/hosted-cubicasa/hosted-rows.jsonl.gz
```
