# Planproof drawing library and benchmark

The November 13, 2026 build opens 6,360 drawings from the 9,768,952,082-byte Stoa release. The library searches drawing names, source collections and the titles in the IFC attribution table. The app can open 533 IFC models, 1,040 paired Swiss PDF/DXF drawings and 4,787 CubiCasa scans. Only 15 of those raw IFC models have English quantity questions in the released IFC Models evaluation. [Open the local library](http://127.0.0.1:4179/library.html) · [Sponsor archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip)

## Released English questions

The benchmark accounts for 64,132 questions. Planproof produced 20,144 numeric answers, of which 19,960 were correct. This raises correct answers on the full release from 18,801 to 19,960, or from 29.32% to 31.12%. The 1,159 additional correct answers comprise 352 new offline IFC answers and 807 previously recorded answers from the stopped NVIDIA run. The scan run covered the first 186 image paths it processed. Its accuracy does not estimate performance on the 38,237 remaining prompts.

| Source | English questions | Correct | Wrong | Abstained | Unsupported | Unrun |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Swiss Dwellings | 18,792 | 18,789 | 3 | 0 | 0 | 0 |
| CubiCasa5K | 42,757 | 819 | 181 | 3,520 | 0 | 38,237 |
| IFC Models | 1,699 | 352 | 0 | 0 | 1,347 | 0 |
| IFC-Bench | 820 | 0 | 0 | 0 | 820 | 0 |
| Opening Design | 64 | 0 | 0 | 0 | 64 | 0 |
| **Total** | **64,132** | **19,960** | **184** | **3,520** | **2,231** | **38,237** |

The Swiss rerun matched the previous answers and evidence checks on all 1,040 sheets. All 12,784 counts matched exactly. Three of 6,008 area answers on site 333 fell outside tolerance. Native IFC produced 60 exact counts and 292 areas within 2% of the reference. The 1,347 remaining IFC Models questions refer to derived PDFs. IFC-Bench asks free-form questions on other models, and Opening Design uses other drawing conventions. This is a development benchmark with previously inspected released drawings. Some models contribute many more questions than others, including 280 of the 352 raw IFC questions from the same clinic.

CubiCasa contributes 807 correct answers from 985 numeric predictions on 1,560 hosted questions and 12 correct answers from 15 numeric predictions on 2,960 offline bedroom questions. The release grades counts numerically. It supplies no per-question judgement of the visual evidence boxes. On scan 10052, for example, the model identified four doors with four boxes, against the reference count of five. Browsing archived predictions and querying native CAD/IFC use zero hosted requests. The reported hosted run used 5,557,894 tokens across completed questions. No Verda endpoint or per-answer price was measured.

[Machine-readable scorecard](drawing-library-results-2026-11-13.json)

## Browser checks

- From the searchable library, open site 2263 and ask for room 2.02. Clicking the result selects just that room. Its DXF outline measures 17.52690 m² and the UI displays 17.53 m².
- Open the KIT FZK house and ask “How many doors are on Erdgeschoss?” Its five counted occurrences link to the original declarations. Selecting the second door opens `#19199`, Innentuer-2. Asking for bicycle capacity gives an unsupported answer.
- Open the buildingSMART Duplex architectural model and ask “What is the net floor area of room A102 on Level 1?” The app returns 27.66 m² and links room `#67` to the original 4.783 × 5.783 m rectangle `#56`. The original IFC is downloadable, with its individual credit and licence.
- Open scan 12564. Its three local bedroom labels are independently selectable on the original PNG. A separate fully authenticated, interactive NVIDIA request for windows on the same drawing exhausted the model's output budget. It returned unknown, displayed no numeric result, and replayed the same abstention after a page reload. This custom question is outside the sponsor benchmark.

## Reproduction

Run the library with `python3 server.py --archive /path/to/junction-dataset.zip`. The four bundled prediction examples replay against matching PNGs from that archive. Optional local benchmark checkpoints provide additional replays. A configured inference endpoint enables explicit individual count requests. The README contains endpoint setup and example links. [Start the prototype](../README.md)

With the official ZIP at the default location, run the commands below. The score join requires the saved local full-English baseline and the stopped NVIDIA exports. Its command-line options accept alternate artifact paths. The ZIP alone reproduces the offline Swiss and native IFC evaluations.

```sh
python3 scripts/benchmark_swiss_frontier.py --revision working --split all --jobs 4
python3 scripts/benchmark_ifc_takeoff.py
python3 scripts/score_drawing_library.py
python3 -m unittest discover -s tests -v
node --test tests/*.cjs
```

The score join checks the release fingerprint and reconciles full drawing-path/question pairs. It checks Swiss answer and evidence scope, native IFC entity IDs, and the identity and structure of scan evidence. Output includes a per-question compressed JSONL and a by-source summary. The Python suite can also exercise the optional Finnish preprocessing tests with NumPy and Pillow installed. [Score join](../scripts/score_drawing_library.py) · [Original offline benchmark](full-english.md)
