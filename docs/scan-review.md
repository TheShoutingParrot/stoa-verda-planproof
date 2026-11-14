# Floor-plan scan review

All 96 sponsor questions appear below, grouped by what the user asked to count. Each drawing link opens the original scan in a local Planproof server on port 4179. The repository includes all 96 measured predictions in a digest-verified replay. Start the server with the sponsor ZIP available and select the question in **Saved questions** to inspect its marks. The expected count appears only in this evaluation. [Setup](../README.md) · [Evaluation design and aggregate results](scan-holdout.md)

## Did the marks land on the right objects?

We compared each reader’s overlay with the upstream author’s SVG annotations after both prediction sets were sealed. For each drawing in the location audit, the sponsor PNG matched the upstream original byte for byte. All 35 object questions had the same reference count in the sponsor answers and SVG annotations. Each predicted box could match one object, and each object one box. A match required an intersection-over-union of at least 0.25. Door references cover the threshold in the wall. A box around the swing arc can consequently miss the reference. [CubiCasa5K source drawings and annotations](https://doi.org/10.5281/zenodo.2613548)

| On questions both readers could evaluate | Questions | Reference objects | Old matched / proposed | New matched / proposed | Old → new questions with every object located and no extra marks |
|---|---:|---:|---:|---:|---:|
| Doors | 6 | 51 | 0 / 12 | 46 / 47 | 0 → 3 |
| Windows | 6 | 33 | 1 / 4 | 24 / 39 | 1 → 1 |
| Toilet bowls | 4 | 6 | 2 / 5 | 6 / 6 | 1 → 4 |
| Sinks | 8 | 21 | 5 / 13 | 15 / 16 | 0 → 5 |
| All | 24 | 111 | 8 / 34 | 91 / 108 | 2 → 13 |

Both readers received usable service on 24 object questions, all with at least one annotated object. The old reader located 8 of 111 objects (7.2%) and the new reader located 91 (82.0%). Among marks actually placed, 8/34 (23.5%) and 91/108 (84.3%) matched, respectively. Across all 35 object questions, including 11 with a service outage for the old reader, the counts were 8/166 and 135/166. The score here measures the location of the marks. Exact counts for whole questions are reported separately below.

## Changes worth inspecting

- In drawing 8731 the old reader abstained on both bedrooms and doors. The new reader counted two bedrooms and seven doors. All seven door marks matched different annotated openings.
- In drawing 1444 the toilet count improved from two to one. The sink count regressed from two to three. Both annotated sinks were located, alongside an extra mark. Both readers counted six doors on the same plan. The old marks matched zero thresholds and the new marks matched five.
- On comparable window questions, 24 of 33 annotated windows were located, yet only one of six whole-drawing counts was exact. The new reader placed 39 marks. That left nine annotated windows unmatched and 15 unmatched predictions. Four drawings were overcounted and one was undercounted.
- Of 34 comparable questions where the old reader abstained, the new reader answered 12 correctly, answered 11 incorrectly and abstained on 11. It corrected two of the seven old wrong counts. Two previously correct counts regressed, one sink overcount and one shower abstention.

## Individual counts

“Abstained” means the reader returned no usable count. “HTTP 429” means the hosted service was still rate-limiting after recovery. “Marks matched” gives old → new numbers of unique reference objects located. An em dash means the question is outside the four audited object types.

### Balconies

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [colorful-9448](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fcolorful-9448.png) | 0 | Abstained | Abstained | — |
| [high_quality-20168](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20168.png) | 1 | HTTP 429 | 1 | — |
| [high_quality-4851](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4851.png) | 0 | 0 | 0 | — |
| [high_quality-750](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-750.png) | 0 | 0 | 0 | — |
| [high_quality_architectural-1839](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1839.png) | 1 | Abstained | 1 | — |
| [high_quality_architectural-7780](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7780.png) | 0 | 0 | 0 | — |
| [high_quality_architectural-9422](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9422.png) | 0 | 0 | 0 | — |

### Bathrooms

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-20168](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20168.png) | 1 | 1 | 1 | — |
| [high_quality-20188](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20188.png) | 1 | 1 | 1 | — |
| [high_quality-337](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-337.png) | 1 | 1 | 1 | — |
| [high_quality-7790](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-7790.png) | 0 | 0 | 0 | — |
| [high_quality_architectural-141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-141.png) | 1 | Abstained | Abstained | — |
| [high_quality_architectural-1718](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1718.png) | 1 | Abstained | Abstained | — |
| [high_quality_architectural-2053](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-2053.png) | 1 | Abstained | Abstained | — |

