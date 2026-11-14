# Scan failures in the original NVIDIA run

The original run attempted 1,560 English questions on 186 previously evaluated colorful floor plans. NVIDIA gave 807 correct counts, 178 wrong counts and 575 abstentions. In 529 abstentions the model reached its 4,096-token output limit before it returned a validated answer. Among the remaining abstentions 10 had non-distinct or invalid boxes and six counts disagreed with their number of boxes. The wrong counts included 102 overcounts and 76 undercounts.

| Question | Correct | Overcounted | Undercounted | Abstained | Hit output limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Doors | 4 | 6 | 12 | 112 | 111 |
| Windows | 14 | 9 | 19 | 143 | 118 |
| Saunas | 90 | 3 | 18 | 13 | 12 |
| Toilet bowls | 130 | 21 | 2 | 33 | 31 |
| Sinks and basins | 84 | 7 | 13 | 79 | 78 |
| Storeys | 167 | 0 | 4 | 15 | 5 |
| Balconies | 49 | 6 | 4 | 11 | 9 |
| Showers and bathtubs | 31 | 17 | 3 | 128 | 124 |
| Kitchens | 94 | 3 | 0 | 12 | 12 |
| Bathrooms | 84 | 5 | 1 | 13 | 13 |
| Separate WC rooms | 60 | 25 | 0 | 16 | 16 |

All 25 wrong separate-WC counts were too high. Questions about toilet bowls and separate WC rooms now take different paths. With local object detection installed, the former counts fixture masks. The latter reads labels and checks for ambiguity, including rooms with combined labels. On mirrored scan 11664, reading alternate orientations recovered the kitchen label *KEITTIÖ* and its position in the original image.

On previously evaluated scan 13022 the old reader abstained on door count. The updated detector counted three doors and linked them to three boxes. On scan 10052 the new detector still counted four doors against five and returned zero toilet bowls against one. This error set helped select changes. The separate [holdout protocol](scan-holdout.md) freezes 32 previously unused public test plans for comparison.

The new local object detector scored 39/70 on a development comparison where the old vision reader scored 25/70. The comparison covered four question types on 20 drawings. Eight drawings were in the CubiCasa model’s original training split. On the other 12 it improved from 17/46 to 27/46. The new OCR reader recovered 19 correct answers across 507 development room questions, including 15 old abstentions. These figures helped choose the reader settings and are separate from the frozen test.

The revised hosted route uses NVIDIA's JSON output mode and disables hidden reasoning for difficult direct count questions. The local detector averages semantic masks at four rotations, counts connected symbols and caches the inventory for further questions. The OCR reader checks upright, mirrored or rotated text as needed and maps label boxes back to the source coordinates. It requires an explicit statement plus other visible evidence before declaring a zero from room text. [NVIDIA inference settings](https://docs.nvidia.com/nim/large-language-models/2.1.5/get-started/advanced/get-started-nemotron-3.5-super-vl.html) · [Detector and limitations](scan-objects.md)
