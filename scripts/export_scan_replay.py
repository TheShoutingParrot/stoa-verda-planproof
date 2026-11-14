"""Rebuild the portable holdout replay: python3 -m scripts.export_scan_replay --archive /path/to/junction-dataset.zip

The source manifest and prediction digests below are the canonical JSON SHA-256 values
from the completed candidate seal. The library pins the SHA-256 of the exported bytes.
"""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from .scan_library import ROOT, _safe_report


MANIFEST_SHA = '37c2984cafd660f1e052b8679aa488caf09b5bf963fabac2cffcca4c6a6744ac'
PREDICTIONS_SHA = '80e0fd7a2c4aca68158327b48f967da7d2d81bebf4052439959c2af78bf62290'
CANDIDATE_ID = '15f89a6f0a5826330d9fd32658cc187b5bc27bf1dcec718fc5361ac873bb3292'
UI_FIELDS = ('path', 'question', 'image_sha256', 'coordinate_system', 'origin', 'model', 'served_model',
             'provider_host', 'method', 'status', 'answer', 'evidence', 'coverage_evidence', 'reason')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def export(manifest_path, source_dir, archive):
    manifest = json.loads(manifest_path.read_bytes())
    seal = json.loads((source_dir / 'seal.json').read_bytes())
    if (sha(canonical(manifest)) != MANIFEST_SHA or seal.get('manifest_sha256') != MANIFEST_SHA
            or seal.get('arm') != 'candidate' or seal.get('completed') != 96
            or seal.get('candidate_id') != CANDIDATE_ID or seal.get('predictions_sha256') != PREDICTIONS_SHA):
        raise ValueError('Source inputs or completed candidate seal do not match the frozen run')
    rows = manifest['rows']
    if len(rows) != 96 or len({row['id'] for row in rows}) != 96 or len({r['path'] for r in rows}) != 32:
        raise ValueError('Expected 96 unique questions on 32 drawings')

    raw = []
    verified = {}
    with ZipFile(archive) as drawings:
        for row in rows:
            rid, path, question, digest = (row[k] for k in ('id', 'path', 'question', 'image_sha256'))
            if rid != sha((path+'|'+question).encode())[:16]:
                raise ValueError('Question ID does not match its drawing and prompt')
            if path not in verified:
                verified[path] = sha(drawings.read('junction-dataset/'+path))
            if verified[path] != digest:
                raise ValueError(f'Image bytes do not match the frozen digest for {path}')
            item = json.loads((source_dir/(rid+'.json')).read_bytes())
            if any(item.get(k) != row[k] for k in ('id', 'path', 'question', 'image_sha256')):
                raise ValueError('Response and frozen input do not match')
            raw.append(item)
    if sha(canonical(raw)) != PREDICTIONS_SHA:
        raise ValueError('Source predictions differ from the sealed run')

    reports = []
    for item in raw:
        if item.get('reused_original') is True:
            source = 'reused hosted response'
        else:
            source = {'local_room_labels':'local room labels', 'cubicasa_icon_segmentation':'local object detector',
                      'nemotron_direct':'hosted inference'}[item['method']]
        report = _safe_report(item, item['path'], item['image_sha256'], item['question'],
                              'Measured scan reader · '+source, sealed=True)
        if report is None:
            raise ValueError('Invalid evidence in source response')
        # _safe_report also validates and allowlists nested label/box evidence.
        reports.append({k:report[k] for k in UI_FIELDS if k in report})
    return canonical(dict(version=1, reports=reports))+b'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT/'docs/scan-holdout-inputs.json')
    parser.add_argument('--source', type=Path, default=ROOT/'.local/evaluation/scan-holdout/candidate')
    parser.add_argument('--output', type=Path, default=ROOT/'public/data/finnish/scan-holdout-replay.json')
    args = parser.parse_args()
    data = export(args.manifest,args.source,args.archive)
    args.output.write_bytes(data)
    print(f'{sha(data)}  {args.output} ({len(data):,} bytes)')


if __name__ == '__main__':
    main()
