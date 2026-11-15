"""Narrate demo/scenes.json with an ElevenLabs voice, one MP3 per scene, for build_video.py --audio-dir.

usage: hsec exec --only ELEVENLABS_API_KEY -- python3 demo/voice_elevenlabs.py [--voice ID] [--out DIR] [--check]

--check only prints the characters (credits) needed and the account's remaining quota.
Existing files are kept, so a run that stopped can be resumed. Each request passes the neighbouring
scenes' text, so the delivery flows across cuts.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = 'https://api.elevenlabs.io/v1'
# "Max - eLearning, Documentary, Friendly": a clear American documentary narrator.
DEFAULT_VOICE = 'Gfpl8Yo74Is0W6cPUWWT'


def call(path, key, body=None):
    request = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                     method='POST' if body is not None else 'GET',
                                     headers={'xi-api-key': key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice', default=DEFAULT_VOICE)
    parser.add_argument('--model', default='eleven_multilingual_v2')
    parser.add_argument('--out', type=Path, default=HERE / 'out' / 'voice')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    key = os.environ.get('ELEVENLABS_API_KEY')
    if not key:
        sys.exit('Set ELEVENLABS_API_KEY in the environment (for example with hsec exec).')
    scenes = json.loads((HERE / 'scenes.json').read_text())['scenes']
    needed = sum(len(s['narration']) for s in scenes if not (args.out / (s['id'] + '.mp3')).exists())
    quota = json.loads(call('/user/subscription', key))
    left = quota['character_limit'] - quota['character_count']
    print('characters needed: %d, left this period: %d (resets %s)'
          % (needed, left, time.strftime('%Y-%m-%d %H:%M', time.localtime(quota.get('next_character_count_reset_unix', 0)))))
    if args.check:
        return
    args.out.mkdir(parents=True, exist_ok=True)
    settings = {'stability': 0.45, 'similarity_boost': 0.8, 'style': 0.15, 'use_speaker_boost': True}
    for index, scene in enumerate(scenes):
        target = args.out / (scene['id'] + '.mp3')
        if target.exists():
            continue
        body = {'text': scene['narration'], 'model_id': args.model, 'voice_settings': settings,
                'previous_text': scenes[index - 1]['narration'] if index else None,
                'next_text': scenes[index + 1]['narration'] if index + 1 < len(scenes) else None}
        try:
            audio = call('/text-to-speech/%s?output_format=mp3_44100_128' % args.voice, key, body)
        except urllib.error.HTTPError as error:
            sys.exit('%s: HTTP %d %s' % (scene['id'], error.code, error.read()[:300].decode(errors='replace')))
        target.write_bytes(audio)
        print('voiced', scene['id'], len(audio), 'bytes')


if __name__ == '__main__':
    main()
