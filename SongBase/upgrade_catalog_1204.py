#!/usr/bin/env python3
"""Resume the 1,204-song catalog upgrade using Flowset's existing backend."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import shutil
import sys
import math
import importlib.util
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
BACKEND = Path('/Users/kaluozheng/MusicPlayer-FlowSystem/audio_backend')
RUN = ROOT / 'catalog-upgrade-2026-10-11'
EXPECTED = 1204
EXTRACTION = RUN / 'extraction'
MANIFEST = RUN / 'input-manifest.json'
sys.path.insert(0, str(BACKEND))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    separators=(',', ':')) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def prepare():
    if MANIFEST.exists():
        result = read(MANIFEST)
        assert len(result['tracks']) == EXPECTED
        print(f"Frozen inputs already exist: {EXPECTED}", flush=True)
        return result
    from audio_io import safe_track_id
    from musicbase_batch import compact_analysis_for_musicbase
    import build_annotation_gap_report as gap
    songs = gap.load_songbase()
    tags = read(ROOT / 'song_tags.json')['tracks']
    pending = set(read(ROOT / '待重录清单.json')['tracks'])
    discarded = set(read(ROOT / '待舍弃归档清单.json')['tracks'])
    with (ROOT / 'Flow衔接与ZMPD补标缺口清单.csv').open(encoding='utf-8-sig', newline='') as source:
        rows = [r for r in csv.DictReader(source) if r['readiness'] == '可立即补标']
    assert len(rows) == EXPECTED, f'Candidate pool changed: {len(rows)}'
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / 'input').mkdir(exist_ok=True)
    EXTRACTION.mkdir(exist_ok=True)
    baseline = RUN / '歌曲特征-480首-升级前.json'
    shutil.copy2(ROOT / '歌曲特征.json', baseline)
    snapshots = RUN / 'sources'
    snapshots.mkdir(exist_ok=True)
    for path in (ROOT / 'song_tags.json', ROOT / 'song_base_by_artist.json',
                 ROOT / 'song_identity_aliases.json', ROOT / 'Flow衔接与ZMPD补标缺口清单.csv',
                 PROJECT / 'ZMPD-模型预测开发/manifests/training-manifest.json',
                 PROJECT / 'Flowset-个人审美打标-Demo/flowset_transition_analysis_rows.csv'):
        shutil.copy2(path, snapshots / path.name)
    tracks = []
    for index, row in enumerate(sorted(rows, key=lambda r: r['track_id'])):
        identity = row['track_id']
        assert identity in songs and identity in tags and identity not in pending | discarded
        assert row['formal_tag'] == 'True' and row['audio_status'] == 'unique'
        names = row['audio_files'].split(' | ')
        assert len(names) == 1
        audio = ROOT / 'SongResources' / names[0]
        assert audio.is_file() and audio.stat().st_size > 0
        assert audio.resolve().is_relative_to((ROOT / 'SongResources').resolve())
        sha = digest(audio)
        link = RUN / 'input' / audio.name
        if not link.exists():
            os.link(audio, link)
        tracks.append({**songs[identity], 'filename': audio.name, 'audioPath': str(audio),
                       'audioFileSize': audio.stat().st_size, 'audioSha256': sha,
                       'audioAnalysisId': safe_track_id(link, sha), 'tag': tags[identity]})
        if (index + 1) % 100 == 0:
            print(f'Input hash validation {index + 1}/{EXPECTED}', flush=True)
    assert len({t['filename'] for t in tracks}) == EXPECTED
    assert len({t['track_id'] for t in tracks}) == EXPECTED
    by_hash = {t['audioSha256']: t for t in tracks}
    assert len(by_hash) == EXPECTED, 'Duplicate audio content must be reviewed'
    seed_sources = [
        Path('/Users/kaluozheng/.codex/visualizations/2026/10/01/01a0f5e6-a32f-75c1-a678-4660d6b684d0/zmpd-acoustic-features'),
        PROJECT / 'ZMPD-模型预测开发/features/sixth-extraction',
        PROJECT / 'ZMPD-模型预测开发/features/seventh-extraction',
    ]
    reused = {}
    source_receipts = []
    for folder in seed_sources:
        analysis_path = folder / 'compact-v3-analysis.json'
        feature_path = folder / 'personal-features-v2.json'
        if not analysis_path.exists() or not feature_path.exists():
            continue
        collection, dataset = read(analysis_path), read(feature_path)
        features = {t['id']: t for t in dataset['tracks']}
        source_receipts.append({'analysis': str(analysis_path), 'analysisSha256': digest(analysis_path),
                                'features': str(feature_path), 'featuresSha256': digest(feature_path)})
        for original in collection['tracks']:
            info = original['track']
            target = by_hash.get(info.get('fileSummary', {}).get('sha256'))
            if not target or info.get('fileSummary', {}).get('sizeBytes') != target['audioFileSize']:
                continue
            feature = features.get(info['id'])
            if not feature:
                continue
            analysis = compact_analysis_for_musicbase(copy.deepcopy(original))
            analysis['track'].update(id=target['audioAnalysisId'], filename=target['filename'])
            feature = copy.deepcopy(feature)
            feature.update(id=target['audioAnalysisId'], filename=target['filename'],
                           fileSize=target['audioFileSize'], selections={}, completed=False, confidence=None)
            reused[target['filename']] = {'analysis': analysis, 'feature': feature,
                                         'featureSchemas': dataset['featureSchemas']}
    checkpoint = EXTRACTION / 'track-checkpoints.ndjson'
    with checkpoint.open('w', encoding='utf-8') as destination:
        for name in sorted(reused):
            destination.write(json.dumps(reused[name], ensure_ascii=False, allow_nan=False,
                                         separators=(',', ':')) + '\n')
    value = {'schemaVersion': 'songbase.catalog-upgrade-input/v1',
             'createdAt': datetime.now(timezone.utc).isoformat(), 'tracks': tracks,
             'summary': {'targets': EXPECTED, 'reusedV3': len(reused),
                         'needsExtraction': EXPECTED - len(reused),
                         'genres': dict(Counter(t['tag']['genre'] for t in tracks))},
             'baseline': {'path': str(baseline), 'sha256': digest(baseline)},
             'reusedFeatureSources': source_receipts}
    write(MANIFEST, value)
    print(json.dumps(value['summary'], ensure_ascii=False), flush=True)
    return value


def extract(max_tracks):
    from musicbase_batch import run_musicbase_batch
    prepare()
    result = run_musicbase_batch(RUN / 'input', EXTRACTION, max_tracks=max_tracks,
                                minimum_memory_free_percent=20, track_timeout_seconds=900,
                                stop_file=RUN / 'STOP')
    print(json.dumps(result['summary'], ensure_ascii=False), flush=True)


def extract_partition(index):
    from musicbase_batch import run_musicbase_batch
    result = run_musicbase_batch(RUN / f'worker-{index}/input', RUN / f'worker-{index}/extraction',
                                max_tracks=EXPECTED, minimum_memory_free_percent=30,
                                track_timeout_seconds=900, stop_file=RUN / 'STOP-WORKERS')
    return result['summary']


def extract_parallel():
    """Three isolated, resumable single-track workers; never share append files."""
    from musicbase_batch import _read_records, _write_aggregate
    manifest = prepare()
    records = _read_records(EXTRACTION / 'track-checkpoints.ndjson')
    complete = {r['analysis']['track']['filename'] for r in records}
    missing = [t for t in manifest['tracks'] if t['filename'] not in complete]
    for position, track in enumerate(missing):
        folder = RUN / f'worker-{position % 3}/input'
        folder.mkdir(parents=True, exist_ok=True)
        link = folder / track['filename']
        if not link.exists():
            os.link(RUN / 'input' / track['filename'], link)
    with ProcessPoolExecutor(max_workers=3) as pool:
        for result in pool.map(extract_partition, range(3)):
            print(json.dumps(result, ensure_ascii=False), flush=True)
    failures = []
    for index in range(3):
        folder = RUN / f'worker-{index}/extraction'
        records.extend(_read_records(folder / 'track-checkpoints.ndjson'))
        failures.extend(_read_records(folder / 'failures.ndjson'))
    unique = {r['analysis']['track']['filename']: r for r in records}
    assert len(unique) == len(records), 'Overlapping worker checkpoints'
    _write_aggregate(EXTRACTION, list(unique.values()), failures)
    write(RUN / 'extraction-summary.json', {'completed': len(unique), 'failures': failures,
                                           'workers': 3, 'remaining': EXPECTED - len(unique)})
    assert len(unique) == EXPECTED, f'Audio extraction incomplete: {len(unique)}/{EXPECTED}'


def train():
    """Reuse audited batch preparation; join features to labels by audio hash."""
    manifest = read(RUN / 'sources/training-manifest.json')
    features = read(PROJECT / 'ZMPD-模型预测开发/features/source/personal-features-v2.json')
    inputs = read(MANIFEST)
    targets = {t['audioSha256']: t for t in inputs['tracks']}
    known = {}
    for receipt in inputs['reusedFeatureSources']:
        for track in read(receipt['analysis'])['tracks']:
            known[track['track']['id']] = track['track']['fileSummary']['sha256']
    original = {(t['filename'], t['fileSize']): t for t in features['tracks']}
    extracted = read(EXTRACTION / 'personal-features-v2.json')
    assert len(extracted['tracks']) == EXPECTED, 'Finish audio extraction before training'
    assert features['featureSchemas'] == extracted['featureSchemas']
    current = {t['id']: t for t in extracted['tracks']}
    joined, receipts = [], []
    for selected in manifest['tracks']:
        key = (selected['filename'], selected['audioFileSize'])
        feature = original.get(key)
        source = 'previous-hash-verified-features'
        if feature:
            assert known[feature['id']] == selected['audioSha256'], f'Training audio mismatch: {key}'
        else:
            target = targets.get(selected['audioSha256'])
            assert target and target['audioFileSize'] == selected['audioFileSize'], f'Missing training audio: {key}'
            feature = current[target['audioAnalysisId']]
            source = 'new-hash-verified-v3-extraction'
        feature = copy.deepcopy(feature)
        feature['filename'] = selected['filename']
        joined.append(feature)
        receipts.append({'filename': selected['filename'], 'audioSha256': selected['audioSha256'],
                         'featureId': feature['id'], 'source': source, 'batchFile': selected['batchFile']})
    assert len(joined) == len({t['id'] for t in joined}) == 467
    features['tracks'] = joined
    features['source'] = {'type': 'manifest-sha256-verified-features', 'receipts': receipts}
    frozen = copy.deepcopy(manifest)
    for source in frozen['sourceFiles']:
        path = Path(source['path'])
        assert digest(path) == source['sha256'], f'Annotation changed during upgrade: {path}'
        snapshot = RUN / 'sources/annotations' / path.name
        snapshot.parent.mkdir(exist_ok=True)
        shutil.copy2(path, snapshot)
        source['path'] = str(snapshot)
    write(RUN / 'training/manifest.json', frozen)
    specification = importlib.util.spec_from_file_location('upgrade_evaluation', PROJECT / 'ZMPD-模型预测开发/run_cross_batch_evaluation.py')
    evaluation = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(evaluation)
    evaluation.MANIFEST = RUN / 'training/manifest.json'
    evaluation.LOCAL_SOURCE_FEATURES = RUN / 'training/personal-features-v2.json'
    evaluation.TRAINING_ROOT = RUN / 'training/batches'
    evaluation.REPORT_HTML = RUN / 'training/cross-batch-evaluation.html'
    evaluation.merged_source_features = lambda: features
    batches = evaluation.prepare_batches(frozen)
    from personal_batch_training import train_batch_normalized_package, predict_selected
    # Preserve the product registry. Comparison scores do not silently change it.
    package, _ = train_batch_normalized_package(batches, method='robust-z',
                                              reference_batch_id='Flowset-个人审美样本-郑卡罗-2026-07-16')
    for selection in package['dimensionModelRegistry'].values():
        selection['reason'] = '沿用现有产品维度注册表；本次扩充训练样本，不按训练内表现重新选择模型。'
    package['provenance'] = {'trainingManifestSha256': digest(RUN / 'training/manifest.json'),
                             'trainingFeaturesSha256': digest(evaluation.LOCAL_SOURCE_FEATURES)}
    write(RUN / 'training/model-package.json', package)
    unlabeled = copy.deepcopy(extracted)
    unlabeled['dimensions'] = batches[0][1]['dimensions']
    for track in unlabeled['tracks']:
        track['selections'] = {}
        track['completed'] = False
    predictions = predict_selected(package, unlabeled)
    truth = {t['audioSha256']: t for t in manifest['tracks']}
    by_filename = {t['filename']: t for t in inputs['tracks']}
    human = 0
    for predicted in predictions['tracks']:
        target = by_filename[predicted['filename']]
        annotation = truth.get(target['audioSha256'])
        if annotation:
            assert annotation['audioFileSize'] == target['audioFileSize']
            predicted['modelPredictionBeforeOverride'] = copy.deepcopy(predicted['dimensions'])
            human_dimensions = []
            for dimension in predicted['dimensions']:
                labels = annotation['selections'][dimension['name']]
                actual = {key: dimension[key] for key in ('id', 'name', 'type')}
                actual.update(status='supported', source='human-ground-truth')
                if dimension['type'] == 'ordinal':
                    actual['referenceScaleValue'] = float(labels[0])
                    actual['referenceScaleDecodedValue'] = int(labels[0])
                else:
                    actual['options'] = [{key: option[key] for key in ('id', 'label')} |
                                         {'score': float(option['label'] in labels), 'status': 'supported', 'source': 'human-ground-truth'}
                                         for option in dimension['options']]
                    actual['prediction'] = {'label': labels[0] if dimension['id'] == 'energy-state' else labels,
                                            'source': 'human-ground-truth'}
                    if dimension['id'] == 'energy-state':
                        actual['prediction'].update(id=next(o['id'] for o in actual['options'] if o['label'] == labels[0]), score=1.0)
                human_dimensions.append(actual)
            predicted['dimensions'] = human_dimensions
            predicted['personalStyleProvenance'] = {
                'type': 'human-ground-truth', 'annotationFile': annotation['batchFile'],
                'sourceAnnotationId': annotation['sourceAnnotationId'],
                'audioSha256': annotation['audioSha256'], 'confidence': annotation['confidence'],
                'policy': manifest['selectionPolicy']}
            human += 1
        else:
            predicted['personalStyleProvenance'] = {
                'type': 'model-prediction', 'modelFile': 'catalog-upgrade-2026-10-11/training/model-package.json',
                'trainingTracks': 467, 'audioSha256': target['audioSha256'],
                'selectionStatus': 'provisional-until-next-blind-test'}
    write(RUN / 'selected-predictions.json', predictions)
    print(f'Trained on 467 labels; catalog human truth {human}, predicted {EXPECTED-human}', flush=True)
    metrics = evaluation.run_evaluation(batches, frozen)
    write(RUN / 'training/cross-batch-evaluation.json', metrics)
    write(RUN / 'training/summary.json', {**package['summary'], 'humanGroundTruthTracks': human,
                                        'modelPredictedTracks': EXPECTED-human,
                                        'featureSources': dict(Counter(r['source'] for r in receipts))})
    print('Leave-one-batch-out evaluation finished', flush=True)


def style_profile():
    """Use formal tags and QQ identities, with repeats and audio errors excluded."""
    import build_annotation_gap_report as gap
    inputs = read(MANIFEST)
    targets = {t['track_id']: t for t in inputs['tracks']}
    tags = read(RUN / 'sources/song_tags.json')['tracks']
    artists = read(RUN / 'sources/song_identity_aliases.json')['artistAliases']
    songs = {}
    for group in read(RUN / 'sources/song_base_by_artist.json')['singers']:
        for song in group['songs']:
            songs[gap.track_id(song['qq_music'])] = {'title': song['title'], 'artist': song.get('full_singer') or group['name'],
                                                   'group_artist': group['name']}
    metadata = {}
    for identity, tag in tags.items():
        if identity not in songs:
            continue
        target = targets.get(identity)
        metadata[identity] = {'trackId': identity, 'filename': target['filename'] if target else f'noncatalog:{identity}',
                              **songs[identity], 'genre': tag['genre'], 'secondaryGenres': tag.get('secondary_genres', [])}
    edges, excluded, conflicts = [], Counter(), []
    with (RUN / 'sources/flowset_transition_analysis_rows.csv').open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        if row['status'] != 'primary' or row['repeat_of']:
            excluded[row['status']] += 1
            continue
        a, b = metadata.get(row['source_id']), metadata.get(row['target_id'])
        if not a or not b:
            excluded['missing-formal-tag-or-identity'] += 1
            continue
        for side, track in (('source', a), ('target', b)):
            artist = artists.get(row[f'{side}_artist'], row[f'{side}_artist'])
            allowed_artists = {gap.text_key(artists.get(track[key], track[key])) for key in ('artist', 'group_artist')}
            if gap.text_key(row[f'{side}_title']) != gap.text_key(track['title']) or gap.text_key(artist) not in allowed_artists:
                conflicts.append({'questionId': row['question_id'], 'side': side, 'trackId': track['trackId']})
        edges.append({'source': a, 'target': b, 'ratings': [float(row['rating'])],
                      'questionRefs': [{'questionId': row['question_id'], 'batch': row['batch'], 'repeatOf': None}]})
    assert not conflicts, f'STP identity conflicts: {conflicts}'
    result = {'schemaVersion': 'songbase.style-transition-preference-report/v1',
              'semantics': {'qualityRating': 'adjacency_utility'},
              'tracks': list(metadata.values()), 'edges': edges,
              'provenance': {'source': 'sources/flowset_transition_analysis_rows.csv',
                             'sourceSha256': digest(RUN / 'sources/flowset_transition_analysis_rows.csv'),
                             'formalTagsSha256': digest(RUN / 'sources/song_tags.json'),
                             'excludedGroups': [5, 8], 'excludedRows': dict(excluded),
                             'primaryRows': len(edges), 'directionalPairs': len({(e['source']['filename'], e['target']['filename']) for e in edges}),
                             'note': '非入库曲目的合格偏好仍用于风格先验，不作为可播放候选；重复题不增加支持。'}}
    write(RUN / 'style-preference-profile.json', result)
    return result


def export():
    """Stream rows, retaining the existing v1 consumer contract and algorithms."""
    from custom_schedule import build_catalog, transition
    from build_browser_catalog import export_catalog
    from style_preference import StylePreferenceModel, has_evidence
    inputs = read(MANIFEST)
    by_filename = {t['filename']: t for t in inputs['tracks']}
    predictions = read(RUN / 'selected-predictions.json')
    prediction_map = {t['filename']: t for t in predictions['tracks']}
    collection = read(EXTRACTION / 'compact-v3-analysis.json')
    assert len(collection['tracks']) == EXPECTED
    collection['tracks'].sort(key=lambda t: by_filename[t['track']['filename']]['track_id'])
    catalog = build_catalog(collection, [predictions])
    model = StylePreferenceModel(style_profile())
    tracks = []
    for item in catalog:
        target = by_filename[item.filename]
        track = export_catalog([item])['tracks'][0]
        track.update(trackId=target['track_id'], songBaseId=target['track_id'],
                     title=target['title'], artist=target['artist'], tag=target['tag'],
                     audioAnalysisId=target['audioAnalysisId'], audioSha256=target['audioSha256'],
                     audioFileSize=target['audioFileSize'],
                     personalStyleProvenance=prediction_map[item.filename]['personalStyleProvenance'])
        tracks.append(track)
    human = sum(t['personalStyleProvenance']['type'] == 'human-ground-truth' for t in tracks)
    header = {'schemaVersion': 'flowset.browser-playlist-catalog/v1',
              'catalogue': {'name': 'SongBase 1204 首歌曲特征库', 'trackCount': EXPECTED,
                            'generatedAt': datetime.now(timezone.utc).isoformat(),
                            'humanGroundTruthZmpd': {'tracks': human, 'predictedTracks': EXPECTED-human},
                            'provenance': {'upgradeManifest': 'catalog-upgrade-2026-10-11/input-manifest.json',
                                           'upgradeManifestSha256': digest(MANIFEST),
                                           'trainingTracks': 467, 'modelPackageSha256': digest(RUN / 'training/model-package.json'),
                                           'styleProfileSha256': digest(RUN / 'style-preference-profile.json'),
                                           'audioAnalysisVersion': collection['modelVersion']}},
              'transitionPolicy': {'mode': 'weighted', 'method': 'weighted-total-score-v1',
                                   'styleWeight': .7, 'acousticWeight': .3}, 'tracks': tracks}
    destination = RUN / '歌曲特征-1204首-待验证.json'
    encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    started = time.monotonic()
    with destination.open('w', encoding='utf-8') as output:
        output.write(encode(header)[:-1] + ',"transitions":[\n')
        for left, source in enumerate(catalog):
            row = []
            for right, target in enumerate(catalog):
                if left == right:
                    row.append(None)
                    continue
                result = transition(source.transition_track, target.transition_track)
                score = model.score(source.filename, target.filename)
                evidence = has_evidence(score)
                row.append({'cost': round(result.cost, 5), 'risk': round(result.risk, 5),
                            'strategy': result.strategy, 'reasons': result.reasons,
                            'objectiveCost': round(.3 * result.cost + .7 * score['cost'] if evidence else result.cost, 5),
                            'styleSelection': {'hasEvidence': evidence, 'predictedRating': round(score['predictedRating'], 4),
                                               'support': score['support'], 'source': score['source']}})
            output.write(encode(row) + (',\n' if left < EXPECTED-1 else '\n'))
            if (left+1) % 100 == 0:
                print(f'Transition rows {left+1}/{EXPECTED}; {time.monotonic()-started:.1f}s', flush=True)
        output.write(']}\n')
    print(f'Exported staged catalog {destination.stat().st_size/1024**2:.1f} MiB', flush=True)


def validate():
    """Full streamed matrix validation, audio rehash and backend spot checks."""
    from custom_schedule import build_catalog, transition
    inputs = read(MANIFEST)
    expected = {t['track_id']: t for t in inputs['tracks']}
    path = RUN / '歌曲特征-1204首-待验证.json'
    sources, strategies, risks = Counter(), Counter(), Counter()
    sample = []
    with path.open(encoding='utf-8') as source:
        first = source.readline()
        header = json.loads(first.removesuffix(',"transitions":[\n') + '}')
        tracks = header['tracks']
        assert len(tracks) == len({t['trackId'] for t in tracks}) == len({t['filename'] for t in tracks}) == EXPECTED
        assert set(expected) == {t['trackId'] for t in tracks}
        human_truth = {t['audioSha256']: t for t in read(RUN / 'sources/training-manifest.json')['tracks']}
        for track in tracks:
            truth = expected[track['trackId']]
            assert track['filename'] == truth['filename'] and track['audioSha256'] == digest(truth['audioPath'])
            assert track['audioFileSize'] == Path(truth['audioPath']).stat().st_size
            assert track['tag'] == truth['tag']
            assert math.isfinite(track['durationSeconds']) and track['durationSeconds'] > 0
            assert math.isfinite(track['opening']['cost']) and 0 <= track['opening']['cost'] <= 1
            assert set(track['aesthetics']) == {'noise', 'swing', 'burden'}
            assert all(1 <= v <= 10 for v in track['aesthetics'].values())
            assert all(math.isfinite(v) and 0 <= v <= 1 for field in ('energyScores', 'timeScores', 'rankedMetrics') for v in track[field].values())
            if track['personalStyleProvenance']['type'] == 'human-ground-truth':
                selections = human_truth[track['audioSha256']]['selections']
                assert track['aesthetics'] == {key: float(selections[name][0]) for key, name in
                                              (('noise', '噪音程度'), ('swing', '摇摆速率'), ('burden', '负担程度'))}
                assert track['energyLabel'] == selections['能量状态'][0]
                assert {key for key, value in track['timeScores'].items() if value == 1} == set(selections['适合的时段'])
        rows = edges = diagonal = 0
        for line in source:
            if line == ']}\n':
                break
            row = json.loads(line.rstrip('\n').removesuffix(','))
            assert len(row) == EXPECTED
            for right, edge in enumerate(row):
                if rows == right:
                    assert edge is None
                    diagonal += 1
                    continue
                assert edge and all(isinstance(edge[k], (int, float)) and math.isfinite(edge[k]) and 0 <= edge[k] <= 1 for k in ('cost', 'risk', 'objectiveCost'))
                assert edge['strategy'] and 1 <= len(edge['reasons']) <= 4
                style = edge['styleSelection']
                assert 1 <= style['predictedRating'] <= 5 and style['support'] >= 0
                weighted = .3*edge['cost']+.7*(5-style['predictedRating'])/4 if style['hasEvidence'] else edge['cost']
                assert abs(weighted-edge['objectiveCost']) < .00002
                sources[style['source']] += 1
                strategies[edge['strategy']] += 1
                risks['hard-rejected' if edge['risk'] >= .5 else 'eligible'] += 1
                edges += 1
                if right == (rows*17+11) % EXPECTED:
                    sample.append((rows, right, edge))
            rows += 1
        assert rows == diagonal == EXPECTED and edges == EXPECTED*(EXPECTED-1)
    collection = read(EXTRACTION / 'compact-v3-analysis.json')
    by_filename = {t['filename']: t['track_id'] for t in inputs['tracks']}
    for analysis in collection['tracks']:
        info = analysis['track']
        target = expected[by_filename[info['filename']]]
        assert info['id'] == target['audioAnalysisId']
        assert info['fileSummary']['sha256'] == target['audioSha256']
        assert info['fileSummary']['sizeBytes'] == target['audioFileSize']
    collection['tracks'].sort(key=lambda t: by_filename[t['track']['filename']])
    schedule = build_catalog(collection, [read(RUN / 'selected-predictions.json')])
    for left, right, edge in sample:
        result = transition(schedule[left].transition_track, schedule[right].transition_track)
        assert edge['cost'] == round(result.cost, 5) and edge['risk'] == round(result.risk, 5)
        assert edge['reasons'] == result.reasons and edge['strategy'] == result.strategy
    baseline = read(inputs['baseline']['path'])
    previous = {t['filename'] for t in baseline['tracks']}
    current = {t['filename'] for t in tracks}
    human = [t for t in tracks if t['personalStyleProvenance']['type'] == 'human-ground-truth']
    with (RUN / 'sources/Flow衔接与ZMPD补标缺口清单.csv').open(encoding='utf-8-sig', newline='') as source:
        gap_rows = {r['track_id']: r for r in csv.DictReader(source)}
    version_reviews = [{'trackId': t['trackId'], 'filename': t['filename'], 'audioSha256': t['audioSha256'],
                        'reason': '歌曲身份已有历史标注，但本次音频 SHA-256 未匹配合格训练真值；暂用预测'}
                       for t in tracks if gap_rows[t['trackId']]['zmpd_labeled'] == 'True'
                       and t['personalStyleProvenance']['type'] != 'human-ground-truth']
    audit = {'schemaVersion': 'songbase.catalog-upgrade-audit/v1', 'validatedAt': datetime.now(timezone.utc).isoformat(),
             'status': 'validated-not-yet-published', 'tracks': EXPECTED, 'directedTransitions': edges,
             'emptyOffDiagonal': 0, 'nullDiagonal': diagonal, 'backendSpotChecks': len(sample),
             'audioHashRevalidated': EXPECTED, 'humanGroundTruthTracks': len(human),
             'humanGroundTruthFiveDimensionsRevalidated': len(human),
             'modelPredictedTracks': EXPECTED-len(human), 'styleSources': dict(sources),
             'historicalLabelsRequiringAudioVersionReview': version_reviews,
             'strategies': dict(strategies), 'risk': dict(risks), 'genreCounts': inputs['summary']['genres'],
             'baselineTracks': len(baseline['tracks']), 'retainedBaselineTracks': len(previous & current),
             'addedTracks': len(current-previous), 'excludedOldFilenames': sorted(previous-current),
             'catalogBytes': path.stat().st_size, 'catalogSha256': digest(path),
             'model': read(RUN / 'training/summary.json'), 'styleProfile': read(RUN / 'style-preference-profile.json')['provenance']}
    write(RUN / 'upgrade-audit.json', audit)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


def publish():
    audit = read(RUN / 'upgrade-audit.json')
    staged = RUN / '歌曲特征-1204首-待验证.json'
    inputs = read(MANIFEST)
    assert audit['tracks'] == EXPECTED and digest(staged) == audit['catalogSha256']
    browser = read(RUN / 'browser-smoke-audit.json')
    assert browser['status'] == 'passed', 'Browser acceptance is required'
    for name in ('song_tags.json', 'song_base_by_artist.json', 'song_identity_aliases.json'):
        assert digest(ROOT / name) == digest(RUN / 'sources' / name), f'Source changed during upgrade: {name}'
    destination = ROOT / '歌曲特征.json'
    # Fail closed if someone changed the live 480-song library meanwhile.
    assert digest(destination) in {inputs['baseline']['sha256'], audit['catalogSha256']}, 'Live catalog changed; do not overwrite'
    temporary = ROOT / '歌曲特征.json.upgrade-tmp'
    shutil.copyfile(staged, temporary)
    os.replace(temporary, destination)
    assert digest(destination) == audit['catalogSha256']
    audit.update(status='published-and-sha256-verified', publishedAt=datetime.now(timezone.utc).isoformat(),
                 publishedPath=str(destination), rollbackPath=inputs['baseline']['path'], browserAcceptance=browser)
    write(RUN / 'upgrade-audit.json', audit)
    print(f'Published {EXPECTED} tracks to {destination}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'extract', 'extract-parallel', 'train', 'export', 'validate', 'publish'))
    parser.add_argument('--max-tracks', type=int, default=50)
    args = parser.parse_args()
    if args.phase == 'prepare':
        prepare()
    elif args.phase == 'extract':
        extract(args.max_tracks)
    elif args.phase == 'extract-parallel':
        extract_parallel()
    else:
        globals()[args.phase]()


if __name__ == '__main__':
    main()
