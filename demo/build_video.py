"""Build the narrated demo video from demo/scenes.json.

usage: python3 demo/build_video.py [--voice Samantha] [--skip-capture] [--audio-dir DIR]

Each scene is a title card (rendered from a template) or a page of the running Planproof server
(python3 server.py, saved results only: no model and no key are needed). Frames are captured with a
headless Chromium browser (demo/capture.mjs), narration is synthesised with the macOS `say` voice or
taken from --audio-dir/<scene id>.(wav|mp3|aiff) when a file is there, and ffmpeg joins the scenes.
Outputs: demo/out/planproof-demo.mp4 and demo/out/planproof-demo.srt.
"""
import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
SIZE = (1920, 1080)
# Fit the whole drawing beside the result panel in a 1080p frame.
APP_CSS = 'body{zoom:1.3} .library-main{max-width:1440px} .scan-viewport{max-height:600px} .topbar,.back-link,footer{display:none}'
CARD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%}}
body{{background:#153c32;color:#f4f1e8;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;display:flex;flex-direction:column;justify-content:center;padding:0 150px;box-sizing:border-box}}
.kicker{{font-size:30px;letter-spacing:.16em;text-transform:uppercase;color:#9fd3b6;margin:0 0 26px}}
h1{{font-size:{title_size}px;line-height:1.08;margin:0 0 34px;font-weight:700;max-width:1500px}}
p.line{{font-size:40px;line-height:1.35;margin:0 0 16px;color:#dfe8e1;max-width:1500px}}
.metrics{{display:flex;gap:70px;margin:38px 0 26px}}
.metric .value{{font-size:118px;font-weight:700;line-height:1;color:#fff}}
.metric .label{{font-size:30px;line-height:1.3;color:#b9d6c6;margin-top:14px;max-width:440px}}
.metric.was .value{{color:#8fb3a1}}
.foot{{position:absolute;left:150px;bottom:64px;font-size:26px;color:#8fb3a1}}
</style></head><body>
<p class="kicker">{kicker}</p><h1>{title}</h1>{lines}<div class="metrics">{metrics}</div><div class="foot">{foot}</div>
</body></html>"""


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def card_html(scene):
    esc = html.escape
    lines = ''.join('<p class="line">%s</p>' % esc(line) for line in scene.get('lines', []))
    metrics = ''.join('<div class="metric%s"><div class="value">%s</div><div class="label">%s</div></div>'
                      % (' was' if m.get('was') else '', esc(str(m['value'])), esc(m['label'])) for m in scene.get('metrics', []))
    return CARD.format(kicker=esc(scene.get('kicker', 'Planproof')), title=esc(scene['title']), lines=lines, metrics=metrics,
                       foot=esc(scene.get('foot', '')), title_size=scene.get('title_size', 84))


def duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]).stdout.strip())


def stamp(seconds):
    millis = round(seconds * 1000)
    return '%02d:%02d:%02d,%03d' % (millis // 3600000, millis // 60000 % 60, millis // 1000 % 60, millis % 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default='Samantha')
    parser.add_argument('--rate', type=int, default=172, help='words per minute for the system voice')
    parser.add_argument('--skip-capture', action='store_true')
    parser.add_argument('--audio-dir', type=Path, help='pre-recorded narration per scene id')
    parser.add_argument('--base', default='http://127.0.0.1:4179')
    args = parser.parse_args()
    scenes = json.loads((HERE / 'scenes.json').read_text())['scenes']
    frames, cards, audio, clips = OUT / 'frames', OUT / 'cards', OUT / 'audio', OUT / 'clips'
    for folder in (frames, cards, audio, clips):
        folder.mkdir(parents=True, exist_ok=True)

    shots = []
    for scene in scenes:
        if scene['kind'] == 'card':
            page = cards / (scene['id'] + '.html')
            page.write_text(card_html(scene))
            shots.append({'name': scene['id'], 'url': page.resolve().as_uri(), 'settle': 300})
            scene['frames'] = [scene['id']]
        else:
            scene['frames'] = []
            for index, shot in enumerate(scene['shots']):
                name = '%s-%d' % (scene['id'], index)
                shots.append(dict(shot, name=name))
                scene['frames'].append(name)
    if not args.skip_capture:
        board = OUT / 'storyboard.json'
        board.write_text(json.dumps({'size': SIZE, 'css': APP_CSS, 'shots': shots}, indent=1))
        subprocess.run(['node', str(HERE / 'capture.mjs'), str(board), str(frames), '--base', args.base], check=True)

    listing, captions, clock = [], [], 0.0
    for scene in scenes:
        voice = None
        if args.audio_dir:
            voice = next((p for p in (args.audio_dir / (scene['id'] + ext) for ext in ('.wav', '.mp3', '.aiff')) if p.exists()), None)
        if voice is None:
            voice = audio / (scene['id'] + '.aiff')
            run(['say', '-v', args.voice, '-r', str(args.rate), '-o', str(voice), scene['narration']])
        lead, tail = 0.35, 0.55
        spoken = duration(voice)
        total = lead + spoken + tail
        each = total / len(scene['frames'])
        clip = clips / (scene['id'] + '.mp4')
        command = ['ffmpeg', '-y', '-loglevel', 'error']
        for name in scene['frames']:
            command += ['-loop', '1', '-t', '%.3f' % each, '-i', str(frames / (name + '.png'))]
        command += ['-i', str(voice)]
        count = len(scene['frames'])
        scale = ''.join('[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x153c32,setsar=1,fps=30[v%d];'
                        % (i, SIZE[0], SIZE[1], SIZE[0], SIZE[1], i) for i in range(count))
        joined = ''.join('[v%d]' % i for i in range(count)) + 'concat=n=%d:v=1:a=0,fade=t=in:st=0:d=0.3,fade=t=out:st=%.3f:d=0.3[v];' % (count, total - 0.3)
        sound = '[%d:a]adelay=%d:all=1,apad=whole_dur=%.3f,aresample=48000[a]' % (count, round(lead * 1000), total)
        command += ['-filter_complex', scale + joined + sound, '-map', '[v]', '-map', '[a]', '-t', '%.3f' % total,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '160k', '-ac', '2', str(clip)]
        run(command)
        listing.append("file '%s'" % clip.resolve())
        captions.append('%d\n%s --> %s\n%s\n' % (len(captions) + 1, stamp(clock + lead), stamp(clock + lead + spoken), scene['narration']))
        clock += total
    (OUT / 'clips.txt').write_text('\n'.join(listing) + '\n')
    target = OUT / 'planproof-demo.mp4'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(OUT / 'clips.txt'), '-c', 'copy', '-movflags', '+faststart', str(target)])
    (OUT / 'planproof-demo.srt').write_text('\n'.join(captions))
    print('%s  %.1f s  %.1f MB' % (target, duration(target), target.stat().st_size / 1e6))


if __name__ == '__main__':
    sys.exit(main())
