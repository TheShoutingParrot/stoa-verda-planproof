"""Reproduce either bundled replay from its immutable predictions and the sponsor ZIP.

Run `python3 -m scripts.export_scan_replay --cohort revision --archive /path/to/junction-dataset.zip`
for the 398-question offline evaluation. Use `--cohort holdout` for the historical 96 responses.
The source seals use canonical JSON; the library pins the SHA-256 of each exported file.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from .scan_library import COORDS, ROOT, _safe_report


MANIFEST_SHA = '37c2984cafd660f1e052b8679aa488caf09b5bf963fabac2cffcca4c6a6744ac'
PREDICTIONS_SHA = '80e0fd7a2c4aca68158327b48f967da7d2d81bebf4052439959c2af78bf62290'
CANDIDATE_ID = '15f89a6f0a5826330d9fd32658cc187b5bc27bf1dcec718fc5361ac873bb3292'
REVISION_MANIFEST_SHA = '62781971de4e842eccf0070119d4721b183339bdc3f7dd07fd904d82e6b7d12c'
REVISION_SEALS = {
    'old': '56b8ba5d7435e0b00031924dabd010b4ae79cd68218e192298c54e2665c84a7b',
    'new': 'af395f99c6f246e313cb75ed4c185265e0298f51b5a37b69d58b1f09deeefc91',
}
LOCAL_METHODS = {
    'local_room_labels': ('local room labels', 'Room label OCR'),
    'local_storey_panels': ('local floor panels', 'Floor plan and caption reader'),
    'cubicasa_icon_segmentation': ('local object detector', 'CubiCasa5K'),
}
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


def zero_coverage(source_dir, config_sha, archive, row):
    # The evaluator retained the count but removed auxiliary coverage for zeroes.
    # Run only the verified room OCR on this one verified PNG, through an isolated
    # interpreter. No hosted client, scorer or object-detection weights are imported.
    root = source_dir/'new'
    config = json.loads((root/'config.json').read_bytes())
    if sha(canonical(config)) != config_sha:
        raise ValueError('Room-reader configuration differs from its seal')
    package = root/'src/scripts'
    for module in ('scan_rooms.py','scan_room_labels.py','scan_storeys.py'):
        if sha((package/module).read_bytes()) != config['source_sha256']['scripts/'+module]:
            raise ValueError('Room-reader source differs from its seal')
    if (package/'__init__.py').read_bytes() != b'':
        raise ValueError('Unexpected snapshot package initializer')
    with ZipFile(archive) as drawings:
        image = drawings.read('junction-dataset/'+row['path'])
    if sha(image) != row['image_sha256']:
        raise ValueError('Studio-zero image differs from the frozen input')
    program = ("import json,sys; sys.path.insert(0,sys.argv[1]); from scripts.scan_rooms import predict; "
               "print(json.dumps(predict(sys.stdin.buffer.read(),sys.argv[2]),allow_nan=False))")
    replay = subprocess.run([sys.executable,'-I','-B','-c',program,str(package.parent.resolve()),row['question']],
                            input=image, capture_output=True, check=True, timeout=180)
    result = json.loads(replay.stdout)
    if (not isinstance(result,dict) or result.get('status') != 'answered' or result.get('answer') != 0
            or result.get('method') != 'local_room_labels' or not result.get('coverage_evidence')):
        raise ValueError('Could not reproduce the sealed zero and its printed evidence')
    return result['coverage_evidence']


def export_revision(manifest_path, source_dir, archive):
    manifest = json.loads(manifest_path.read_bytes())
    if sha(canonical(manifest)) != REVISION_MANIFEST_SHA or len(manifest['rows']) != 398 or manifest['images'] != 48:
        raise ValueError('The revision manifest does not match the frozen inputs')
    seals = {}
    for arm in ('old', 'new'):
        seal = json.loads((source_dir/arm/'seal.json').read_bytes())
        if (sha(canonical(seal)) != REVISION_SEALS.get(arm) or seal.get('rows') != len(manifest['rows'])
                or seal.get('manifest_sha256') != REVISION_MANIFEST_SHA):
            raise ValueError('The completed revision seal does not match: '+arm)
        seals[arm] = seal

    predictions = {}
    by_image = {}
    directory = source_dir/'new'/'outputs'
    with ZipFile(archive) as drawings:
        for row in manifest['rows']:
            rid, path, question, digest = (row[k] for k in ('id', 'path', 'question', 'image_sha256'))
            if rid in predictions or rid != sha((path+'|'+question).encode())[:16]:
                raise ValueError('Duplicate or invalid drawing-question ID')
            if path not in by_image:
                by_image[path] = sha(drawings.read('junction-dataset/'+path))
            item = json.loads((directory/(rid+'.json')).read_bytes())
            if by_image[path] != digest or any(item.get(k) != row[k] for k in ('id','question','image_sha256')):
                raise ValueError('Prediction, frozen question or original drawing differs')
            predictions[rid] = item
    if (len(by_image) != 48 or len(list(directory.glob('*.json'))) != len(predictions)
            or sha(canonical(predictions)) != seals['new']['predictions_sha256']):
        raise ValueError('Saved revision predictions do not match the seal')

    reports = []
    for row in manifest['rows']:
        item = predictions[row['id']]
        if item['status'] != 'answered':
            continue
        source, model = LOCAL_METHODS[item['method']]
        path = row['path']
        enriched = dict(item, path=path, image=Path(path).name, model=model, coordinate_system=COORDS)
        if item['method'] == 'local_room_labels' and item['answer'] == 0:
            enriched['coverage_evidence'] = zero_coverage(source_dir, seals['new']['config_sha256'], archive, row)
            enriched['reason'] = 'The sealed zero was reproduced by the frozen room reader. The marks show its printed evidence.'
        if item['method'] == 'cubicasa_icon_segmentation' and item['answer'] == 0:
            enriched['reason'] = 'The local detector returned no qualifying symbols for this category on the scan.'
        report = _safe_report(enriched, path, row['image_sha256'], row['question'],
                              'Measured scan revision · '+source, sealed=True)
        if report is None:
            raise ValueError('Invalid evidence for measured revision answer')
        reports.append({k:report[k] for k in UI_FIELDS if k in report})
    return canonical(dict(version=1, reports=reports))+b'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', choices=('holdout','revision'), default='holdout')
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    name = 'scan-'+args.cohort
    manifest = args.manifest or ROOT/'docs'/(name+'-inputs.json')
    source = args.source or ROOT/'.local/evaluation'/name
    if args.cohort == 'holdout':
        data = export(manifest, source if args.source else source/'candidate', args.archive)
    else:
        data = export_revision(manifest, source, args.archive)
    args.output = args.output or ROOT/'public/data/finnish'/(name+'-replay.json')
    args.output.write_bytes(data)
    print(f'{sha(data)}  {args.output} ({len(data):,} bytes)')


if __name__ == '__main__':
    main()
