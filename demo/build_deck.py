"""Build the Planproof pitch deck as one self-contained HTML file (and optionally a PDF).

usage: python3 -I demo/build_deck.py --kit TEAM_SLIDE_KIT_DIR --frames DEMO_FRAMES_DIR [--out DIR] [--pdf] [--png]

The deck follows the team slide kit: a 1920 x 1080 canvas with 128 px margins, dark background, Inter,
and the kit's team slide second to last. The team slide is rendered from the kit's team.json (or --team) and photos,
which are read as data only. Product slides use the frames captured for the demo video
(demo/out/frames). Every figure on the slides comes from docs/scan-next-evaluation.md and the result
files next to it; each slide's speaker note names its source.

Outputs (ignored by git, because the photos are private): DIR/planproof-deck.html, and with --pdf
DIR/planproof-deck.pdf, rendered by a headless Chromium browser (DEMO_BROWSER, a Playwright headless shell or Brave).
"""
import argparse
import base64
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--kit', type=Path, required=True, help='extracted team-slide-kit folder (contains team.json)')
parser.add_argument('--team', type=Path, help="team.json with the team's own corrections; defaults to the kit's (photos still come from the kit)")
parser.add_argument('--frames', type=Path, required=True, help='demo video frames (demo/out/frames)')
parser.add_argument('--out', type=Path, default=HERE / 'out' / 'deck')
parser.add_argument('--pdf', action='store_true', help='also print the deck to PDF with a headless browser')
parser.add_argument('--png', action='store_true', help='also save one PNG per slide for checking')
parser.add_argument('--browser', help='Chromium binary; defaults to DEMO_BROWSER, then a Playwright headless shell, then Brave')
args = parser.parse_args()
esc = html.escape
MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


def data_uri(path):
    path = Path(path)
    if path.suffix.lower() not in MIME:
        sys.exit('unsupported image: %s' % path)
    return 'data:%s;base64,%s' % (MIME[path.suffix.lower()], base64.b64encode(path.read_bytes()).decode())


def frame(name):
    return data_uri(args.frames / name)


# ---------------------------------------------------------------- team slide from the kit (data only)
kit = args.kit.resolve()
team = json.loads((args.team or kit / 'team.json').read_text(encoding='utf-8'))
members = {m['id']: m for m in team['members']}


def member_photo(member):
    photo = (kit / member['photo']).resolve()
    if kit not in photo.parents:
        sys.exit('photo outside the kit: %s' % member['photo'])
    return data_uri(photo)


team_columns = ''.join(
    '<div class="member" style="--i:%d"><img class="photo" src="%s" alt="%s"><h3>%s</h3><ul class="who">%s</ul></div>'
    % (i, member_photo(m), esc(m['name']), esc(m['name']), ''.join('<li>%s</li>' % esc(c) for c in m['credentials']))
    for i, m in enumerate(members[k] for k in team['slide']['order']))
first_names = [members[k]['name'].split()[0] for k in team['slide']['order']]
team_slide = '''<section id="team">
<p class="eyebrow">%s</p>
<h2>%s</h2>
<div class="team">%s</div>
<aside>Four of us from Aalto: %s and %s. Content from the team slide kit's team.json%s.</aside>
</section>''' % (esc(team['slide']['eyebrow']), esc(team['slide']['title']), team_columns, ', '.join(first_names[:-1]), first_names[-1], ', with the team\'s corrections' if args.team else ', unchanged')


# ---------------------------------------------------------------- outcome bars for the results slide
def outcome_bar(label, exact, wrong, total):
    deferred = total - exact - wrong
    pct = lambda n: 100 * n / total
    return ('<div class="bar-row"><div class="bar-label">%s</div><div class="bar">'
            '<div class="seg exact" style="width:%.3f%%" title="Exact: %d of %d"><span>%d exact</span></div>'
            '<div class="seg wrong" style="width:%.3f%%" title="Wrong: %d of %d"><span>%d wrong</span></div>'
            '<div class="seg deferred" style="width:%.3f%%" title="Deferred: %d of %d"><span>%d deferred</span></div>'
            '</div></div>') % (esc(label), pct(exact), exact, total, exact, pct(wrong), wrong, total, wrong,
                               pct(deferred), deferred, total, deferred)


