# Local door, window and plumbing counts

Planproof can count windows, doors, toilet bowls and sinks on a supplied PNG using CubiCasa's published multi-task hourglass network. A first pass at four orientations finds toilet bowls and sinks as connected fixture masks and measures how long the drawing's doors are. Windows and doors are then read a second time at a scale the network handles well. The reader uses the model’s directional endpoint maps to pair the ends of windows and doors along each wall. It checks the ink between endpoints against the model’s window and door probabilities. Competing openings on the same wall are resolved together, and strong semantic components can supply diagonal or cropped openings. Each result links to a box on the original scan. The model can miss small symbols or merge adjacent symbols. A rendered zero means that no qualifying symbol was detected.

The reader takes the supplied image bytes and question. It checks SHA-256 before reusing any inventory across questions, holds at most 16 small inventories in memory, and serializes local inference. The default interpreter can still use other readers if these optional dependencies or model assets are missing.

## How windows and doors are sized and read

The first pass shrinks the PNG until its longer side is at most 896 px and never enlarges it. Toilet bowl and sink marks come from this pass. The second reading does not change them.

CubiCasa trained the network on drawings resampled until a door threshold is about 78 px long. The median is 76.8 px over 523 annotated doors on the 48-drawing cohort and 79.1 px over 503 doors on 48 validation drawings. Stoa’s PNGs are the drawings before that resampling. The first pass showed the 48-drawing cohort at between 19% and 129% of the training scale, and below half of it on 30 drawings. Most of the windows that the previous reader missed on dense plans were on those drawings.

The reader sizes a drawing by the median length of the door components in the first pass’s segmentation. It needs three doors. The second reading then follows three rules.

- A drawing whose doors measure between 39 and 78 px keeps its own pixels.
- A drawing with shorter doors is enlarged until they measure 39 px.
- A drawing with longer doors is reduced until they measure 78 px.

The resampling uses nearest neighbour. On six drawings a nearest-neighbour resize of the sponsor’s PNG reproduced CubiCasa’s scale-normalised image exactly. The resampled sheet is read in 1024 px square tiles with a white margin, a 128 px overlap and linear blending, at four orientations per tile. The tile side divides by 64, as the 256 px training crops did. A fixed tile also keeps one compiled graph and bounds memory. A sheet that would need more than four tiles is reduced until it fits.

The endpoint decoder is the same on both readings. Its pixel constants scale with the measured door length. One rule uses the door length directly. A window part shorter than half a door that touches another window on the same wall is joined to it, because such a part is usually a sash of that window.

Two checks decide whether the second reading is used.

- With fewer than three doors in the first pass, the reader looks at one orientation of the sheet enlarged to a longer side of about 1536 px, at most four times. It sizes the drawing from that view if it shows at least two doors.
- The second reading must show at least two doors whose median length is within a factor of 1.5 of the length that sized the drawing.

If either check fails, the windows and doors of the first pass are kept. They are decoded as in the previous reader.

## Measured on development drawings

The tables compare the reader of commit `b948d67` with this reader on the same drawings. Both arms use the same first pass. A mark matches one annotated opening of the original CubiCasa SVG at an intersection-over-union of 0.25 or more. A total is exact when the number of marks equals the number of annotated openings. A drawing is fully marked when every annotated opening has its own mark and no mark is left over. The sponsor’s answer equalled the SVG count on every released window and door question of these drawings. The definitions follow the earlier location check. [Earlier location check](scan-revision-marks.md)

The design was chosen on the 48-drawing cohort and on 19 drawings of the official validation split. It was then fixed, and the confirmation drawings were scored once. They are the 119 other official test drawings that earlier Planproof experiments had exposed, which include the 32-drawing cohort, and 57 further validation drawings. None of these drawings belongs to the reserved pool of the fresh comparison. The detector was trained on the official training split and selected on the validation split.

