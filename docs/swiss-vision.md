# GPT-6 Astra on Swiss floor-plan images

The vision benchmark uses every one of the 1,080 original English sponsor questions on the [frozen 60-site sample](swiss-benchmark-inputs.json). Each call attached the public Swiss Dwellings PNG at its original resolution, 2480 × 1753 pixels or the portrait equivalent. GPT-6 Astra received all questions for that sheet, in release order. The prompt asked for one numerical answer per question and allowed `null` for insufficient evidence. It contained no reference answers, extracted geometry, historical results or examples.

Each sheet ran in a separate ephemeral Codex session at medium reasoning effort in a temporary directory. The CLI used its existing ChatGPT sign-in. The runner rejects a response if the event stream records a tool call, the number of answers differs from the number of questions, or the values fall outside the numerical schema. It caches successful responses with image and prompt hashes. The program joins predictions with the reference answers after inference. [OpenAI Docs on non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode).

The paired comparison grades numerical answers identically for both systems. Counts require an exact match and areas must be within 2% of the sponsor value. A refusal receives no credit. Planproof has access to the paired vector DXF and exposes the contributing geometry in the interface. The model sees the published raster image and returns numbers. This measures those two input workflows. It does not isolate a model effect from the difference in available drawing information. No human localization score or per-call monetary charge was available for the vision run.

## Results

All 60 model calls completed. Planproof returned 1,080 correct numerical answers. GPT-6 Astra returned 854 correct answers (79.1%), 185 incorrect answers and 41 abstentions. Both systems scored on all 1,080 questions. The original 60-site set informed the Planproof fixes.

| Quantity | Questions | Planproof with DXF | GPT-6 Astra with PNG |
| --- | ---: | ---: | ---: |
| Rooms counted by label | 361 | 361 | 359 |
| Combined room area by label | 60 | 60 | 48 |
| Single numbered room area | 120 | 120 | 83 |
| Door, window and fixture counts | 308 | 308 | 200 |
| Apartment counts | 60 | 60 | 59 |
| Apartment areas | 111 | 111 | 75 |
| Indoor floor areas | 60 | 60 | 30 |
| **All English questions on these sheets** | **1,080** | **1,080** | **854** |

The model answered 1,039 questions. Median elapsed time per sheet was 49.4 seconds, including CLI startup and the model response. Across the 60 scored calls the CLI reported 1,196,163 input tokens, including 743,680 cached input tokens, and 85,422 output tokens, including 81,859 reasoning tokens. The counts include the Codex harness. Planproof made zero model calls for these sheets. The complete [vision answer vectors and per-sheet timings](swiss-vision-results.json) and [CAD results](swiss-frontier-recheck.json) are available for inspection.

## Reproduce

From a full checkout, use a signed-in Codex CLI with access to `gpt-6-astra`, Python 3.10+, and curl. Run `python3 scripts/benchmark_vision.py --jobs 3` to download the frozen questions and PNGs, run the model and score the responses. Pass `--archive /path/to/junction-dataset.zip` to read local inputs. An interrupted run can resume from its cache. The `--published-results PATH` option writes the full answer vectors, image and prompt hashes, timing and usage for independent verification.

[Dataset attribution](../public/data/SWISS-SOURCE.md) · [Full Swiss CAD benchmark](swiss-frontier.md)