### Bedrooms

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-1877](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1877.png) | 2 | Abstained | 2 | — |
| [high_quality-3141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3141.png) | 3 | Abstained | 3 | — |
| [high_quality-6624](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-6624.png) | 3 | Abstained | 3 | — |
| [high_quality-8731](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-8731.png) | 2 | Abstained | 2 | — |
| [high_quality_architectural-1217](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1217.png) | 3 | Abstained | 3 | — |
| [high_quality_architectural-1781](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1781.png) | 1 | Abstained | 2 | — |
| [high_quality_architectural-5760](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5760.png) | 2 | Abstained | 2 | — |
| [high_quality_architectural-7696](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7696.png) | 0 | Abstained | 1 | — |

### Doors

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-3141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3141.png) | 11 | Abstained | 9 | 0 → 9 |
| [high_quality-8731](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-8731.png) | 7 | Abstained | 7 | 0 → 7 |
| [high_quality_architectural-1444](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1444.png) | 6 | 6 | 6 | 0 → 5 |
| [high_quality_architectural-172](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-172.png) | 7 | 6 | 7 | 0 → 7 |
| [high_quality_architectural-2053](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-2053.png) | 12 | Abstained | 10 | 0 → 10 |
| [high_quality_architectural-3024](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-3024.png) | 11 | HTTP 429 | 9 | 0 → 9 |
| [high_quality_architectural-4553](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4553.png) | 8 | Abstained | 8 | 0 → 8 |
| [high_quality_architectural-4928](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4928.png) | 12 | HTTP 429 | 9 | 0 → 9 |
| [high_quality_architectural-5617](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5617.png) | 4 | HTTP 429 | 2 | 0 → 2 |

### Floors

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-20188](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20188.png) | 1 | Abstained | Abstained | — |
| [high_quality-3078](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3078.png) | 1 | Abstained | Abstained | — |
| [high_quality-3162](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3162.png) | 1 | 1 | 1 | — |
| [high_quality-5703](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5703.png) | 1 | 1 | 1 | — |
| [high_quality-750](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-750.png) | 1 | 1 | 1 | — |
| [high_quality-7790](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-7790.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-1839](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1839.png) | 1 | Abstained | Abstained | — |
| [high_quality_architectural-4928](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4928.png) | 2 | Abstained | Abstained | — |

### Kitchens

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-1877](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1877.png) | 1 | 1 | 1 | — |
| [high_quality-4851](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4851.png) | 1 | 1 | 1 | — |
| [high_quality-9480](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-9480.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-141.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-1718](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1718.png) | 1 | Abstained | Abstained | — |
| [high_quality_architectural-172](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-172.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-5760](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5760.png) | 1 | HTTP 429 | HTTP 429 | — |
| [high_quality_architectural-9422](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9422.png) | 1 | 1 | 1 | — |

### Saunas

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [colorful-9448](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fcolorful-9448.png) | 0 | 0 | 0 | — |
| [high_quality-3078](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3078.png) | 0 | 0 | 0 | — |
| [high_quality-3162](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3162.png) | 1 | 0 | 0 | — |
| [high_quality-750](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-750.png) | 0 | 0 | 0 | — |
| [high_quality-7790](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-7790.png) | 0 | 0 | 0 | — |
| [high_quality-8731](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-8731.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-172](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-172.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-5760](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5760.png) | 1 | HTTP 429 | HTTP 429 | — |

### Separate wc rooms

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-20168](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20168.png) | 0 | 0 | 0 | — |
| [high_quality-20188](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20188.png) | 0 | HTTP 429 | HTTP 429 | — |
| [high_quality_architectural-1217](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1217.png) | 1 | 2 | 2 | — |
| [high_quality_architectural-141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-141.png) | 1 | HTTP 429 | HTTP 429 | — |
| [high_quality_architectural-1718](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1718.png) | 1 | 1 | 1 | — |
| [high_quality_architectural-2053](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-2053.png) | 1 | Abstained | Abstained | — |
| [high_quality_architectural-7696](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7696.png) | 0 | Abstained | Abstained | — |

