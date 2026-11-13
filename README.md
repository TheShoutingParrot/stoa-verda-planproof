# Planproof

A local Stoa / Junction prototype for checking quantities against construction drawings. Click a measured room to see its contribution, compare the sum of the printed areas with the geometry, or inspect a bedroom label on a scanned apartment plan.

## Open the prototype

Requires Python 3.10+ and a modern browser. The core application uses the Python standard library and browser JavaScript.

```sh
python3 server.py
```

Open **http://127.0.0.1:4179/**. The companion **/finnish.html** page shows the original Finnish scan, local OCR comparison and a saved NVIDIA Nemotron Parse run. A configured Super VL image endpoint can run the scan again.

- **Swiss geometry.** Nine rooms labelled *Stanza* on floor 5 measure **124.50 m²** together. Switching to the printed values produces **124.49 m²**. Click room 5.11 to inspect **13.61707 m²** from its outline and **13.62 m²** from its label. Try “How many bathrooms?” for a different set of rooms. Ask “What is the area of room 5.11?” to highlight just that room. Switch drawings to try another floor. On [site 1006, room 1.19](http://127.0.0.1:4179/?sheet=site1006_bldg2088_floor9498&room=1.19), the measured area is **15.06 m²**. You can type a room number, pick one from the selector or inspect the original PDF and DXF. The viewer counts and sums room groups locally. It also measures the indoor area of an apartment or floor and counts doors, windows and bathroom fixtures. Try “How many doors are drawn on this floor plan?” and click a numbered symbol to inspect the CAD geometry.
- **Finnish scan.** The indicated apartment is outlined in green. Tesseract read no exact bedroom abbreviations. At 4× magnification it produced one fuzzy candidate, `moakuuh`. Click the candidate under *Inspect local OCR candidates* to locate the printed text. The local Nemotron Parse v1.2 run independently transcribed `makuuh,` in the full scan and lower-left crop. Matching that reading to a Tesseract box inside the green outline yielded one bedroom label. Click **1. makuuh** to inspect its position. The saved run took 31.6 seconds for warm full-sheet inference, excluding load, OCR localization and crop checks. This is one known example. [Recorded output](public/data/finnish/parse-run.json) · [Local reproduction](scripts/local_parse.py).

**Hosted Super VL label check.** In NVIDIA’s playground, Nemotron 3.5 Super VL classified the candidate as a bedroom label and expanded it to *makuuhuone*. The playground exposed preset images only in this session. The prompt supplied the actual OCR reading and a character-grid rendering of the label crop. This verifies a recognition step and does not establish whole-image visual grounding. NVIDIA reported 134.07 seconds for this trial. [Exact input and response](public/data/finnish/super-vl-label-check.json). Verda hosting and full-image Super VL inference still require a live run on the event endpoint.

## Run Nemotron 3.5 Super VL

Use a provider endpoint that accepts images, plus a key issued by that same provider. For Verda, use the event endpoint and the exact served alias confirmed by booth 6. For NVIDIA's own NIM use `https://integrate.api.nvidia.com/v1` and its matching credential. The default model is `nvidia/nemotron-3.5-super-vl-120b-a12b`. Never enter keys into the web page or commit them.

Put the endpoint into `NEMOTRON_BASE_URL`, set the matching secret in the server environment as `NEMOTRON_API_KEY`, and optionally set `NEMOTRON_MODEL` to a provider-specific alias for this exact model. For example, if the key is in hsec and the endpoint has already been exported:

```sh
hsec exec --only NEMOTRON_API_KEY -- python3 server.py
```

Stop the existing local server before restarting it with credentials, or use `--port 4180`. With both settings present, the Finnish page offers **Run Nemotron on this scan**. The server sends only the bundled drawing and question to the configured HTTPS endpoint. Live runs explicitly triggered in the browser save evidence to `public/data/finnish/run.json`. The terminal has the same entry point for repeatable experiments:

```sh
hsec exec --only NEMOTRON_API_KEY -- python3 scripts/nemotron.py \
  public/data/finnish/high_quality_architectural-13066.png \
  --output public/data/finnish/run.json
```

The report records the provider host, requested and returned model identifiers when available, image hash, latency, provider-reported tokens, result status and evidence boxes. The drawing hash must match the image in the viewer. Boxes are normalized to 0–1000 on both axes, with top-left origin. The server keeps a previous successful model response if a later request fails. The CLI writes the latest attempt to the requested output path and returns 0 for an answer, 1 for uncertainty, and 2 for an unavailable service.

## Reproduce the measurements

```sh
python3 scripts/extract_rooms.py
python3 -m unittest discover -s tests -v
```

The [full English Swiss benchmark](docs/swiss-frontier.md) covers 1,040 drawings and includes the original 60-site comparison. The [frontier model benchmark](docs/swiss-vision.md) uses the same 1,080 English questions from those 60 sites. Planproof reads the sponsor’s paired CAD files, and GPT-6 Astra reads the sponsor’s rendered images. The [earlier room-lookup experiment](docs/swiss-benchmark.md) records the previous baseline.

The extractor matches DXF text to enclosing straight closed room outlines and subtracts interior cutouts. It reads model units and adds unrounded areas before formatting the total. The supplied geometry targets this Swiss drawing convention. The scan's optional OCR reproduction uses Tesseract 5 with English language data and Python Pillow: `python3 scripts/ocr_baseline.py`.

## Data and award briefs

The software is MIT licensed. The Swiss drawing and its derived room geometry are CC BY 4.0. The Finnish scan and its annotations are CC BY-NC-SA 4.0 for this noncommercial hackathon prototype. See [Swiss attribution](public/data/SWISS-SOURCE.md) and [Finnish attribution](public/data/FINNISH-SOURCE.md).

[Junction Stoa brief](https://hackjunction.app/participate/45/challenges/335) · [Verda compute challenge](https://hackjunction.app/participate/45/tech-challenges/56) · [NVIDIA challenge](https://hackjunction.app/participate/45/tech-challenges/46) · [NVIDIA model and endpoint](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b)
