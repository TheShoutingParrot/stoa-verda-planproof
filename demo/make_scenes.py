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
    {'id': '01-title', 'kind': 'card', 'kicker': 'Planproof', 'title': 'Counts on construction drawings, with the evidence you can click',
     'lines': ['Local readers answer what the drawing itself can prove.', 'NVIDIA Nemotron answers the rest.'],
     'foot': 'Junction 2026 · Stoa, Verda and NVIDIA challenges',
     'narration': 'Planproof answers quantity questions about construction drawings. Every count links to the marks on the drawing that support it.'},
]
if windows:
    scenes.append({'id': '02-windows', 'kind': 'app',
                   'shots': [{'url': link(windows), 'wait': ready, 'actions': [frame, select(0)]},
                             {'actions': [select(min(3, windows['gold'] - 1))]}, {'actions': [select(windows['gold'] - 1)]}],
                   'narration': 'This floor plan was held back for the test. The new reader reads windows and doors a second time, at a scale set by the drawing\'s own doors. '
                                'It marks all %d windows. The previous reader counted %d.' % (windows['gold'], windows['old']['answer'])})
if storeys:
    scenes.append({'id': '03-storeys', 'kind': 'app',
                   'shots': [{'url': link(storeys), 'wait': ready, 'actions': [frame, select(0)]}] + ([{'actions': [select(1)]}] if storeys['gold'] >= 2 else []),
                   'narration': 'Questions the old reader had to defer now get an answer from the room map of the same detector. '
                                'Here it counts %d %s, one box for each.' % (storeys['gold'], 'storeys' if storeys['gold'] != 1 else 'storey')})
if zero:
    scenes.append({'id': '04-zero', 'kind': 'app',
                   'shots': [{'url': link(zero), 'wait': ready, 'actions': [frame, select(0)]}],
                   'narration': 'A zero is an answer too. For %s, the reader shows the rooms it examined before it says none.' % zero['category']})
scenes.append({'id': '05-result', 'kind': 'card', 'kicker': 'Sealed comparison · %d drawings, %d questions' % (drawings, len(rows)),
               'title': 'Exact answers, offline, on drawings held back from development',
               'metrics': [{'value': before['exact'], 'label': 'previous reader', 'was': True}, {'value': after['exact'], 'label': 'new reader'},
                           {'value': '%d%%' % share(after), 'label': 'of its answers exact (was %d%%)' % share(before)}],
               'foot': 'Baseline sealed before any tuning · one scoring · protocol in docs/scan-next-protocol.md',
               'narration': 'On %d drawings held back from development, with %d questions, exact answers rose from %d to %d with no hosted model at all. '
                            '%d percent of the answers it gives are exact, up from %d.' % (drawings, len(rows), before['exact'], after['exact'], share(after), share(before))})
if args.hybrid:
    h = json.loads(args.hybrid.read_text())
    arms, calls = h['arms'], h['hosted_calls_needed']
    best = 'hybrid_after_shower_route' if 'hybrid_after_shower_route' in arms else 'hybrid_after'
    scenes.append({'id': '06-nvidia', 'kind': 'card', 'kicker': 'On NVIDIA hardware · Nemotron 3.5 Super VL',
                   'title': 'Local evidence first, NVIDIA for the rest',
                   'metrics': [{'value': arms['nemotron_alone']['exact'], 'label': 'Nemotron alone, exact of %d' % h['prompts'], 'was': True},
                               {'value': arms[best]['exact'], 'label': 'Planproof readers with Nemotron behind them'},
                               {'value': calls[best], 'label': 'NVIDIA calls instead of %d' % calls['nemotron_alone']}],
                   'foot': 'Same %d questions · hosted on integrate.api.nvidia.com' % h['prompts'],
                   'narration': 'What the local readers cannot prove goes to Nemotron on NVIDIA\'s endpoint. Nemotron alone gets %d of the %d questions exactly right. '
                                'With Planproof\'s readers in front, and Nemotron reasoning over small shower symbols, the same endpoint reaches %d, with %d calls instead of %d.'
                                % (arms['nemotron_alone']['exact'], h['prompts'], arms[best]['exact'], calls[best], calls['nemotron_alone'])})
if args.hosted_example:
    path, question = args.hosted_example.split('|', 1)
    scenes.append({'id': '07-hosted', 'kind': 'app',
                   'shots': [{'url': '/scan-drawing.html?' + urlencode({'path': path, 'question': question}), 'wait': ready, 'actions': [frame]}],
                   'narration': 'In the live app, a question no local reader covers is answered by Nemotron, and the source of every answer is shown.'})
scenes.append({'id': '08-close', 'kind': 'card', 'kicker': 'Planproof', 'title': 'Every count can be checked on the drawing',
               'lines': ['Open the drawing library, pick a scan, ask a count.', 'Code, tests and the sealed protocol are in the repository.'],
               'narration': 'Planproof. Every count can be checked on the drawing.'})
(HERE / 'scenes.json').write_text(json.dumps({'scenes': scenes}, indent=1, ensure_ascii=False) + '\n')
words = sum(len(s['narration'].split()) for s in scenes)
print('scenes: %d, narration words: %d' % (len(scenes), words))
for s in scenes:
    print(' ', s['id'], '|', s['narration'])
