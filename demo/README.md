# Live demo and video

## Live demo (5 minutes, no model or key needed)

```sh
python3 server.py            # with the sponsor ZIP at its default path
```

Run it with the detector's Python (`.local/scan-dev/objects/venv/bin/python server.py`) to let the audience ask new questions, and add the NVIDIA key (`hsec exec --only NEMOTRON_API_KEY -- ...`, with `NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1`) so questions the local readers cannot prove go to Nemotron.

1. **Open the result card.** `docs/scan-next-evaluation.md` gives the sealed before/after numbers. Say what was held back and that the baseline was sealed first.
2. **Windows.** Open the window link in `demo/links.md`. Click through the marks: each one sits on a window of the original PNG.
3. **A deferred question that now has an answer.** Open the storey or kitchen link. The reason line says it came from the room map and the label OCR.
4. **A zero with evidence.** Open the zero link. The evidence list shows the rooms that were examined, not an empty box.
5. **Ask live.** Type "How many doors are shown on this floor plan?" and press **Run count**. The first object question on a drawing takes 5 to 20 seconds on an Apple M-series GPU; later questions on the same drawing reuse the reading.
6. **NVIDIA fallback (key configured).** Ask "How many showers and bathtubs are drawn on this floor plan in total?". No local reader covers showers, so the answer comes from Nemotron 3.5 Super VL on NVIDIA's endpoint and its source line says so. Shower questions use Nemotron's reasoning pass, which takes 20 to 60 seconds; ask it while you talk through another result.

Fallback if the network is down: every link in `demo/links.md` replays a sealed answer without a model or a key.

## Video

```sh
python3 server.py &                                  # saved results only
python3 demo/make_scenes.py --paired <paired-rows.json> --hosted-example "<drawing path>|<question>"
python3 demo/build_video.py                          # macOS voice; or --audio-dir with recorded or AI narration
hsec exec --only ELEVENLABS_API_KEY -- python3 demo/voice_elevenlabs.py   # ElevenLabs narration into demo/out/voice
python3 demo/build_video.py --skip-capture --audio-dir demo/out/voice
```

The video explains what Planproof does, filmed from real answers: `make_scenes.py` picks its example drawings from the scored result files. `build_video.py` captures the scenes from the running app with a headless Chromium browser (`demo/capture.mjs`), narrates them with a macOS system voice or the audio files given, and writes `demo/out/planproof-demo.mp4` with subtitles in `demo/out/planproof-demo.srt`. The output folder is ignored by git.