# Figures, all from docs/scan-next-results-2026-11-15.json ("overall") and docs/scan-next-evaluation.md.
results = json.loads((HERE.parent / 'docs' / 'scan-next-results-2026-11-15.json').read_text())['overall']
hybrid = json.loads((HERE.parent / 'docs' / 'scan-next-nvidia-hybrid-2026-11-15.json').read_text())
showers = json.loads((HERE.parent / 'docs' / 'scan-next-nvidia-showers-2026-11-15.json').read_text())
before, after = results['before'], results['after']
assert (before['exact'], before['wrong'], after['exact'], after['wrong'], before['questions']) == (189, 145, 325, 140, 608)
assert round(results['delta_exact_pp'], 1) == 22.4 and [round(x, 1) for x in results['clustered_bootstrap_delta_pp_95']] == [18.7, 26.1]
assert round(100 * before['accuracy_when_answered'], 1) == 56.6 and round(100 * after['accuracy_when_answered'], 1) == 69.9
arms, calls = hybrid['arms'], hybrid['hosted_calls_needed']
assert (arms['nemotron_alone']['exact'], arms['nemotron_alone']['wrong'], calls['nemotron_alone']) == (247, 231, 608)
assert (arms['hybrid_after']['exact'], arms['hybrid_after']['wrong'], calls['hybrid_after']) == (392, 186, 143)
assert (arms['hybrid_after_shower_route']['exact'], arms['hybrid_after_shower_route']['wrong'], calls['hybrid_after_shower_route']) == (405, 175, 143)
assert (showers['showers']['old_route']['exact'], showers['showers']['new_route']['exact'], showers['showers']['prompts']) == (28, 41, 66)
bars = outcome_bar('Previous reader', before['exact'], before['wrong'], 608) + outcome_bar('Current reader', after['exact'], after['wrong'], 608)