| Drawings | Object | Reader | Totals exact | Marks matched / placed | Annotated located | Fully marked | Mean absolute count error |
|---|---|---|---:|---:|---:|---:|---:|
| Tuning: 48-drawing cohort | Windows, all drawings | `b948d67` | 23/48 | 346/373 (92.8%) | 346/458 (75.5%) | 20 | 2.23 |
| | | this reader | 25/48 | 401/439 (91.3%) | 401/458 (87.6%) | 22 | 1.40 |
| | Doors, 35 released questions | `b948d67` | 18/35 | 285/303 (94.1%) | 285/323 (88.2%) | 16 | 0.86 |
| | | this reader | 22/35 | 301/313 (96.2%) | 301/323 (93.2%) | 18 | 0.51 |
| | Doors, all drawings | `b948d67` | 19/48 | 411/438 (93.8%) | 411/523 (78.6%) | 16 | 1.98 |
| | | this reader | 25/48 | 468/493 (94.9%) | 468/523 (89.5%) | 19 | 0.96 |
| Confirmation: 119 official test drawings | Windows, all drawings | `b948d67` | 53/119 | 698/753 (92.7%) | 698/868 (80.4%) | 52 | 1.52 |
| | | this reader | 59/119 | 765/826 (92.6%) | 765/868 (88.1%) | 55 | 0.97 |
| | Doors, 84 released questions | `b948d67` | 51/84 | 580/616 (94.2%) | 580/664 (87.3%) | 43 | 0.90 |
| | | this reader | 51/84 | 622/666 (93.4%) | 622/664 (93.7%) | 45 | 0.55 |
| | Doors, all drawings | `b948d67` | 58/119 | 858/903 (95.0%) | 858/1026 (83.6%) | 49 | 1.30 |
| | | this reader | 63/119 | 935/993 (94.2%) | 935/1026 (91.1%) | 52 | 0.73 |
| Confirmation: 57 validation drawings | Windows, all drawings | `b948d67` | 23/57 | 350/383 (91.4%) | 350/491 (71.3%) | 22 | 2.39 |
| | | this reader | 27/57 | 401/439 (91.3%) | 401/491 (81.7%) | 25 | 1.72 |
| | Doors, 38 released questions | `b948d67` | 21/38 | 283/297 (95.3%) | 283/335 (84.5%) | 18 | 1.21 |
| | | this reader | 20/38 | 311/333 (93.4%) | 311/335 (92.8%) | 19 | 0.79 |
| | Doors, all drawings | `b948d67` | 22/57 | 438/464 (94.4%) | 438/596 (73.5%) | 19 | 2.60 |
| | | this reader | 22/57 | 498/534 (93.3%) | 498/596 (83.6%) | 21 | 1.68 |

On the 176 confirmation drawings the reader located 1,166 of 1,359 annotated windows, up from 1,048, and 1,433 of 1,622 annotated doors, up from 1,296. Exact window totals rose from 76 to 86. The share of marks that match an annotation stayed at 92% for windows and fell from 94.8% to 93.8% for doors. Exact door totals on the released questions did not improve. They went from 72 to 71 of 122, although the mean count error fell from 1.00 to 0.62. The gain of four exact door totals on the 48-drawing cohort did not carry over. On the confirmation drawings 11 window totals and 12 door totals that were exact before are now wrong, and 21 window totals and 17 door totals became exact. Among the 37 architectural test drawings, exact window totals rose from 12 to 15 and located windows from 250 to 293 of 337.

On the 48-drawing cohort the reader again marks all nine windows of drawing 6058 and gives 23 for drawing 1966. Drawing 1767 keeps its two matching marks. Drawing 8285 has 15 marks, all matching, for 17 windows, and drawing 5018 has 21 marks for 17 windows. Toilet bowl and sink marks were identical on all 224 drawings read for these tables.

Each reader read 24 drawings of the 48-drawing cohort once, cold, in its own process on the Apple M5 while unrelated jobs kept the machine busy. The previous reader took 3.8 s per drawing on average and 6.8 s at worst. This reader took 8.4 s on average and 18.3 s at worst, on a drawing that keeps its own pixels and needs four tiles. One tile at four orientations took 1.5 s in an isolated measurement. Peak MPS driver memory rose from 2.1 GB to 3.1 GB.

## What was tried and not kept

The numbers come from cached detector outputs of the tuning drawings.

- **Reading every drawing at the full training scale.** Nine dense drawings were cached at 50%, 71% and 100% of CubiCasa's normalised size. At 100% the decoder matched 119 of 144 window marks and located 103 of 138 doors. The band above matched 123 of 138 window marks and located 119 of 138 doors. Drawing 2204 is enlarged 5.2 times at 100%, and the reader then found 5 of its 28 doors against 18 at 50%. The network seldom saw drawings enlarged that far.
- **One scale for all drawings.** On 16 dense drawings a uniform 50% located 173 of 219 windows with 195 marks, and a uniform 71% located 174 with 200 marks. The band located 177 with 197 marks.
- **Penalising endpoint peaks left unexplained inside an opening.** On the first pass of the 48-drawing cohort it located 351 windows instead of 346, placed 383 marks instead of 373 and gave 22 exact totals instead of 23.
- **Inferring a missing end from the facing end of the neighbouring opening.** It located 350 windows with 377 marks and 22 exact totals.
- **Closing a one-ended opening where the window or door class stops along the wall.** It located 345 windows with 385 marks and 21 exact totals.
- **Other thresholds.** Joining sashes shorter than 0.40, 0.45, 0.50 and 0.55 of a door left 291, 289, 288 and 288 window marks on 32 drawings, with 260 matched each time. Without the rule there were 295. At 0.60 the matched marks fell to 257. Door acceptance thresholds between 0.15 and 0.5 for the class vote and between 0.32 and 0.6 for the endpoint peak moved the exact door totals between 35 and 38 of 65 tuning drawings. They were left as they were.
- **Six tiles per sheet.** The two drawings that needed six tiles took 14 s and 20 s on a loaded machine. The limit is four.
- **A stricter test for doors that the segmentation does not show.** Of 25 such door marks on 66 tuning drawings, 15 matched an annotated door. Requiring an endpoint peak of 0.5 instead of 0.42 gave 38 exact door totals instead of 35 there. This was measured after the confirmation scores were known, so it is not in the reader. It is a lead for the next round.

