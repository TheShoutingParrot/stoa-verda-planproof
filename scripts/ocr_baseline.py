"""Measure native and 4x whole-sheet Tesseract recognition of Finnish bedroom labels."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unicodedata

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "public/data/finnish/high_quality_architectural-13066.png"
OUTPUT = ROOT / "public/data/finnish/ocr-baseline.json"
LABELS = ("mh", "makuuh", "makuuhuone")


def normalize(token):
    return "".join(ch for ch in unicodedata.normalize("NFKC", token).casefold() if ch.isalpha())


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        following = [i]
        for j, y in enumerate(b, start=1):
            following.append(min(row[j] + 1, following[-1] + 1, row[j - 1] + (x != y)))
        row = following
    return row[-1]


def run_ocr(image, scale):
    data = io.BytesIO()
    image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS).save(data, "PNG")
    command = ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "11", "tsv"]
    process = subprocess.run(command, input=data.getvalue(), capture_output=True, check=True,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    rows = csv.DictReader(io.StringIO(process.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE)
    tokens, candidates = 0, []
    for row in rows:
        if row["level"] != "5" or not row["text"].strip():
            continue
        tokens += 1
        token = normalize(row["text"])
        target = min(LABELS, key=lambda label: distance(label, token))
        edits = distance(target, token)
        if edits and (edits > 1 or len(target) < 5):
            continue
        x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
        candidates.append({
            "text": row["text"], "expectedLabel": target.upper(), "match": "fuzzy" if edits else "exact",
            "editDistance": edits, "ocrConfidence": float(row["conf"]),
            "box": [x / scale, y / scale, (x + w) / scale, (y + h) / scale],
        })
    return {"scale": scale, "wordsRead": tokens,
            "exactLabels": sum(c["match"] == "exact" for c in candidates), "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=IMAGE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with Image.open(args.image) as original:
        gray = original.convert("L")
    version = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, check=True)
    result = {
        "engine": version.stdout.splitlines()[0], "source": args.image.name,
        "imageSha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "imageSize": [gray.width, gray.height],
        "method": "Whole page, grayscale at 1x and Lanczos-resampled 4x. Tesseract eng, sparse text (--psm 11), TSV word boxes. Same settings and no cropping for both runs.",
        "matching": "Casefold letters, ignoring punctuation. Exact MH, MAKUUH or MAKUUHUONE. Allow one single-character insertion, deletion or substitution only for long forms. No hand-placed boxes.",
        "coordinates": "Original image pixels, [left, top, right, bottom], top-left origin.",
        "interpretation": "Page-wide text candidates. Apartment boundary and room membership unverified. Candidate count is not a bedroom count.",
        "runs": [run_ocr(gray, scale) for scale in (1, 4)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for run in result["runs"]:
        print(f"{run['scale']}x: {run['wordsRead']} tokens, {run['exactLabels']} exact, {len(run['candidates'])} candidates")


if __name__ == "__main__":
    main()
