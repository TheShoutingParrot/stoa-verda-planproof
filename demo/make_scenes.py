"""Write demo/scenes.json from the scored comparison, so every number and link in the video comes from a result file.

usage: python3 demo/make_scenes.py --paired PAIRED_ROWS.json --hybrid HYBRID_SUMMARY.json [--after-records FILE] [--drawings N --prompts N]
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--paired', type=Path, required=True)
parser.add_argument('--hybrid', type=Path)
parser.add_argument('--after-records', type=Path, help='development override of the after arm (records keyed by prompt id)')
parser.add_argument('--hosted-example', help='path|question of a saved hosted answer to show')
args = parser.parse_args()
rows = json.loads(args.paired.read_text())
if args.after_records:
    records = json.loads(args.after_records.read_text())['records']
    for row in rows:
        row['new'] = dict(records[row['id']], correct=records[row['id']]['status'] == 'answered' and records[row['id']]['answer'] == row['gold'])


def tally(arm):
    exact = sum(1 for r in rows if r[arm]['status'] == 'answered' and r[arm]['answer'] == r['gold'])
    answered = sum(1 for r in rows if r[arm]['status'] == 'answered')
    return {'exact': exact, 'wrong': answered - exact, 'deferred': len(rows) - answered, 'answered': answered}


def link(row):
    return '/scan-drawing.html?' + urlencode({'path': row['path'], 'question': row['question']})


def gained(category, key, want=None):
    found = [r for r in rows if r['category'] == category and r['new']['status'] == 'answered' and r['new']['answer'] == r['gold']
             and not (r['old']['status'] == 'answered' and r['old']['answer'] == r['gold']) and (want is None or want(r))]
    return max(found, key=key) if found else None


before, after = tally('old'), tally('new')
drawings = len({r['path'] for r in rows})
share = lambda t: round(100 * t['exact'] / max(1, t['answered']))
windows = gained('windows', lambda r: r['gold'], lambda r: r['old']['status'] == 'answered')
storeys = gained('floors', lambda r: (r['gold'], len(r['new']['evidence'])), lambda r: r['gold'] >= 2) or gained('floors', lambda r: r['gold'])
zero = gained('saunas', lambda r: r['path'], lambda r: r['gold'] == 0) or gained('balconies', lambda r: r['path'], lambda r: r['gold'] == 0)
select = lambda k: "document.querySelectorAll('.evidence-row')[%d]?.click()" % k
frame = "document.getElementById('scan-workspace').scrollIntoView({block:'start'})"
ready = "!document.getElementById('scan-workspace').hidden && document.getElementById('scan-image').complete && document.getElementById('scan-answer').textContent.trim() !== '—'"
scenes = [
    {'id': '01-title', 'kind': 'card', 'kicker': 'Planproof', 'title': 'Ask a floor plan how many. See exactly where.',
     'lines': ['Windows, doors, rooms and storeys, counted on the drawing itself.', 'Every counted item is marked where it is.'],
     'foot': 'Built at Junction 2026 for the Stoa, Verda and NVIDIA challenges',
     'narration': 'This is Planproof. You ask a construction drawing a counting question, like how many windows or how many bathrooms, '
                  'and it gives you the number together with the marks on the drawing that support it.'},
    {'id': '02-library', 'kind': 'app',
     'shots': [{'url': '/library.html?source=cubicasa5k', 'wait': "document.querySelectorAll('a[href*=\\'scan-drawing\\']').length > 5", 'settle': 900}],
     'narration': 'It opens the sponsor\'s whole drawing library: thousands of scanned Finnish floor plans, Swiss plans and building models. Pick any drawing and ask.'},
]
if windows:
    scenes.append({'id': '03-windows', 'kind': 'app',
                   'shots': [{'url': link(windows), 'wait': ready, 'actions': [frame, select(0)]},
                             {'actions': [select(min(3, windows['gold'] - 1))]}, {'actions': [select(windows['gold'] - 1)]}],
                   'narration': 'Here we asked how many windows. It found %d, and each one is a mark on the scan. Click a row and it shows you that window, '
                                'so you never have to take the number on trust.' % windows['new']['answer']})
if storeys:
    scenes.append({'id': '04-storeys', 'kind': 'app',
                   'shots': [{'url': link(storeys), 'wait': ready, 'actions': [frame, select(0)]}] + ([{'actions': [select(1)]}] if storeys['gold'] >= 2 else []),
                   'narration': 'It also reads the rooms. From the printed room names and a map of the plan\'s rooms, it answers questions about kitchens, saunas, bathrooms and storeys. '
                                'This sheet shows %d floors, and each floor gets its own box.' % storeys['new']['answer']})
if zero:
    scenes.append({'id': '05-zero', 'kind': 'app',
                   'shots': [{'url': link(zero), 'wait': ready, 'actions': [frame, select(0)]}],
                   'narration': 'Even a zero comes with evidence. When it says there is no %s, it shows the rooms it checked.' % zero['category'].rstrip('s')})
if args.hosted_example:
    path, question = args.hosted_example.split('|', 1)
    scenes.append({'id': '06-nvidia', 'kind': 'app',
                   'shots': [{'url': '/scan-drawing.html?' + urlencode({'path': path, 'question': question}), 'wait': ready, 'actions': [frame, select(0)]}, {'actions': [select(1)]}],
                   'narration': 'Some questions need more than the local readers, like counting showers. Those go to NVIDIA\'s Nemotron vision model, '
                                'which reasons over the drawing and marks what it counted. The answer always says which model gave it.'})
scenes.append({'id': '07-how', 'kind': 'card', 'kicker': 'How it works', 'title': 'Local readers first, NVIDIA Nemotron for the rest',
               'lines': ['1. Room labels read with OCR on the scan.', '2. Floor panels and the room map of a floor-plan detector.',
                         '3. Windows and doors read again at the drawing\'s own scale.', '4. Anything still unproven goes to Nemotron on NVIDIA.'],
               'title_size': 72,
               'narration': 'Under the hood, Planproof tries its own readers first: text recognition for room labels, a floor-plan detector for rooms and storeys, '
                            'and a second, closer look at windows and doors. Only what they cannot prove is sent to NVIDIA. That keeps answers fast, checkable and cheap.'})
scenes.append({'id': '08-close', 'kind': 'card', 'kicker': 'Planproof', 'title': 'Every count can be checked on the drawing',
               'lines': ['Open the library, pick a plan, ask how many.'],
               'narration': 'Planproof. Ask how many, and see exactly where.'})
(HERE / 'scenes.json').write_text(json.dumps({'scenes': scenes}, indent=1, ensure_ascii=False) + '\n')
words = sum(len(s['narration'].split()) for s in scenes)
print('scenes: %d, narration words: %d' % (len(scenes), words))
for s in scenes:
    print(' ', s['id'], '|', s['narration'])