## Limitations

- The network does not recognise every drawing style. Drawing 4707 shows its windows as filled blocks, and the reader still finds 4 of 18.
- A window divided by a mullion is annotated as one window on some drawings and as two on others. The reader splits where the network sees facing endpoints. It over-counts drawings such as 1282 (11 marks for 7 windows) and 5018 (21 for 17).
- Some marks fall on openings that the annotation leaves out, for example at the cropped edge of drawing 8573 or on the left wall of drawing 9443. Some annotations are shifted against the image, as on drawing 2204, so a correct mark can fail the overlap test.
- An opening without a door leaf can be marked as a door. The sponsor's door question excludes such openings. The second reading places more such marks on clean drawings, which is why exact door totals did not improve on the confirmation drawings.
- On a faint drawing the second reading can do worse than the first. Validation drawing 1425 has 17 window marks for 9 windows, where the first pass gave 10.
- A drawing with fewer than two detectable doors keeps its first reading, as does a drawing whose doors do not show again at the measured size.
- A sheet that needs more than four tiles is reduced to fit. Its doors are then shorter than 39 px in the second reading.
- The second reading about doubles the time for the first object question on a drawing. During the confirmation run on a busier machine one drawing took 25 s.

## Install and run

Run these commands from the Planproof checkout. The verified environment uses Python 3.12 and PyTorch 2.15.0. Installation downloads the public upstream architecture and checkpoint once. The server uses local files at inference time. Apple Silicon uses MPS when available. Systems with CUDA use CUDA, and other systems use CPU.

```sh
mkdir -p .local/scan-dev/objects
python3.12 -m venv .local/scan-dev/objects/venv
.local/scan-dev/objects/venv/bin/python -m pip install torch==2.15.0 numpy==2.5.4 opencv-python-headless==5.0.0.93 pillow==13.0.0
git clone https://github.com/CubiCasa/CubiCasa5k.git .local/scan-dev/objects/CubiCasa5k
git -C .local/scan-dev/objects/CubiCasa5k checkout c34440266665a11f4484eb06cd2e4b7d72ad76c1
curl -fL --retry 2 -o .local/scan-dev/objects/model_best_val_loss_var.pkl 'https://drive.usercontent.google.com/download?id=1gRB7ez1e4H7a9Y09lLqRuna0luZO5VRK&export=download&confirm=t'
.local/scan-dev/objects/venv/bin/python -m unittest discover -s tests -p 'test_scan_o*.py'
.local/scan-dev/objects/venv/bin/python server.py
```

`PLANPROOF_CUBICASA_CODE` can point to a different checkout of the same upstream commit. `PLANPROOF_OBJECT_WEIGHTS` can point to the downloaded checkpoint elsewhere. The loader verifies hashes of the upstream Python modules and checks the weight file against SHA-256 `dd20b4e1bf1d670f2125107b079df06958b1ccd36e49a464ab739aeb00b8e7a2` before restricted PyTorch `weights_only=True` deserialization. `scripts.scan_objects.available()` checks the local prerequisites without loading tensors. The server should be started with the interpreter that has these packages. With the model assets and the sponsor ZIP present, `tests/test_scan_openings.py` also reads two development drawings through the detector and checks every window mark.

## Source and evaluation scope

Ahti Kalervo, Juha Ylioinas, Markus Häikiö, Antti Karhu and Juho Kannala published this CubiCasa5K model. The upstream repository states CC BY-NC 4.0 and links the checkpoint in its evaluation instructions. The original floor-plan dataset carries CC BY-NC-SA 4.0. The checkpoint and upstream source stay in the ignored local asset directory. [CubiCasa release and evaluation instructions](https://github.com/CubiCasa/CubiCasa5k/tree/c34440266665a11f4484eb06cd2e4b7d72ad76c1) · [Upstream licence](https://github.com/CubiCasa/CubiCasa5k/blob/c34440266665a11f4484eb06cd2e4b7d72ad76c1/LICENSE) · [Original dataset](https://doi.org/10.5281/zenodo.2613548)

Matching filenames from the original split manifests against Stoa's 4,787 CubiCasa PNGs gives 4,018 training drawings, 382 validation drawings and 387 original test drawings. The model trained on many released Stoa drawings. Report performance on the original test partition separately and preserve any independently held-out subset for evaluation. The detector reads no vector annotations, benchmark answers or filenames.