SLIDES = [
# 1 ------------------------------------------------------------------------------------------- title
'''<section id="title" class="split">
<div class="col">
<p class="eyebrow">JUNCTION 2026 · STOA CHALLENGE · VERDA AND NVIDIA TECH CHALLENGES</p>
<h1>Planproof</h1>
<p class="lead">Ask a construction drawing how many. Get the number, and see exactly where each one is.</p>
<p class="soft">Windows, doors, rooms and storeys, counted on the original drawing. Every count links to its evidence.</p>
</div>
<div class="shot tall crop"><img src="{{windows}}" alt="Planproof marking 18 windows on a held-out floor plan"></div>
<aside>Planproof answers count questions about construction drawings and links every count to evidence on the drawing. Screenshot: held-out drawing 6549, windows question (demo video frame 03-windows-0).</aside>
</section>''',
# 2 ------------------------------------------------------------------------------------------ problem
'''<section id="problem">
<p class="eyebrow">PROBLEM</p>
<h2>Counting on drawings is slow, and the total cannot be checked</h2>
<div class="cards three">
<div class="card"><h3>Slow by hand</h3><p>Someone goes through each sheet and counts window, door and room symbols by eye. Every new question is another pass over the drawing.</p></div>
<div class="card"><h3>Unverifiable</h3><p>The result is a number in a spreadsheet. Nothing shows which symbols were counted, or which were missed.</p></div>
<div class="card"><h3>A model alone does not fix it</h3><p>A vision model that returns only a number is just as hard to check. On our held-out test, Nemotron alone was exact on <b>247 of 608</b> questions.</p></div>
</div>
<aside>247 of 608: Nemotron 3.5 Super VL alone on the 72 held-out drawings (docs/scan-next-nvidia-hybrid-2026-11-15.json, arms.nemotron_alone).</aside>
</section>''',
# 3 ---------------------------------------------------------------------------------- what it does
'''<section id="what" class="split">
<div class="col">
<p class="eyebrow">WHAT PLANPROOF DOES</p>
<h2>Ask how many. Get the number and the marks.</h2>
<ul class="points">
<li>Pick a drawing and type a count question.</li>
<li>Get the number, plus one mark per counted item on the original scan.</li>
<li>Click a row to see that item on the drawing.</li>
<li>The answer names the reader or model that produced it.</li>
</ul>
<p class="callout">Held-out drawing 6549: <b>18 windows, 18 marks</b>. The previous reader found 15.</p>
</div>
<div class="shot tall"><img src="{{windows}}" alt="18 window marks on drawing 6549"></div>
<aside>Example from docs/scan-next-evaluation.md, "Clickable examples": windows on architectural drawing 6549, 18 marks for 18 windows, up from 15. Also in demo/links.md.</aside>
</section>''',
# 4 ------------------------------------------------------------------------------ rooms and zeros
'''<section id="rooms">
<p class="eyebrow">ROOMS, STOREYS AND ZEROS</p>
<h2>Rooms and storeys too, and a room zero shows which rooms were checked</h2>
<div class="pair">
<figure><div class="shot"><img src="{{storeys}}" alt="Three floor panels, each with its own box"></div><figcaption><b>3 storeys</b>, one box per floor panel. The previous reader deferred this question.</figcaption></figure>
<figure><div class="shot"><img src="{{zero}}" alt="Zero saunas, with the examined wet room marked"></div><figcaption><b>0 saunas</b>, and the evidence is the wet room it examined, not an empty box.</figcaption></figure>
</div>
<aside>Storeys: high_quality-1692, expected 3, previous reader deferred, current 3 (demo/links.md). Zero: saunas on a held-out drawing, frame 05-zero-0 of the demo video. Narration: "Even a zero comes with evidence."</aside>
</section>''',
# 5 ------------------------------------------------------------------------------------ how it works
'''<section id="how">
<p class="eyebrow">HOW IT WORKS</p>
<h2>Local readers first, NVIDIA Nemotron for what they cannot prove</h2>
<div class="flow">
<div class="node q"><h3>Question</h3><p>“How many windows are shown on this floor plan?” on the original drawing</p></div>
<div class="arrow">→</div>
<div class="node local"><h3>Local readers, offline</h3>
<ol><li>Room-label OCR on the scan</li><li>CubiCasa5K floor-plan detector: room map and floor panels</li><li>Windows and doors read again at the drawing’s own scale</li></ol></div>
<div class="arrow">→</div>
<div class="branch">
<div class="node ok"><h3>Proven</h3><p>Answer and one mark per item</p></div>
<div class="node nv"><h3>Not proven</h3><p>NVIDIA Nemotron 3.5 Super VL on NVIDIA’s endpoint answers and marks what it counted. The source line names the model.</p></div>
</div>
</div>
<p class="foot">Scan evidence is bound to the original image by SHA-256. Without a hosted endpoint, unproven questions are deferred.</p>
<aside>README.md and docs/scan-next-evaluation.md. The product sends every question no local reader can verify to Nemotron 3.5 Super VL (integrate.api.nvidia.com).</aside>
</section>''',
# 6 ----------------------------------------------------------------------------------------- dataset
'''<section id="dataset" class="split">
<div class="col">
<p class="eyebrow">THE SPONSOR DATASET</p>
<h2>Built on the full 9.8 GB release</h2>
<div class="tiles two">
<div class="tile"><div class="value">4,787</div><div class="label">CubiCasa scans of Finnish floor plans</div></div>
<div class="tile"><div class="value">1,040</div><div class="label">Swiss plans with CAD files</div></div>
<div class="tile"><div class="value">533</div><div class="label">IFC building models</div></div>
<div class="tile"><div class="value">64,132</div><div class="label">English questions</div></div>
</div>
<p class="soft">Tested on 72 held-out CubiCasa test drawings and their 608 questions, none used in development.</p>
</div>
<div class="shot tall"><img src="{{library}}" alt="The drawing library with 4,787 CubiCasa drawings"></div>
<aside>README.md: the library indexes 1,040 Swiss floor plans with companion DXFs, 533 raw IFC models and 4,787 CubiCasa scans; 64,132 English questions in the 9.77 GB release (9.8 GB in the video narration).</aside>
</section>''',
# 7 ----------------------------------------------------------------------------------------- results
'''<section id="results">
<p class="eyebrow">RESULTS · SEALED, PRE-REGISTERED, OFFLINE</p>
<h2>Exact answers rose from 189 to 325 of 608</h2>
<div class="tiles three">
<div class="tile"><div class="value">+22.4<small> points</small></div><div class="label">exact answers, 95% interval 18.7 to 26.1</div></div>
<div class="tile"><div class="value">56.6% <i>→</i> 69.9%</div><div class="label">accuracy among answered questions</div></div>
<div class="tile"><div class="value">145 <i>→</i> 140</div><div class="label">wrong answers, while answering 131 more questions</div></div>
</div>
<div class="bars" role="img" aria-label="Outcomes of 608 questions: previous reader 189 exact, 145 wrong, 274 deferred; current reader 325 exact, 140 wrong, 143 deferred">
{{bars}}
<div class="legend"><span><i class="key exact"></i>Exact</span><span><i class="key wrong"></i>Wrong</span><span><i class="key deferred"></i>Deferred</span></div>
</div>
<p class="foot">72 held-out CubiCasa test drawings · baseline sealed before tuning · one scored run plus an identical repeat · no hosted model</p>
<aside>docs/scan-next-evaluation.md, "Result", and docs/scan-next-results-2026-11-15.json (overall): 189 / 145 / 274 before, 325 / 140 / 143 after; +22.37 points, clustered bootstrap 18.74 to 26.05; 131 newly answered, 127 of them exact.</aside>
</section>''',
# 8 ------------------------------------------------------------------------------------------- marks
'''<section id="marks" class="split">
<div class="col">
<p class="eyebrow">CHECKED AGAINST THE SVG ANNOTATIONS</p>
<h2>The marks land on real windows and doors</h2>
<div class="tiles stack">
<div class="tile"><div class="value">68.5% <i>→</i> 76.2%</div><div class="label">of annotated windows found · 507 → 564 of 740</div></div>
<div class="tile"><div class="value">85.6% <i>→</i> 95.0%</div><div class="label">of annotated doors found · 427 → 474 of 499</div></div>
<div class="tile"><div class="value">90%</div><div class="label">of window marks land on a real window · 564 of 625 (92.3% before)</div></div>
</div>
</div>
<div class="shot tall crop"><img src="{{windows_marks}}" alt="Window marks on the original scan of drawing 6549"></div>
<p class="foot">Every window and door mark compared with the drawing’s CubiCasa SVG annotation. A mark matches when it overlaps one annotated object at an intersection-over-union of 0.25 or more</p>
<aside>Screenshot: drawing 6549, windows (demo video frame 03-windows-1). docs/scan-next-evaluation.md, "Where the marks fall": windows 507 (68.5%) → 564 (76.2%) of 740; doors 427 (85.6%) → 474 (95.0%) of 499; current window marks matching 564 / 625 (90.2%).</aside>
</section>''',
# 9 ------------------------------------------------------------------------------------------- NVIDIA
'''<section id="nvidia" class="split narrow-shot">
<div class="col">
<p class="eyebrow">ON NVIDIA · NEMOTRON 3.5 SUPER VL</p>
<h2>More exact answers, fewer NVIDIA calls</h2>
<table class="numbers">
<thead><tr><th>Same 608 questions</th><th>Exact</th><th>Wrong</th><th>NVIDIA calls</th></tr></thead>
<tbody>
<tr><td>Nemotron alone</td><td>247</td><td>231</td><td>608</td></tr>
<tr><td>Planproof readers, then Nemotron</td><td>392</td><td>186</td><td>143</td></tr>
<tr class="best"><td>… with the shower reasoning route</td><td>405</td><td>175</td><td>143</td></tr>
</tbody></table>
<p class="callout">Letting Nemotron reason over shower symbols raised held-out shower counts from <b>28 to 41 of 66</b> (paired sign test p = 0.04).</p>
<p class="foot-inline">Descriptive: added after the protocol was fixed, nothing tuned on these drawings. Shower route chosen on 45 development drawings, confirmed on 90 others.</p>
</div>
<div class="shot tall"><img src="{{nvidia}}" alt="Showers and bathtubs answered by Nemotron on NVIDIA's endpoint, with marks"></div>
<aside>docs/scan-next-nvidia-hybrid-2026-11-15.json (arms, hosted_calls_needed) and docs/scan-next-nvidia-showers-2026-11-15.json (28 → 41 of 66, gained 24, lost 11, p = 0.041). Screenshot: an interactive shower answer from Nemotron on integrate.api.nvidia.com (demo video frame 06-nvidia-1).</aside>
</section>''',
# 10 ------------------------------------------------------------------------------------------ limits
'''<section id="limits">
<p class="eyebrow">HONEST LIMITS</p>
<h2>What we have not shown yet</h2>
<ul class="points big">
<li><b>Window totals did not improve significantly:</b> +1.4 points (−8.3 to 12.5). The window marks improved; the exact totals did not.</li>
<li><b>Showers, and the bedroom questions the label reader defers (20 of 40), still rely on the hosted model.</b> The shower route is right on 61 of 90 confirmation drawings, still behind a constant answer of one (69 of the same 90).</li>
<li><b>No NVIDIA GPU was measured locally:</b> the detector ran on an Apple M5 only. It selects CUDA when present. Verda-hosted inference still needs verification.</li>
<li><b>The current reader is about 1.7 times slower:</b> 9.4 s per drawing against 5.6 s.</li>
<li><b>Test composition:</b> 60 of the 72 drawings are architectural and none is colorful.</li>
</ul>
<aside>docs/scan-next-evaluation.md, "By question family" (windows +1.4, −8.3 to 12.5), "Showers on NVIDIA's endpoint", "How the run was controlled" (9.4 s vs 5.6 s) and "Limits"; README.md for Verda.</aside>
</section>''',
# 11 -------------------------------------------------------------------------------------------- team
team_slide,
# 12 -------------------------------------------------------------------------------------------- demo
'''<section id="demo" class="split">
<div class="col">
<p class="eyebrow">DEMO</p>
<h2>Ask a drawing how many, and check every count</h2>
<ol class="steps">
<li><b>Windows</b> on drawing 6549: click through the 18 marks.</li>
<li><b>Storeys</b> on drawing 1692: answered from the room map, deferred before.</li>
<li><b>A zero with evidence:</b> no sauna, and the wet rooms that were examined.</li>
<li><b>Ask live:</b> “How many doors are shown on this floor plan?”</li>
<li><b>Showers</b> go to Nemotron on NVIDIA’s endpoint, and say so.</li>
</ol>
<p class="soft">No model or key needed for the saved answers: every demo link replays a sealed answer offline.</p>
</div>
<div class="col cta">
<div class="card"><h3>Run it</h3><p><code>python3 server.py</code>, then open the drawing library and pick any plan. With <code>NEMOTRON_BASE_URL</code> set to NVIDIA's endpoint and <code>NEMOTRON_API_KEY</code> in the server environment, unproven questions go to Nemotron.</p></div>
<div class="card"><h3>Next</h3><ul class="points">
<li>Measure the detector on an NVIDIA GPU on Verda.</li>
<li>Move bedrooms and showers to local readers.</li>
<li>Try it on your own drawings: ask how many, see exactly where.</li>
</ul></div>
</div>
<aside>Live demo order from demo/README.md and demo/links.md. Next steps follow from the limits slide.</aside>
</section>''',
]

