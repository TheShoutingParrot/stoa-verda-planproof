# Reading rooms and storeys from the detector’s room map

The label reader answers a room question only when OCR finds the room’s printed name among at least three labels of two kinds. The panel reader answers a storey question only when raw ink shows one clean panel or captioned panels. On the 48-drawing comparison that left 158 of 398 prompts unanswered. A third local reader now takes those prompts. It joins the printed labels with the room map of the CubiCasa5K network and reads the wet rooms a second time at a larger scale. It runs only after the label and panel readers decline, so every count they return is unchanged. [Label reader](../scripts/scan_rooms.py) · [Panel reader](scan-storeys.md) · [Room-map reader](../scripts/scan_layout.py) · [Detector setup and licence](scan-objects.md)

## What the reader sees

The network’s room head assigns every pixel to background, outdoor space, wall, kitchen, living room, bedroom, bath, entry, railing, storage, garage or other room. The upstream training labels map saunas and WC rooms to the bath class and balconies, terraces and yards to outdoor space. The released weights do not follow that mapping for saunas. On the 420 development drawings, 252 of the 254 sauna-bench symbols of at least 0.2% of the interior lay in a region classed as other room, and only 2 of the 598 bath-class regions held any bench symbol. The icon head marks toilet bowls, sinks, bathtubs and sauna benches. It has no class for showers. These planes come from the object reader’s first pass over the drawing, averaged over four orientations. A drawing passes through the network once at that scale, whichever question is asked first.

From these planes it derives three things. A floor panel is one connected body of walls and rooms. A room region is a connected area of one room class that covers at least 0.4% of the interior. A symbol belongs to the region under it. Each printed label from the sheet OCR is assigned to the region under its box.

Short names such as *WC*, *KPH* and *S* are often lost at sheet scale. For sauna, WC and bathroom questions the reader cuts up to six bath-class regions out of the original image, enlarges each up to four times onto one white sheet and runs the Vision OCR again in the sheet’s reading direction and its reverse. A sauna room that the network classes as other room is not among these regions. Its printed name is read again only when it falls inside the enlarged crop of a neighbouring bath-class region, which happened for 4 of 35 such sauna labels on the development drawings. Storey, kitchen and balcony questions never use this second look, so an answer does not depend on which question was asked first.

## Rules

Every positive count carries one box per counted instance. Every zero carries the boxes that were examined and a one-sentence reason. Shares are fractions of the interior area in the room map.

| Question | The reader answers | The reader declines |
|---|---|---|
| Storeys | **1** when the room map has one floor panel. **N** when it has N panels, each with at least a quarter of the largest panel’s room area. Without a level caption each panel needs at least three quarters of that area. Evidence: one box per panel. | A level caption on a one-panel sheet. All four raw-ink views showing two or more panels. A caption count of two or more that differs from the panel count. An extra body between 10% and 25% of the largest panel. |
| Kitchens | **1** when the map has exactly one kitchen region and it covers at least 4%. Evidence: the region. | A second kitchen region of 0.4% or more. Two kitchen labels. Two apartment designations. |
| Saunas | **1** for a sauna-bench symbol of at least 0.4%, or for a sauna label inside a bath-class region. **0** when there is no bench, no sauna label, no *+S* designation, and every bath-class region holds a toilet bowl, a sink, or a bathroom or WC label. | Bench symbols far apart. A sauna label outside the wet rooms. Weak bench traces. A wet room with neither fixture nor name. No bath-class region at all. |
| Separate WC rooms | The number of bath-class regions that hold a *WC* label. **0** when the plan has a single bath-class region of at least 3%, at most one toilet bowl and no *WC* label. | A *WC* label outside the wet rooms. An unclear reading such as *WG*. A second toilet room under 3% without a name. Several wet rooms and no *WC* label. |
| Bathrooms | The number of bath-class regions that hold a bathroom label. **1** when a sheet with at least three labels of two kinds has exactly one unnamed bath-class region of at least 3% with a toilet bowl or sink. | A bathroom label outside the wet rooms. A second wet room of at least 3% without a name. A sheet with too few printed names. |
| Balconies | The number of balcony labels, each inside an outdoor region. **0** when the map has no outdoor region of at least 1%, or when every such region is labelled *terassi* or *kuisti*. | An outdoor region without a name. A balcony label outside the outdoor regions. |
| Bedrooms | Never. The label reader keeps this family. | Always. |
| Showers and bathtubs | Never. The network was trained without a shower class and no printed label marks a shower. | Always. |

A zero is never inferred from a missing label alone. It needs a completed sheet OCR, and for wet rooms a completed second look. A sheet without printed room names keeps its bathroom question unanswered. The sponsor count for that question follows the printed names, and a drawing without names gives no evidence either way.

## Measured on development drawings

The rules were developed on previously exposed drawings only. No drawing reserved for the next fresh comparison was opened. The development set holds 420 drawings with released prompts: all 167 exposed drawings of the official CubiCasa test split and 253 drawings of the validation split, taken in a hash order. The 80 drawings of the two earlier comparisons went to tuning because they had been inspected before. A stable hash of the path sent two fifths of the other drawings to tuning and three fifths to confirmation. The rules were chosen on the 208 tuning drawings and frozen. The 212 confirmation drawings were then scored once. The baseline is the reader at commit `b948d67` with no hosted endpoint.

