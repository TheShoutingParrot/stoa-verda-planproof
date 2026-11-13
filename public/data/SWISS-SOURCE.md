# Swiss Dwellings floor 10281

The original source is [Swiss Dwellings v3.0.0](https://doi.org/10.5281/zenodo.7788422) by Matthias Standfest, Michael Franzen, Yvonne Schröder, Luis Gonzalez Medina, Yarilo Villanueva Hernandez, Jan Hendrik Buck, Yen-Ling Tan, Milena Niedzwiecka and Rachele Colmegna (Archilyse AG), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The [Stoa Junction preview](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset-preview.zip) includes the Swiss files in `data/swiss_dwellings/`. The pack's authors rendered the drawings from published geometry and added the drawing style, room numbers, unit numbers, localized labels, door swings and title block. Archilyse AG does not endorse the derived drawings. The [original per-source notice](swiss/LICENSE.md), [original DXF](swiss/site1102_bldg2242_floor10281.dxf) and [original PDF](swiss/site1102_bldg2242_floor10281.pdf) are included. The floor data and its illustrated adaptations retain this attribution and CC BY 4.0 license.

PlanProof extracts source polygons, label positions and measured areas and highlights selected rooms. Coordinates use the original DXF model axes in metres, with positive Y upward. Areas are calculated from unrounded polygon vertices and printed labels are preserved separately. Two numbered rooms have no category or printed area, two polygons have no room number, and four open detail lines are preserved separately. Empty category strings mean that the source provides no room type. The extractor reads the straight, closed ROOM_OUTLINE polygons used on this sheet. It does not identify arbitrary drawing symbols or subtract interior holes from other CAD formats.

To reproduce the JSON from the repository root, run `python3 scripts/extract_rooms.py` using Python 3.10 or later. To extract another Junction Swiss DXF, use `python3 scripts/extract_rooms.py path/to/another.dxf --output /tmp/another.json`. The fixture test runs with `python3 -m unittest discover -s tests -p test_geometry.py`.

The preview DXF SHA-256 is `4070c5f19eb921bc08e2f5a23e957086f76abcca03fafbb8b62ca30c8a60b58d`.