images = {'windows': frame('03-windows-0.png'), 'storeys': frame('04-storeys-0.png'), 'zero': frame('05-zero-0.png'),
          'nvidia': frame('06-nvidia-1.png'), 'windows_marks': frame('03-windows-1.png'), 'library': frame('02-library-0.png'), 'bars': bars}
def fill(slide):
    for key, value in images.items():
        slide = slide.replace('{{%s}}' % key, value)
    return slide


slides = '\n'.join(s if s is team_slide else fill(s) for s in SLIDES)

CSS = '''
html, body { margin: 0; background: #000; }
body { font-family: 'Inter', -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #F7F8F8; overflow: hidden; }
h1, h2, h3, p, ul, ol, figure { margin: 0; }
ul, ol { padding-left: 1.2em; }
#stage { width: 1920px; height: 1080px; transform-origin: top left; position: absolute; }
section { box-sizing: border-box; width: 1920px; height: 1080px; background: #08090A; color: #F7F8F8;
          padding: 128px 128px 160px; display: none; flex-direction: column; gap: 40px; position: relative; }
section.active { display: flex; }
h1 { font-size: 132px; font-weight: 800; letter-spacing: -4px; line-height: 1; }
h2 { font-size: 64px; font-weight: 700; line-height: 1.1; letter-spacing: -1.5px; max-width: 1500px; }
h3 { font-size: 30px; font-weight: 600; line-height: 1.2; }
.eyebrow { font-size: 24px; font-weight: 600; letter-spacing: 2px; color: #8B93FF; line-height: 1.1; }
.lead { font-size: 44px; line-height: 1.25; font-weight: 600; }
.soft { font-size: 28px; line-height: 1.45; color: #B4B8C0; }
.soft.wide { max-width: 1400px; }
b { color: #F7F8F8; font-weight: 700; }
aside { display: none; }
.split { flex-direction: row; gap: 64px; align-items: center; }
.split .col { flex: 1 1 0; display: flex; flex-direction: column; gap: 36px; min-width: 0; }
.shot { border: 2px solid #3A3D45; border-radius: 16px; overflow: hidden; background: #F3F4EF; }
.shot img { display: block; width: 100%%; height: 100%%; object-fit: cover; object-position: left top; }
.split .shot.tall { flex: 0 0 900px; height: 640px; }
.narrow-shot .shot.tall { flex-basis: 760px; height: 600px; }
.narrow-shot .col { gap: 28px; }
.shot.crop img { object-fit: none; object-position: -215px -300px; }
#marks .shot.crop img { object-position: -225px -330px; }
.cards { display: grid; gap: 32px; }
.cards.three { grid-template-columns: 1fr 1fr 1fr; margin-top: 24px; }
.card { background: #121317; border: 2px solid #23252B; border-radius: 16px; padding: 40px; display: flex; flex-direction: column; gap: 20px; }
.card p { font-size: 28px; line-height: 1.45; color: #B4B8C0; }
.points { font-size: 30px; line-height: 1.4; color: #B4B8C0; display: flex; flex-direction: column; gap: 14px; }
.points.big { font-size: 32px; gap: 24px; max-width: 1560px; }
.points li::marker, .steps li::marker { color: #8B93FF; }
.callout { font-size: 30px; line-height: 1.4; color: #B4B8C0; border-left: 6px solid #8B93FF; padding: 6px 0 6px 28px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 48px; }
.pair .shot { height: 470px; }
figcaption { font-size: 28px; line-height: 1.4; color: #B4B8C0; margin-top: 22px; }
.flow { display: flex; align-items: center; gap: 28px; margin-top: 20px; }
.node { background: #121317; border: 2px solid #23252B; border-radius: 16px; padding: 32px; display: flex; flex-direction: column; gap: 16px; }
.node p, .node ol { font-size: 26px; line-height: 1.4; color: #B4B8C0; }
.node ol { display: flex; flex-direction: column; gap: 10px; }
.node.q { flex: 0 0 300px; }
.node.local { flex: 0 0 560px; border-color: #8B93FF; }
.branch { display: flex; flex-direction: column; gap: 28px; flex: 1 1 0; }
.node.nv { border-color: #76B900; }
.arrow { font-size: 56px; color: #8B93FF; }
.foot { position: absolute; left: 128px; right: 128px; bottom: 72px; font-size: 22px; color: #80858F; line-height: 1.4; }
.foot-inline { font-size: 22px; color: #80858F; line-height: 1.45; }
.tiles { display: grid; gap: 32px; }
.tiles.two { grid-template-columns: 1fr 1fr; }
.tiles.three { grid-template-columns: 1fr 1fr 1fr; }
.tiles.stack { grid-template-columns: 1fr; gap: 20px; }
.tiles.stack .tile { padding: 22px 32px; }
.tiles.stack .tile .value { font-size: 56px; }
.tiles.stack .tile .label { margin-top: 8px; }
.tile { background: #121317; border: 2px solid #23252B; border-radius: 16px; padding: 32px 36px; }
.tile .value { font-size: 64px; font-weight: 700; letter-spacing: -1.5px; line-height: 1.05; white-space: nowrap; }
.tile .value small { font-size: 32px; font-weight: 600; letter-spacing: 0; color: #B4B8C0; }
.tile .value i { font-style: normal; color: #8B93FF; font-weight: 600; }
.tile .label { font-size: 26px; line-height: 1.4; color: #B4B8C0; margin-top: 14px; }
.split .tile .value { font-size: 72px; }
.bars { display: flex; flex-direction: column; gap: 20px; margin-top: 8px; }
.bar-row { display: grid; grid-template-columns: 250px 1fr; align-items: center; gap: 24px; }
.bar-label { font-size: 26px; color: #B4B8C0; }
.bar { display: flex; gap: 2px; height: 64px; }
.seg { display: flex; align-items: center; padding-left: 18px; box-sizing: border-box; font-size: 24px; font-weight: 600; white-space: nowrap; overflow: hidden; }
.seg:first-child { border-radius: 4px 0 0 4px; } .seg:last-child { border-radius: 0 4px 4px 0; }
.seg.exact { background: #7880F0; color: #08090A; }
.seg.wrong { background: #CF7650; color: #08090A; }
.seg.deferred { background: #1C1E23; color: #B4B8C0; border: 2px dashed #3A3D45; }
.legend { display: flex; gap: 36px; font-size: 22px; color: #B4B8C0; padding-left: 274px; }
.legend .key { display: inline-block; width: 22px; height: 22px; border-radius: 4px; margin-right: 10px; vertical-align: -3px; }
.key.exact { background: #7880F0; } .key.wrong { background: #CF7650; } .key.deferred { background: #1C1E23; border: 2px dashed #3A3D45; box-sizing: border-box; }
table.numbers { border-collapse: collapse; font-size: 28px; width: 100%%; }
.numbers th { text-align: right; font-size: 22px; font-weight: 600; color: #80858F; padding: 0 0 14px 24px; }
.numbers th:first-child, .numbers td:first-child { text-align: left; padding-left: 0; }
.numbers td { text-align: right; padding: 16px 0 16px 24px; border-top: 2px solid #23252B; color: #B4B8C0; font-variant-numeric: tabular-nums; }
.numbers tr.best td { color: #F7F8F8; font-weight: 700; }
.numbers tr.best td:first-child { font-weight: 600; }
.steps { font-size: 30px; line-height: 1.4; color: #B4B8C0; display: flex; flex-direction: column; gap: 16px; }
.cta { flex: 0 0 700px; gap: 32px; }
code { font-family: ui-monospace, Menlo, monospace; color: #F7F8F8; font-size: .9em; }
/* team slide, from the kit's slide/team.css */
.team { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 32px; }
.member { display: flex; flex-direction: column; gap: 16px; }
.member .photo { width: 220px; height: 220px; border-radius: 110px; object-fit: cover; border: 2px solid #3A3D45; }
.who { font-size: 24px; line-height: 1.45; color: #B4B8C0; }
body.still .member { animation: none !important; }
@keyframes rise { from { opacity: 0; transform: translateY(14px); } }
section.active .member { animation: rise 420ms ease-out both; animation-delay: calc(var(--i) * 110ms); }
#counter { position: fixed; right: 16px; bottom: 12px; font: 13px -apple-system, sans-serif; color: #555; }
#notes { position: fixed; left: 0; right: 0; bottom: 0; background: rgba(18,19,23,.96); color: #D0D3D8; font: 16px/1.5 -apple-system, sans-serif;
         padding: 14px 20px; display: none; border-top: 1px solid #333; }
body.show-notes #notes { display: block; }
@media print {
  @page { size: 1920px 1080px; margin: 0; }
  html, body { background: #08090A; overflow: visible; }
  #stage { position: static; transform: none !important; }
  section { display: flex !important; break-after: page; page-break-after: always; }
  section .member { animation: none !important; }
  #counter, #notes { display: none !important; }
}
'''

