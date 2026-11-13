# Finnish drawing credit

`finnish/high_quality_architectural-13066.png` is an unmodified 378 × 521 PNG from the full Stoa Junction drawing set, `data/cubicasa5k/high_quality_architectural-13066.png`. SHA-256: `f1cf7f64462f9687e41b4a5848534cc409c32212cc3c6ae02b9e315039d6f6af`.

© 2019 CubiCasa. Ahti Kalervo, Juha Ylioinas, Markus Häikiö, Antti Karhu, Juho Kannala. *CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis*, SCIA 2019. The image and its sponsor-supplied evaluation question are licensed under [Creative Commons Attribution-NonCommercial-ShareAlike 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), separately from the application code. Commercial reuse requires appropriate permission. The app draws its evidence overlay separately from the original file. [Upstream dataset](https://zenodo.org/records/2613548) · [Full Junction archive](https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip).

## Reproduce the inference

Set `NEMOTRON_BASE_URL` to the Verda Junction **API base including its version prefix**, or a complete chat completions URL, and place the matching endpoint credential in `NEMOTRON_API_KEY`. If the endpoint exposes its own alias for the exact Nemotron 3.5 Super VL model, set `NEMOTRON_MODEL` to that alias. Keep credentials on the server. The default model ID is `nvidia/nemotron-3.5-super-vl-120b-a12b`.

```sh
python3 scripts/nemotron.py public/data/finnish/high_quality_architectural-13066.png \
  --output public/data/finnish/run.json
```

The default prompt uses the sponsor’s Finnish bedroom question. The runner sends the drawing and question only; the reference count stays outside inference. It returns `answered` (exit 0), `unknown` for insufficient visual evidence (exit 1), or `unavailable` for service or configuration failure (exit 2). Successful items carry a visible label and `[left, top, right, bottom]` normalized independently to 0–1000 from the image’s top-left. Hosting the output under `public/` makes it visible to visitors. Use a different output file to compare runs. Hosted alternatives require their own HTTPS base, exact deployed model ID and matching key, supplied via `--base-url`, `--model` and `--api-key-env`.

## Reproduce the local OCR comparison

The committed [`parse-run.json`](finnish/parse-run.json) records a real, offline Apple Silicon run of NVIDIA Nemotron Parse v1.2 using an 8-bit MLX conversion. It transcribes text from pixels. A Finnish bedroom-label matcher counts `MH`, `makuuh.` and `makuuhuone`; Tesseract locates matching labels and a green-outline check rejects neighboring text. The whole sheet determines the count. Four overlapping crops document how the transcription changes with scale. On this drawing, Nemotron's box covers the plan and Tesseract supplies the tighter word box. The outside unit's partially visible label is not counted. This is one measured sample. [NVIDIA model](https://huggingface.co/nvidia/NVIDIA-Nemotron-Parse-v1.2) · [Pinned MLX conversion](https://huggingface.co/mlx-community/Nemotron-Parse-v1.2-8bit/tree/92ebb2122d413426995ea92340ac847dad6ec274).

On an Apple Silicon Mac with Python 3.12, `uv`, and Tesseract 5.5.3 with English data:

```sh
uv venv --python 3.12 .local/parse-venv
uv pip install --python .local/parse-venv/bin/python 'mlx-vlm==0.7.12' 'mlx==0.32.4' 'pillow==13.0.0'
.local/parse-venv/bin/python scripts/local_parse.py public/data/finnish/high_quality_architectural-13066.png --output .local/repeated-parse.json
```

The first run downloads roughly 1.5 GiB of weights. Pass `--weights /path/to/pinned/checkpoint` for offline use with an existing copy. The reported model latency covers the warm whole-sheet run. The JSON lists model-load time and separate times for each crop.
