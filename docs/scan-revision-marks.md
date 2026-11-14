# Checking the opening and fixture marks

We compared the old and new boxes on all 177 door, window, toilet and sink questions in the 48-drawing benchmark. Each box could match one original CubiCasa annotation at an intersection-over-union threshold of 0.25. The source SVG uses the threshold in the wall for a door. Each sponsor image matched the corresponding original PNG by SHA-256. The sponsor integer and the SVG instance count agreed on 177/177 questions. The annotated files were available only to the assessor after predictions were frozen. [Count results and cohort](scan-revision-evaluation.md) · [Original CubiCasa5K vector annotations](https://doi.org/10.5281/zenodo.2613548)

| Object | Old matched / marks placed | New matched / marks placed | Old matched / annotated | New matched / annotated | Questions with all objects marked and no extra marks, old → new |
|---|---:|---:|---:|---:|---:|
| Windows | 330/401 (82.3%) | 346/373 (92.8%) | 330/458 (72.1%) | 346/458 (75.5%) | 16 → 20 of 48 |
| Doors | 261/277 (94.2%) | 285/303 (94.1%) | 261/323 (80.8%) | 285/323 (88.2%) | 14 → 16 of 35 |
| Toilet bowls | 53/61 (86.9%) | 53/61 (86.9%) | 53/67 (79.1%) | 53/67 (79.1%) | 35 → 35 of 48 |
| Sinks | 89/106 (84.0%) | 89/106 (84.0%) | 89/127 (70.1%) | 89/127 (70.1%) | 24 → 24 of 46 |
| All | 733/845 (86.7%) | 773/843 (91.7%) | 733/975 (75.2%) | 773/975 (79.3%) | 89 → 95 of 177 |

Across the 48 window questions, unmatched predictions fell from 71 to 27. The number of annotated windows without a matching mark fell from 128 to 112. Seven previously wrong totals became correct and four previously correct totals regressed. On drawing 1767 the old reader placed nine marks for two windows. The revised reader placed exactly two and both matched. On drawing 6058 the old reader found every one of its nine windows and the revision missed two. Drawing 1966 shows why the two metrics matter. Its revised count fell from the correct 23 to 21, even as the number of correctly located windows rose from 19 to 20. [Fixed example](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1767.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) · [Missed windows](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-6058.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) · [Count and location disagreement](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1966.png&question=How+many+windows+are+shown+on+this+floor+plan%3F)

## Inspect the window counts

The links open the exact question on the original scan when the local server is running on port 4179 with the sponsor ZIP. Each matched mark is paired with a distinct annotated opening. The reader sees only the PNG. [Run the prototype](../README.md)

| Drawing | Expected count | Previous count | New count | Matched window marks, old → new |
|---|---:|---:|---:|---:|
| [high_quality-1025](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1025.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 6 | 6 | 4 → 4 |
| [high_quality-1282](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1282.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 7 | 14 | 7 | 7 → 6 |
| [high_quality-1403](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1403.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 7 | 7 | 7 | 7 → 7 |
| [high_quality-20174](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20174.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 5 | 5 | 5 | 5 → 5 |
| [high_quality-20183](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20183.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |
| [high_quality-20197](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20197.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 5 | 5 | 5 | 5 → 5 |
| [high_quality-20198](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-20198.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 10 | 10 | 10 | 9 → 9 |
| [high_quality-3106](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3106.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 7 | 6 | 8 | 6 → 7 |
| [high_quality-3247](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3247.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 8 | 7 | 7 | 7 → 7 |
| [high_quality-3638](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3638.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 3 | 3 | 3 → 3 |
| [high_quality-3676](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3676.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |
| [high_quality-3801](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-3801.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |
| [high_quality-4712](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4712.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |
| [high_quality-4767](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4767.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 6 | 5 | 5 | 5 → 5 |
| [high_quality-477](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-477.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 5 | 6 | 4 → 4 |
| [high_quality-4815](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-4815.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 8 | 8 | 8 | 7 → 8 |
| [high_quality-5588](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5588.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 3 | 3 | 3 | 3 → 3 |
| [high_quality-5836](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-5836.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 11 | 13 | 11 | 11 → 11 |
| [high_quality-6058](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-6058.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 9 | 9 | 7 | 9 → 7 |
| [high_quality-837](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-837.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 9 | 6 | 6 | 6 → 6 |
| [high_quality-8380](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-8380.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 5 | 4 | 3 → 3 |
| [high_quality-90](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-90.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 5 | 7 | 5 | 4 → 5 |
| [high_quality-9671](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-9671.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 6 | 5 | 6 | 5 → 6 |
| [high_quality-9864](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-9864.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |
| [high_quality_architectural-1191](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1191.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 24 | 20 | 21 | 20 → 21 |
| [high_quality_architectural-1319](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1319.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 11 | 10 | 9 | 6 → 7 |
| [high_quality_architectural-165](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-165.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 6 | 5 | 7 | 5 → 5 |
| [high_quality_architectural-1669](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1669.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 3 | 3 | 3 | 3 → 3 |
| [high_quality_architectural-1767](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1767.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 2 | 9 | 2 | 2 → 2 |
| [high_quality_architectural-1837](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1837.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 3 | 4 | 4 | 3 → 3 |
| [high_quality_architectural-1966](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1966.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 23 | 23 | 21 | 19 → 20 |
| [high_quality_architectural-1982](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1982.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 25 | 17 | 18 | 13 → 16 |
| [high_quality_architectural-20000](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-20000.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 6 | 6 | 6 | 6 → 6 |
| [high_quality_architectural-2037](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-2037.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 2 | 2 | 2 | 2 → 2 |
| [high_quality_architectural-2204](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-2204.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 16 | 1 | 0 | 0 → 0 |
| [high_quality_architectural-4014](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4014.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 7 | 7 | 7 | 7 → 7 |
| [high_quality_architectural-4707](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4707.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 18 | 6 | 4 | 3 → 3 |
| [high_quality_architectural-4898](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-4898.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 19 | 13 | 14 | 12 → 13 |
| [high_quality_architectural-5018](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5018.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 17 | 17 | 18 | 17 → 16 |
| [high_quality_architectural-5089](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-5089.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 6 | 4 | 4 | 4 → 4 |
| [high_quality_architectural-6166](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-6166.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 10 | 9 | 10 | 9 → 10 |
| [high_quality_architectural-6276](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-6276.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 32 | 18 | 20 | 12 → 19 |
| [high_quality_architectural-6697](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-6697.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 23 | 15 | 14 | 13 → 13 |
| [high_quality_architectural-8269](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-8269.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 7 | 5 | 4 → 4 |
| [high_quality_architectural-8285](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-8285.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 17 | 17 | 10 | 12 → 10 |
| [high_quality_architectural-8573](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-8573.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 12 | 6 | 4 → 4 |
| [high_quality_architectural-9443](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9443.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 34 | 23 | 25 | 20 → 23 |
| [high_quality_architectural-9886](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-9886.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 4 | 4 | 4 | 4 → 4 |

## Reproduce the location check

First run the paired count scorer, which verifies both prediction seals before creating the joined rows. Then run the following with the upstream source ZIP.

```sh
uv run --no-project --python 3.12 --with svgpathtools==1.8.0 python scripts/score_scan_evidence.py \
  --questions .local/evaluation/scan-revision/paired-rows.json \
  --upstream /path/to/cubicasa5k.zip \
  --output .local/evaluation/scan-revision/grounding.json
```
