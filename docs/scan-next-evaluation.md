# Local scan reader on 72 held-out CubiCasa test drawings

The previous local reader (commit `b948d67`) and the current one (commit `cbf542b`) answered the same 608 English count questions on the same 72 drawings. Both ran offline, with no hosted model. The drawings come from the official CubiCasa test split. None was inspected or used in any development round. An independent evaluator froze the drawings and sealed the previous reader's answers before any tuning started. It then ran the current reader once and scored both once. [Pre-registered protocol](scan-next-protocol.md) · [Machine-readable result](scan-next-results-2026-11-15.json) · [Frozen inputs](scan-next-inputs.json)

## Result

| Reader | Exact | Wrong | Deferred | Answered | Exact among answered |
|---|---:|---:|---:|---:|---:|
| Previous (`b948d67`) | 189 | 145 | 274 | 54.9% | 56.6% |
| Current (`cbf542b`) | **325** | **140** | **143** | 76.5% | **69.9%** |

Exact answers rose from 31.1% to 53.5% of all 608 questions, by **+22.4 percentage points**. The 95% interval, from resampling whole drawings within each drawing style, runs from +18.7 to +26.1 points. The reader gained 145 exact answers and lost 9. It newly answered 131 questions that it had deferred before, and 127 of those answers were exact. The mean absolute error on questions both readers answered fell from 1.27 to 0.99.

The questions cover 12 families, including showers, which no local reader answers. Over the 11 families of the earlier 48-drawing comparison, with both drawing styles weighted equally, exact accuracy rose from 41.8% to 67.6%. That figure is the one to compare with earlier results. Architectural drawings make up 84% of this cohort, against 48% of the earlier one.

## By question family

| Family | Questions | Previous exact / wrong / deferred | Current exact / wrong / deferred | Change, points (95% interval) |
|---|---:|---:|---:|---:|
| Storeys | 72 | 13 / 0 / 59 | 61 / 1 / 10 | +66.7 (55.6 to 77.8) |
| Saunas | 42 | 3 / 1 / 38 | 34 / 1 / 7 | +73.8 (59.5 to 85.7) |
| Kitchens | 47 | 9 / 2 / 36 | 37 / 4 / 6 | +59.6 (46.8 to 72.3) |
| Separate WC rooms | 30 | 0 / 4 / 26 | 12 / 4 / 14 | +40.0 (23.3 to 56.7) |
| Bathrooms | 26 | 8 / 1 / 17 | 13 / 1 / 12 | +19.2 (3.8 to 34.6) |
| Balconies | 18 | 6 / 0 / 12 | 9 / 1 / 8 | +16.7 (0.0 to 33.3) |
| Doors | 51 | 21 / 30 / 0 | 29 / 22 / 0 | +15.7 (3.9 to 27.5) |
| Windows | 72 | 29 / 43 / 0 | 30 / 42 / 0 | +1.4 (−8.3 to 12.5) |
| Bedrooms | 40 | 14 / 6 / 20 | 14 / 6 / 20 | 0 |
| Toilet bowls | 72 | 48 / 24 / 0 | 48 / 24 / 0 | 0 |
| Sinks | 72 | 38 / 34 / 0 | 38 / 34 / 0 | 0 |
| Showers | 66 | 0 / 0 / 66 | 0 / 0 / 66 | 0 |

Most of the gain comes from the new room-map reader, which answers room and storey questions the label reader had to defer. On the rooms, storeys and showers it covers, exact accuracy rose by 37.2 points (32.2 to 42.3). Among the questions it newly answered, 127 of 131 were exact. [Room-map reader](scan-layout.md)

The second reading of windows and doors gained 10 exact door totals and lost 2. Window totals gained 8 and lost 7. Across doors and windows together the change is +7.3 points, with an interval from −0.9 to +16.2. A gain in exact window totals is therefore not established on these drawings. The marks did improve, as the next section shows. [Window and door reader](scan-objects.md)

Bedroom, toilet bowl and sink answers did not change. Toilet bowls and sinks were a control: the current reader reads them exactly as before.

## Where the marks fall

Each window, door, toilet bowl and sink mark was compared with the drawing's original CubiCasa SVG annotation. A mark matches when it overlaps one annotated object at an intersection-over-union of 0.25 or more. A question is fully grounded when every annotated object has its own mark and no mark is left over.

| Object | Annotated | Previous located | Current located | Previous marks matching | Current marks matching | Fully grounded questions |
|---|---:|---:|---:|---:|---:|---:|
| Windows | 740 | 507 (68.5%) | 564 (76.2%) | 507 / 549 (92.3%) | 564 / 625 (90.2%) | 26 → 25 of 72 |
| Doors | 499 | 427 (85.6%) | 474 (95.0%) | 427 / 458 (93.2%) | 474 / 515 (92.0%) | 16 → 25 of 51 |
| Toilet bowls | 111 | 83 | 83 | 83 / 95 | 83 / 95 | 47 of 72 |
| Sinks | 201 | 135 | 135 | 135 / 165 | 135 / 165 | 34 of 72 |

The current reader finds 57 more windows and 47 more doors. It also places more marks that match no annotation, so the share of matching marks fell slightly.

## Regressions

Nine answers that were exact are now wrong. All nine are window or door totals off by one or two: windows on architectural drawings 1701, 1914, 20003, 6716, 7606, 7715 and 8571, and doors on high-quality drawing 488 and architectural drawing 8726. Four previously deferred questions now have wrong answers, all from the room-map reader: storeys on architectural drawing 1116 (3 for 2), kitchens on architectural drawings 1284 (1 for 2) and 7705 (1 for 0), and balconies on architectural drawing 20028 (0 for 1).

