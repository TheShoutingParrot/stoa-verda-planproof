# Planproof: Junction 2026 submission

**One line:** Ask a construction drawing how many, and see exactly where. Planproof counts windows, doors, rooms and storeys on the original drawing and marks every counted item, so the number can be checked instead of trusted.

**Challenges:** Stoa: Make Blueprints Talk · NVIDIA: Best Use of Nemotron

## What we built

Construction quantities are still counted by eye, sheet by sheet. Neither the result nor a vision model's answer shows which symbols were counted. Planproof answers count questions on the sponsor's drawings and links every answer to evidence on the original image.

- **A drawing library over the full sponsor release (9.8 GB):** 4,787 CubiCasa scans of Finnish floor plans, 1,040 Swiss plans with their CAD files, 533 IFC building models and 64,132 English questions.
- **Clickable evidence:** each count comes with one mark per counted item on the original drawing. A zero for a room question (saunas, WCs, balconies) comes with the rooms that were examined. Scan evidence is bound to the original image by its SHA-256.
- **Local readers first:**
  - Room-label OCR on the scan.
  - The CubiCasa5K floor-plan detector, used both for a room map (rooms, storeys, saunas, WCs, balconies) and for windows and doors.
  - Windows and doors are read a second time at a scale set by the drawing's own doors.
- **NVIDIA Nemotron 3.5 Super VL for the rest:** what the local readers cannot prove goes to Nemotron on NVIDIA's endpoint. Shower questions use Nemotron's reasoning pass with a guide to Finnish shower symbols. Every answer names the reader or model that produced it.
- **Swiss plans and IFC models:** room areas measured from the CAD outlines, and element counts linked to the original IFC records.

## Results

All local figures are offline, on 72 CubiCasa test drawings with 608 questions that were not used in any development round. An independent evaluator sealed the previous reader's answers before tuning started, then ran the new reader once plus an identical repeat and scored the comparison once, following a pre-registered protocol.

| | Previous reader | Planproof now |
|---|---:|---:|
| Exact answers | 189 of 608 | **325 of 608** |
| Wrong answers | 145 | 140 |
| Deferred | 274 | 143 |
| Exact among answered | 56.6% | 69.9% |

- **Exact answers:** +22.4 percentage points, 95% interval 18.7 to 26.1.
- **Repeat runs:** a repeat of each reader gave identical answers.
- **Marks checked against the original SVG annotations:**
  - Annotated windows found: 68.5% before, 76.2% now.
  - Annotated doors found: 85.6% before, 95.0% now.
  - 90% of window marks fall on a real window (92.3% before; the new reader also places more marks that match nothing).
- **On NVIDIA's endpoint, same 608 questions** (descriptive: run after the sealed scoring, not part of the protocol):
  - Nemotron alone: 247 exact.
  - Planproof's readers with Nemotron behind them: **405** exact, with 143 NVIDIA calls instead of 608.
  - Shower route: tuned on development drawings only, it raised held-out shower counts from 28 to 41 of 66 (paired sign test p = 0.04).

## NVIDIA Nemotron (Best Use of Nemotron)

- **Model:** NVIDIA Nemotron 3.5 Super VL on `integrate.api.nvidia.com`.
- **What it does:** it answers the count questions our local readers cannot prove, such as showers and bedrooms whose labels are unreadable, and returns a box for every item it counts. Those boxes are shown on the drawing like the local marks.
- **Why it matters:** the local readers answer what the drawing itself proves for free, and Nemotron covers the rest. Together they reach 405 of 608 exact, against 247 for Nemotron alone, with 143 NVIDIA calls instead of 608.
- **How we improved its outputs:** answers must parse as a count with one valid box per item, or they are deferred. For showers, a guide to Finnish shower symbols plus Nemotron's reasoning pass, chosen on development drawings and checked on held-out ones, raised exact counts from 28 to 41 of 66.

## Try it

```sh
python3 server.py        # with the sponsor ZIP at .local/evaluation/swiss-frontier/inputs/junction-dataset.zip
```

Open http://127.0.0.1:4179/library.html. The links in `demo/links.md` replay sealed answers without a model or key. For live counts, start the server with the detector's Python (`.local/scan-dev/objects/venv/bin/python server.py`); the detector setup is in `docs/scan-objects.md`. To send unproven questions to NVIDIA, set `NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1` and `NEMOTRON_API_KEY` in the server environment.

- Demo video: https://youtu.be/NZQnlgucLDw (1 min 43 s; also `planproof-demo.mp4`)
- Pitch deck: `planproof-deck.pdf` (12 slides)
- Evaluation write-up: `docs/scan-next-evaluation.md`; protocol: `docs/scan-next-protocol.md`

## Built with

Python standard library and browser JavaScript for the app. PyTorch with the CubiCasa5K model for the detector, macOS Vision and Tesseract for OCR, and NVIDIA Nemotron 3.5 Super VL on `integrate.api.nvidia.com`.

## Limits

- Window totals did not improve significantly (+1.4 points), although the window marks did.
- Shower questions, and the bedroom questions the label reader defers (20 of 40), still depend on the hosted model.
- The detector has only been measured on an Apple M5. It selects CUDA when an NVIDIA GPU is present, but we have not run it on Verda yet.
- The new reader takes about 1.7 times as long per drawing.

## Team

Manu Mäkinen · Victor Ocampo · Anni Tapionlinna · Touko Ursin
