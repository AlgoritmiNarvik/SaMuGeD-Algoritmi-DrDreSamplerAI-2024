"""Source binding and exact selection coverage for interface supplements."""
import hashlib
import json

import pytest

from scripts.curate_external_tool import curate


def fixture_packet(tmp_path):
    dataset = tmp_path / 'dataset'
    sources = tmp_path / 'sources'
    dataset.mkdir()
    (dataset / 'midi').mkdir()
    (sources / 'Tool').mkdir(parents=True)
    config = {'sources': {}, 'selections': {}, 'per_song': {'melodic': 2, 'percussion': 1}}
    rows, source_rows = [], []
    for song in ('One', 'Two'):
        path = f'Tool/{song}.mid'
        payload = song.encode()
        (sources / path).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        config['sources'][path] = {'source_url': f'https://example.org/{song}', 'download_url': f'https://example.org/{song}.mid', 'sha256': digest}
        config['selections'][path] = []
        source_rows.append({'source_path': path, 'source_sha256': digest, 'status': 'ok', 'search_limited': False, 'curation_truncated': False})
        for i, kind in enumerate(('melodic', 'melodic', 'percussion')):
            pid = f'{song}-{i}'
            midi = f'midi/{pid}.mid'
            (dataset / midi).write_bytes(pid.encode())
            config['selections'][path].append([pid, 'Distinct source pattern.'])
            rows.append({'phrase_id': pid, 'source_path': path, 'source_sha256': digest, 'kind': kind, 'pitches': [60, 62, 64], 'duration_beats': 4, 'start_tick': 0, 'end_tick': 100, 'occurrence_count': 2, 'occurrences': [{'start_tick': 0, 'end_tick': 100}, {'start_tick': 200, 'end_tick': 300}], 'midi_path': midi, 'midi_sha256': hashlib.sha256(pid.encode()).hexdigest()})
    for name, values in [('phrases.jsonl', rows), ('sources.jsonl', source_rows)]:
        (dataset / name).write_text(''.join(json.dumps(r) + '\n' for r in values))
    for name in ('build_config.json', 'summary.json'):
        (dataset / name).write_text('{}')
    return dataset, sources, config


def test_configured_supplement_binds_each_source_and_selected_midi(tmp_path):
    dataset, sources, config = fixture_packet(tmp_path)
    output = tmp_path / 'selection'
    result = curate(dataset, sources, output, config)
    assert result['selected_source_files'] == 2
    assert result['selected_melodic_count'] == 4
    assert result['selected_percussion_count'] == 2
    assert len(list((output / 'midi').glob('*.mid'))) == 6
    assert {r['source_url'] for r in result['candidates']} == {'https://example.org/One', 'https://example.org/Two'}


def test_config_cannot_assign_another_songs_phrase(tmp_path):
    dataset, sources, config = fixture_packet(tmp_path)
    config['selections']['Tool/One.mid'][0][0] = 'Two-0'
    with pytest.raises(ValueError, match='does not belong'):
        curate(dataset, sources, tmp_path / 'selection', config)


def test_changed_download_is_rejected_before_rendering(tmp_path):
    dataset, sources, config = fixture_packet(tmp_path)
    (sources / 'Tool/One.mid').write_bytes(b'changed source')
    with pytest.raises(ValueError, match='source hash mismatch'):
        curate(dataset, sources, tmp_path / 'selection', config)


def test_changed_detector_export_is_rejected(tmp_path):
    dataset, sources, config = fixture_packet(tmp_path)
    (dataset / 'midi/One-0.mid').write_bytes(b'changed phrase')
    with pytest.raises(ValueError, match='detector MIDI hash mismatch'):
        curate(dataset, sources, tmp_path / 'selection', config)


def test_download_receipt_must_match_source_manifest(tmp_path):
    dataset, sources, config = fixture_packet(tmp_path)
    config['sources']['Tool/One.mid']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='download receipt hash mismatch'):
        curate(dataset, sources, tmp_path / 'selection', config)