## How the run was controlled

The previous reader's answers were sealed twice before tuning started, and both runs agreed on all 608 answers. Right before the current reader ran, a third run of the previous reader served as a control under the same machine conditions. It also agreed on all 608 answers. The current reader was then run twice, and both runs agreed on every answer, status, evidence list and method.

The OCR calls have time limits, and a time-out can silently cost answers. Every time-out was logged, and a run with any time-out would have been set aside unseen and repeated. None occurred. No reader error or invalid report occurred.

An earlier automated bedroom check, on 13 November, had opened 40 of these 72 drawings. The result holds on both parts: +22.4 points (18.3 to 26.7) on those 40 drawings and +22.2 points (15.4 to 29.1) on the other 32.

On the same Apple M5, the current reader took 9.4 s per drawing to answer all its questions, against 5.6 s for the previous reader run back to back. The machine was somewhat busier during the current reader's run.

## With NVIDIA Nemotron behind the local readers

With a hosted endpoint configured, the product sends every question that no local reader can verify to NVIDIA's Nemotron 3.5 Super VL. The 608 questions were sent through that same hosted route to NVIDIA's endpoint (`integrate.api.nvidia.com`) after the sealed scoring. The table combines those hosted answers with the sealed local answers, exactly as the product would. This comparison was added after the protocol was fixed, so it is descriptive. No hosted answer or setting was tuned on these drawings. [Result file](scan-next-nvidia-hybrid-2026-11-15.json)

| Configuration | Exact | Wrong | Deferred | Calls to NVIDIA |
|---|---:|---:|---:|---:|
| Nemotron alone | 247 | 231 | 130 | 608 |
| Previous local readers, then Nemotron | 336 | 208 | 64 | 274 |
| Current local readers, then Nemotron | **392** | **186** | 30 | **143** |

With the current readers in front, the hosted product gets 56 more exact answers and 22 fewer wrong ones, with about half as many calls to NVIDIA. Nemotron still decides every shower question, bedrooms the label reader defers, and what remains of the room questions. On those routes it got showers right 28 times out of 66.

### Showers on NVIDIA's endpoint

Showers were the largest family left to Nemotron and its weakest one, so the hosted route for shower and bathtub questions was improved on NVIDIA's endpoint. The new route describes how Finnish plans draw showers and bathtubs, switches on Nemotron's reasoning and raises the output budget to 16,384 tokens (`scripts/scan_reader.py`, `SHOWER_INSTRUCTIONS`). Other questions keep the previous hosted route.

The change was chosen on 45 development drawings and then frozen. It was confirmed once on 90 other development drawings, and then run once on the 66 shower questions of the 72 held-out drawings. None of these drawings was used to choose it. [Result file](scan-next-nvidia-showers-2026-11-15.json)

| Shower and bathtub questions | Previous hosted route: exact / wrong / unanswered | New route: exact / wrong / unanswered | Gained / lost |
|---|---:|---:|---:|
| 45 tuning drawings | 24 / 16 / 5 | 33 / 12 / 0 | 13 / 4 |
| 90 confirmation drawings | 50 / 34 / 6 | 61 / 28 / 1 | 21 / 10 |
| 66 held-out questions | 28 / 35 / 3 | **41 / 24 / 1** | 24 / 11 |

On the held-out questions a paired sign test gives p = 0.04 (0.07 on the confirmation drawings). With the current local readers and this route, the product answers **405 of 608** questions exactly, with 175 wrong, 28 deferred and 143 calls to NVIDIA. The reasoning pass costs about 5,500 output tokens per shower question, against about 20 before, and takes tens of seconds instead of a few.

The figure still trails a constant answer of one shower, which would be right on 69 of the 90 confirmation drawings, because most Finnish flats have exactly one. The route answers from what is drawn and marks each shower it counts, so a plan with a bathtub, two bathrooms or none is not forced to one.

## Clickable examples

Start `python3 server.py` with the sponsor ZIP at its default path. The viewer replays the sealed answers of the current reader without a model or key. [More demo links](../demo/links.md)

- [Windows on architectural drawing 6549](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-6549.png&question=How+many+windows+are+shown+on+this+floor+plan%3F): 18 marks for 18 windows, up from 15.
- [Storeys on architectural drawing 9796](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9796.png&question=How+many+floors+%28storeys%29+does+this+floor+plan+show%3F): two floor panels, previously deferred.
- [Separate WC rooms on architectural drawing 875](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-875.png&question=How+many+separate+WC+rooms+%28toilet+rooms+marked+WC%29+are+on+this+floor+plan%3F): an answered zero that marks the one wet room examined.

## Limits

- The window count gain is not significant on these drawings, and nine of the thirteen new errors are window or door totals.
- Bedroom questions the label reader defers and all shower questions still need the hosted model. Shower counts on NVIDIA's endpoint are right 62% of the time.
- No NVIDIA GPU was available, so the local detector has only been measured on an Apple M5. It selects CUDA when present.
- The room-map reader needs the optional detector and a completed macOS Vision pass. Without either it declines.
- The current reader is about 1.7 times slower per drawing.
- Composition matters: 60 of the 72 drawings are architectural and none is colorful, because every colorful test drawing had been used before.