| Question on the confirmation drawings | Deferred at baseline | Newly answered | Exact | Exact share (95% Wilson interval) | Test split | Validation split |
|---|---:|---:|---:|---:|---:|---:|
| Storeys | 152 | 129 | 127 | 98.4% (94.5–99.6) | 30/30 | 97/99 |
| Kitchens | 89 | 77 | 76 | 98.7% (93.0–99.8) | 18/18 | 58/59 |
| Saunas | 132 | 104 | 104 | 100.0% (96.4–100.0) | 30/30 | 74/74 |
| Separate WC rooms | 94 | 68 | 64 | 94.1% (85.8–97.7) | 20/21 | 44/47 |
| Bathrooms | 62 | 28 | 26 | 92.9% (77.4–98.0) | 11/12 | 15/16 |
| Balconies | 43 | 25 | 24 | 96.0% (80.5–99.3) | 1/2 | 23/23 |
| **All six** | **572** | **431** | **421** | **97.7% (95.8–98.7)** | **110/113** | **311/318** |

The last two columns give exact answers over newly answered prompts on the 57 test-split and 155 validation-split confirmation drawings. The detector was trained on the training split and selected on the validation split, so the test-split column is the stricter check. It has only two newly answered balcony prompts. The 65 deferred bedroom prompts and 198 shower prompts on these drawings stayed deferred. On the tuning drawings the same rules newly answered 443 prompts and 436 were exact (98.4%, interval 96.8–99.2).

The label and panel readers on this branch returned the baseline answer on all 2,332 room and storey prompts of 549 development drawings, so no previously answered prompt changed.

On the 48-drawing comparison, which was tuning data here, 108 of the 158 deferred prompts became exact, two kitchen prompts became wrong and 48 stayed deferred. That would move its totals from 167 exact, 73 wrong and 158 deferred to 275, 75 and 48. On the 96 prompts of the 32-drawing comparison the offline reader deferred 47 room, storey and shower prompts. Twenty-nine became exact, none wrong and 18 stayed deferred, eight of them shower prompts. Neither figure estimates the gain on fresh drawings. [48-drawing comparison](scan-revision-evaluation.md) · [32-drawing comparison](scan-holdout.md)

## Time per drawing

The room map is computed once per drawing and kept for the eight most recent drawings. Its planes come from the first detector pass, which the object reader needs as well. Whichever reader asks first pays for that pass and the other reuses it. The first sauna, WC or bathroom question also pays for two Vision calls on the enlarged wet rooms. Later questions about the same drawing reuse both. Questions that the label or panel readers answer cost nothing extra.

The timings below were taken while the room-map reader still ran a detector pass of its own. Both readers answered every released English prompt of 24 tuning drawings, about nine prompts per drawing, alternating drawing by drawing on a machine shared with other jobs. The baseline took 6.60 s per drawing on average and 9.64 s at worst. The room-map branch took 10.47 s on average and 16.37 s at worst, 3.87 s more per drawing on average. Measured separately on 12 drawings, the separate detector pass took 3.04 s, the second look 1.05 s and the remaining steps 0.12 s. On these 24 drawings the branch newly answered 56 prompts and changed none of the baseline’s answers.

The two readers now share the first pass, so a drawing with an object question no longer pays for the separate one. On 18 development drawings the shared pass gave byte-identical room and icon planes and identical window, door, toilet bowl and sink marks, whichever reader asked first.

## Limits

The reader needs the optional detector and the macOS Vision OCR. Without the detector it is skipped. Without a completed Vision pass it declines, because every rule lets a caption or a second label veto its count.

A utility kitchen or scullery that the network classes as storage is invisible to the kitchen rule. Both wrong kitchen counts on the 48-drawing cohort are sheets with such a second kitchen. Two buildings of similar size on one sheet, such as a cottage and its sauna building, are counted as two storeys when no caption says otherwise. Two floor panels drawn wall to wall merge in the room map and are caught only when all four ink views separate them.

The ten wrong new answers on the confirmation drawings show the same weaknesses. Two storey counts included a separate storage building, one of them because a single level caption waived the size check. One sheet had a second kitchen. Four WC counts and two bathroom counts came from sheets where a wet room’s name was not read or two wet rooms shared one region. One balcony was not classed as outdoor space.

A sauna count of zero rests mainly on the absence of any bench symbol and of a sauna label at sheet scale. The second look adds to that only where a sauna lies inside or next to a bath-class region, because it reads bath-class regions and a sauna drawn with benches is usually outside them. All 92 such zeros on the development drawings matched the sponsor answer, 42 on tuning and 50 on confirmation.

The sponsor counts follow the annotators’ room names and symbols. A sauna that is drawn with a bench and stove but carries no label can count as zero there, and a room with a printed name that the annotators left undefined can count as zero bedrooms. The reader does not chase those cases.

Bedroom questions that the label reader declines stay unanswered. A second look at the bedroom regions answered seven such prompts on 157 tuning drawings and six matched the sponsor, too few to ship. Shower questions stay unanswered because nothing on the drawing can be tied to the network’s classes or to a printed label.