JS = '''
var slides = Array.prototype.slice.call(document.querySelectorAll('section'));
var index = Math.max(0, Math.min(slides.length - 1, (parseInt(location.hash.slice(1), 10) || 1) - 1));
function show(i) {
  index = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach(function (s, k) { s.classList.toggle('active', k === index); });
  document.getElementById('counter').textContent = (index + 1) + ' / ' + slides.length;
  var note = slides[index].querySelector('aside');
  document.getElementById('notes').textContent = note ? note.textContent : '';
  history.replaceState(null, '', '#' + (index + 1));
}
function fit() {
  var s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  var el = document.getElementById('stage');
  el.style.transform = 'scale(' + s + ')';
  el.style.left = ((window.innerWidth - 1920 * s) / 2) + 'px';
  el.style.top = ((window.innerHeight - 1080 * s) / 2) + 'px';
}
document.addEventListener('keydown', function (e) {
  if (['ArrowRight', 'PageDown', ' ', 'Enter'].indexOf(e.key) >= 0) { show(index + 1); e.preventDefault(); }
  else if (['ArrowLeft', 'PageUp', 'Backspace'].indexOf(e.key) >= 0) { show(index - 1); e.preventDefault(); }
  else if (e.key === 'Home') show(0);
  else if (e.key === 'End') show(slides.length - 1);
  else if (e.key === 'n' || e.key === 'N') document.body.classList.toggle('show-notes');
  else if (e.key === 'f' || e.key === 'F') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen(); }
});
document.addEventListener('click', function (e) { show(e.clientX < window.innerWidth / 3 ? index - 1 : index + 1); });
window.addEventListener('resize', fit);
if (location.search.indexOf('still') >= 0) document.body.classList.add('still');
fit(); show(index);
'''

page = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planproof pitch deck</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<style>%s</style>
</head>
<body>
<div id="stage">
%s
</div>
<div id="counter"></div>
<div id="notes"></div>
<script>%s</script>
</body>
</html>
''' % (CSS % (), slides, JS)

args.out.mkdir(parents=True, exist_ok=True)
deck = args.out / 'planproof-deck.html'
deck.write_text(page, encoding='utf-8')
print('slides: %d -> %s (%.1f MB)' % (len(SLIDES), deck, deck.stat().st_size / 1e6))


def find_browser():
    if args.browser or os.environ.get('DEMO_BROWSER'):
        return args.browser or os.environ['DEMO_BROWSER']
    shells = sorted(Path.home().glob('Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell'))
    return str(shells[-1]) if shells else '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'


def headless(*extra):
    browser = find_browser()
    mode = [] if browser.endswith('chrome-headless-shell') else ['--headless=new']
    with tempfile.TemporaryDirectory(prefix='planproof-deck-') as profile:
        subprocess.run([browser, *mode, '--hide-scrollbars', '--no-first-run', '--disable-extensions',
                        '--user-data-dir=' + profile, '--virtual-time-budget=4000', *extra],
                       check=True, capture_output=True, timeout=90)


if args.pdf:
    pdf = args.out / 'planproof-deck.pdf'
    headless('--no-pdf-header-footer', '--print-to-pdf=' + str(pdf), deck.as_uri())
    print('pdf ->', pdf)
if args.png:
    for k in range(1, len(SLIDES) + 1):
        png = args.out / ('slide-%02d.png' % k)
        headless('--window-size=1920,1080', '--screenshot=' + str(png), deck.as_uri() + '?still#%d' % k)
    print('png -> %s/slide-NN.png' % args.out)
