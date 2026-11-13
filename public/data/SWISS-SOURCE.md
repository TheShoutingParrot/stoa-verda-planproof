# Swiss Dwellings floor 10281

The original source is [Swiss Dwellings v3.0.0](https://doi.org/10.5281/zenodo.7788422) by Matthias Standfest, Michael Franzen, Yvonne Schröder, Luis Gonzalez Medina, Yarilo Villanueva Hernandez, Jan Hendrik Buck, Yen-Ling Tan, Milena Niedzwiecka and Rachele Colmegna (Archilyse AG), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The [Stoa Junction preview](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset-preview.zip) includes the Swiss files in `data/swiss_dwellings/`. The pack's authors rendered the drawings from published geometry and added the drawing style, room numbers, unit numbers, localized labels, door swings and title block. Archilyse AG does not endorse the derived drawings. The [original per-source notice](swiss/LICENSE.md), [original DXF](swiss/site1102_bldg2242_floor10281.dxf) and [original PDF](swiss/site1102_bldg2242_floor10281.pdf) are included. The floor data and its illustrated adaptations retain this attribution and CC BY 4.0 license.

Planproof extracts source polygons, label positions and measured areas and highlights selected rooms. Coordinates use the original DXF model axes in metres, with positive Y upward. Areas are calculated from unrounded polygon vertices and printed labels are preserved separately. Two numbered rooms have no category or printed area, two polygons have no room number, and four open detail lines are preserved separately. Empty category strings mean that the source provides no room type. The extractor reads the straight, closed ROOM_OUTLINE polygons used on this sheet. It does not identify arbitrary drawing symbols or subtract interior holes from other CAD formats.

To reproduce the JSON from the repository root, run `python3 scripts/extract_rooms.py` using Python 3.10 or later. To extract another Junction Swiss DXF, use `python3 scripts/extract_rooms.py path/to/another.dxf --output /tmp/another.json`. The fixture test runs with `python3 -m unittest discover -s tests -p test_geometry.py`.

The preview DXF SHA-256 is `4070c5f19eb921bc08e2f5a23e957086f76abcca03fafbb8b62ca30c8a60b58d`.

## Quantity evidence

The extractor uses each numbered room’s measured net polygon area. Unit captions and `UNIT_OUTLINE` rings identify apartments. Named outdoor rooms and voids are excluded from indoor totals. For some unlabelled spaces, the extractor can infer a balcony from matching geometry or drawing details. The repository’s `docs/swiss-frontier.md` records remaining disagreements with the sponsor quantities.

Door and window counts use the opening frames. Bathroom fixtures use the outlines and inner strokes on the `FIXTURE` layer. The viewer links each counted mark to its original DXF handle and each area contribution to its room. These conventions apply to the Junction Swiss Dwellings renderings.

## Independent floor 9498

The second drawing, `site1006_bldg2088_floor9498`, is a German-language plan from site 1006, building 2088. The [original DXF](swiss/site1006_bldg2088_floor9498.dxf) and [original PDF](swiss/site1006_bldg2088_floor9498.pdf) were extracted without modification from the [full Stoa Junction archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip). The [Swiss Dwellings attribution and licence](swiss/LICENSE.md) above also apply to this drawing. The [derived room geometry](swiss/site1006_bldg2088_floor9498.json) was generated using the same extractor as floor 10281.

The selection was made before opening the drawing or reading its answers. Out of the full archive's Swiss DXFs, exclude every site in the preview, every site in the preceding 60-site evaluation, and the two previously examined sites (1102 and 3387). Sort the 914 remaining filename stems by the hexadecimal SHA-256 of the UTF-8 string `planproof-fresh-select-2026-11-13-v1|<stem>`. The first stem is this drawing, with selection digest `0046e2a56e75a7bbb3c698f9bccf606d1c633134b1923ce3efd3da26c6e39f8b`.

The original DXF SHA-256 is `6d3820dc1d6286961651d6954ab3c94bfa122f7448abe9614ac541f4643625bd`. The original PDF SHA-256 is `7189952e7fe80d760f9b7c3c42e91665e446f82a4079dc8135472afb35cf6b93`.