### Showers

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-3141](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3141.png) | 2 | HTTP 429 | 1 | — |
| [high_quality-9480](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-9480.png) | 1 | Abstained | 1 | — |
| [high_quality_architectural-1839](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1839.png) | 1 | Abstained | 0 | — |
| [high_quality_architectural-4553](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4553.png) | 1 | Abstained | 3 | — |
| [high_quality_architectural-4928](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4928.png) | 1 | HTTP 429 | 1 | — |
| [high_quality_architectural-5617](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5617.png) | 1 | HTTP 429 | 1 | — |
| [high_quality_architectural-7780](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7780.png) | 1 | 1 | Abstained | — |
| [high_quality_architectural-9422](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9422.png) | 1 | 2 | 0 | — |

### Sinks

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-1877](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1877.png) | 2 | 2 | 2 | 1 → 2 |
| [high_quality-3078](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3078.png) | 2 | Abstained | 2 | 0 → 2 |
| [high_quality-5703](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5703.png) | 2 | 2 | 2 | 1 → 2 |
| [high_quality-5807](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5807.png) | 2 | 2 | 2 | 1 → 2 |
| [high_quality-6624](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-6624.png) | 3 | 3 | 3 | 1 → 3 |
| [high_quality_architectural-1217](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1217.png) | 5 | Abstained | 0 | 0 → 0 |
| [high_quality_architectural-1444](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1444.png) | 2 | 2 | 3 | 1 → 2 |
| [high_quality_architectural-1781](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1781.png) | 3 | 2 | 2 | 0 → 2 |

### Toilet bowls

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [colorful-9448](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fcolorful-9448.png) | 1 | HTTP 429 | 1 | 0 → 1 |
| [high_quality-3162](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3162.png) | 2 | HTTP 429 | 2 | 0 → 2 |
| [high_quality-337](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-337.png) | 2 | Abstained | 2 | 0 → 2 |
| [high_quality-5703](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5703.png) | 1 | 1 | 1 | 1 → 1 |
| [high_quality-5807](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5807.png) | 1 | HTTP 429 | 1 | 0 → 1 |
| [high_quality-6624](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-6624.png) | 2 | HTTP 429 | 4 | 0 → 2 |
| [high_quality_architectural-1444](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1444.png) | 1 | 2 | 1 | 1 → 1 |
| [high_quality_architectural-3024](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-3024.png) | 2 | HTTP 429 | 2 | 0 → 2 |
| [high_quality_architectural-4553](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4553.png) | 2 | 2 | 2 | 0 → 2 |

### Windows

| Drawing | Expected | Old | New | Marks matched, old → new |
|---|---:|---:|---:|---:|
| [high_quality-337](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-337.png) | 9 | Abstained | 7 | 0 → 5 |
| [high_quality-4851](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4851.png) | 4 | HTTP 429 | 4 | 0 → 4 |
| [high_quality-5807](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5807.png) | 7 | HTTP 429 | 6 | 0 → 6 |
| [high_quality-9480](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-9480.png) | 6 | Abstained | 7 | 0 → 6 |
| [high_quality_architectural-1781](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1781.png) | 7 | 3 | 11 | 0 → 4 |
| [high_quality_architectural-3024](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-3024.png) | 9 | HTTP 429 | 7 | 0 → 6 |
| [high_quality_architectural-5617](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5617.png) | 1 | 1 | 1 | 1 → 1 |
| [high_quality_architectural-7696](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7696.png) | 1 | Abstained | 3 | 0 → 1 |
| [high_quality_architectural-7780](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-7780.png) | 9 | Abstained | 10 | 0 → 7 |

## Reproduce the location check

First run the paired scorer to validate the two prediction seals. Supply the upstream CubiCasa5K ZIP containing the original and scaled PNG and SVG for each drawing. The evaluator checks the original image SHA-256, uses the scaled raster dimensions to align the annotated vectors, and writes both overall and common-service counts.

```sh
uv run --no-project --python 3.12 --with svgpathtools==1.8.0 python scripts/score_scan_evidence.py \
  --questions .local/evaluation/scan-holdout/paired-rows.json \
  --upstream /path/to/cubicasa5k.zip \
  --before .local/evaluation/scan-holdout/baseline \
  --after .local/evaluation/scan-holdout/candidate \
  --output .local/evaluation/scan-holdout/grounding.json
```
