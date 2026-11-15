"""Narrate demo/scenes.json with OpenAI text-to-speech, one MP3 per scene, for build_video.py --audio-dir.

usage: hsec exec --only OPENAI_API_KEY -- python3 demo/voice_openai.py [--voice NAME] [--model NAME] [--out DIR] [--force]

Only the narration text of each scene is sent. Existing files are kept unless --force is given.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TONE = ('Voice: a calm, warm documentary narrator presenting a product demo. '
        'Pace: unhurried and clear, with short natural pauses at full stops. '
        'Read numbers naturally. Sound confident and friendly, never salesy.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default='cedar')
    parser.add_argument('--model', default='gpt-4o-mini-tts')
    parser.add_argument('--out', type=Path, default=HERE / 'out' / 'voice-openai')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        sys.exit('Set OPENAI_API_KEY in the environment (for example with hsec exec).')
    scenes = json.loads((HERE / 'scenes.json').read_text())['scenes']
    args.out.mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        target = args.out / (scene['id'] + '.mp3')
        if target.exists() and not args.force:
            continue
        body = {'model': args.model, 'voice': args.voice, 'input': scene['narration'],
                'instructions': TONE, 'response_format': 'mp3'}
        request = urllib.request.Request('https://api.openai.com/v1/audio/speech', data=json.dumps(body).encode(),
                                         method='POST', headers={'Authorization': 'Bearer ' + key,
                                                                 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                target.write_bytes(response.read())
        except urllib.error.HTTPError as error:
            sys.exit('%s: HTTP %d %s' % (scene['id'], error.code, error.read()[:300].decode(errors='replace')))
        print('voiced', scene['id'], target.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
