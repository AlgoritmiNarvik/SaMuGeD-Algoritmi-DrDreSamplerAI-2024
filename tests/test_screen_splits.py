import json
from pathlib import Path

import pytest

from samuged.dataset import atomic_json, canonical_json, file_digest
from scripts.screen_splits import screen, verify_screening


def fixture(tmp_path):
    dataset = tmp_path/'dataset'
    dataset.mkdir()
    sources = []
    for index, (group, split) in enumerate((('a', 'train'), ('b', 'validation'),
                                           ('b', 'validation'), ('d', 'test'), ('e', 'test'))):
        sources.append({'source_id': str(index), 'source_path': f'A/song{index}.mid',
                        'source_sha256': f'{index:064x}', 'split_group': group, 'split': split})
    phrases = [{'phrase_id': f'p{row["source_id"]}', 'source_id': row['source_id'],
                'kind': 'melodic', 'split_group': row['split_group'], 'split': row['split']}
               for row in sources]
    phrases.append({**phrases[1], 'phrase_id': 'already-excluded', 'split': 'overlap_excluded'})
    for name, rows in (('sources.jsonl', sources), ('phrases.jsonl', phrases)):
        (dataset/name).write_text(''.join(canonical_json(row)+'\n' for row in rows))
    summary = {'source_files': 5, 'run_key': 'run',
               'source_manifest_sha256': file_digest(dataset/'sources.jsonl'),
               'phrase_manifest_sha256': file_digest(dataset/'phrases.jsonl')}
    atomic_json(dataset/'summary.json', summary)
    candidates = []
    for left, right in ((sources[0], sources[1]), (sources[1], sources[3])):
        row = {'symbolic_near_duplicate': True, 'exact_arrangement': False, 'exact_bytes': False,
               'shared_rare_shingles': 100, 'jaccard': .9, 'containment': .95}
        for side, source in (('left', left), ('right', right)):
            row.update({f'{side}_{key}': source[key] for key in ('source_path', 'source_sha256', 'split')})
        candidates.append(row)
    report = {'manifest_sha256': summary['source_manifest_sha256'], 'method_key': 'method',
              'fingerprint_method_key_counts': {'method': 5}, 'candidates': candidates,
              'generation': {key: False for key in ('pair_generation_limit_reached',
                  'pair_verification_limit_reached', 'candidate_report_limit_reached')}}
    path = tmp_path/'duplicates.json'
    atomic_json(path, report)
    return dataset, path, report


def test_transitive_groups_are_quarantined_and_originals_unchanged(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    before = {name: (dataset/name).read_bytes() for name in ('sources.jsonl', 'phrases.jsonl')}
    output = tmp_path/'screened'
    result = screen(dataset, report, output)
    assert (output/'duplicate_report.json').read_bytes() == report.read_bytes()
    assert result['excluded_source_groups'] == 2
    assert result['source_split_counts'] == {'train': 1, 'duplicate_excluded': 3, 'test': 1}
    assert result['newly_excluded_phrase_counts'] == {'validation': 2, 'test': 1}
    assert result['already_family_excluded_phrases_in_quarantined_groups'] == 1
    assert result['retained_cross_split_candidate_edges'] == 0
    assert {name: (dataset/name).read_bytes() for name in before} == before
    rows = [json.loads(line) for line in (output/'phrase_splits.jsonl').read_text().splitlines()]
    assert rows[-1]['screened_split'] == 'overlap_excluded'
    for name, digest in result['artifacts'].items():
        assert file_digest(output/name) == digest
    with pytest.raises(ValueError, match='new or empty'):
        screen(dataset, report, output)


def _rewrite_screening_artifact(output, name, rows):
    (output/name).write_text(''.join(canonical_json(row)+'\n' for row in rows))
    summary = json.loads((output/'summary.json').read_text())
    summary['artifacts'][name] = file_digest(output/name)
    atomic_json(output/'summary.json', summary)


def test_verify_screening_reconstructs_valid_view(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    expected = screen(dataset, report, output)

    assert verify_screening(dataset, output) == expected


@pytest.mark.parametrize('artifact,field', [
    ('source_splits.jsonl', 'screened_split'),
    ('phrase_splits.jsonl', 'screened_split'),
])
def test_verify_screening_rejects_rehashed_forged_mapping(tmp_path, artifact, field):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)
    rows = [json.loads(line) for line in (output/artifact).read_text().splitlines()]
    rows[0][field] = 'duplicate_excluded' if rows[0][field] != 'duplicate_excluded' else 'train'
    _rewrite_screening_artifact(output, artifact, rows)

    with pytest.raises(ValueError, match='mapping mismatch'):
        verify_screening(dataset, output)


def test_verify_screening_rejects_base_source_phrase_split_mismatch(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)

    phrases = [json.loads(line) for line in (dataset/'phrases.jsonl').read_text().splitlines()]
    phrases[0]['split'] = 'test'
    (dataset/'phrases.jsonl').write_text(
        ''.join(canonical_json(row)+'\n' for row in phrases)
    )
    dataset_summary = json.loads((dataset/'summary.json').read_text())
    dataset_summary['phrase_manifest_sha256'] = file_digest(dataset/'phrases.jsonl')
    atomic_json(dataset/'summary.json', dataset_summary)
    screening_summary = json.loads((output/'summary.json').read_text())
    screening_summary['phrase_manifest_sha256'] = dataset_summary['phrase_manifest_sha256']
    atomic_json(output/'summary.json', screening_summary)

    with pytest.raises(ValueError, match='phrase split does not match'):
        verify_screening(dataset, output)


def test_verify_screening_rejects_summary_count_tampering(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)
    summary = json.loads((output/'summary.json').read_text())
    summary['candidate_edges'] += 1
    atomic_json(output/'summary.json', summary)

    with pytest.raises(ValueError, match='candidate edge count mismatch'):
        verify_screening(dataset, output)


def test_verify_screening_rejects_rehashed_edge_group_tampering(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)
    edges = [json.loads(line) for line in (output/'candidate_edges.jsonl').read_text().splitlines()]
    edges[0]['left_split_group'] = 'forged-group'
    _rewrite_screening_artifact(output, 'candidate_edges.jsonl', edges)

    with pytest.raises(ValueError, match='source group mismatch'):
        verify_screening(dataset, output)


def test_verify_screening_reconstructs_edges_from_report_artifact(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)

    copied_report = json.loads((output/'duplicate_report.json').read_text())
    copied_report['candidates'] = []
    atomic_json(output/'duplicate_report.json', copied_report)
    summary = json.loads((output/'summary.json').read_text())
    summary['duplicate_report_sha256'] = file_digest(output/'duplicate_report.json')
    summary['artifacts']['duplicate_report.json'] = summary['duplicate_report_sha256']
    atomic_json(output/'summary.json', summary)

    with pytest.raises(ValueError, match='candidate edge artifact does not match'):
        verify_screening(dataset, output)


def test_verify_screening_rejects_report_source_forgery_after_rehash(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)

    copied_report = json.loads((output/'duplicate_report.json').read_text())
    copied_report['candidates'][0]['left_source_sha256'] = 'f' * 64
    atomic_json(output/'duplicate_report.json', copied_report)
    summary = json.loads((output/'summary.json').read_text())
    summary['duplicate_report_sha256'] = file_digest(output/'duplicate_report.json')
    summary['artifacts']['duplicate_report.json'] = summary['duplicate_report_sha256']
    atomic_json(output/'summary.json', summary)

    with pytest.raises(ValueError, match='source hash or path mismatch'):
        verify_screening(dataset, output)


def test_verify_screening_rejects_escaped_artifact(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)
    escaped = tmp_path/'outside.jsonl'
    escaped.write_bytes((output/'candidate_edges.jsonl').read_bytes())
    (output/'candidate_edges.jsonl').unlink()
    (output/'candidate_edges.jsonl').symlink_to(escaped)

    with pytest.raises(ValueError, match='regular file'):
        verify_screening(dataset, output)


def test_verify_screening_requires_unverified_script_creation_metadata(tmp_path):
    dataset, report, _ = fixture(tmp_path)
    output = tmp_path/'screened'
    screen(dataset, report, output)
    summary = json.loads((output/'summary.json').read_text())
    summary['script_provenance']['status'] = 'verified_current'
    atomic_json(output/'summary.json', summary)

    with pytest.raises(ValueError, match='script provenance'):
        verify_screening(dataset, output)


@pytest.mark.parametrize('corruption', ['manifest', 'candidate', 'method', 'budget'])
def test_rejects_unreconciled_or_limited_duplicate_report(tmp_path, corruption):
    dataset, path, report = fixture(tmp_path)
    if corruption == 'manifest':
        report['manifest_sha256'] = 'wrong'
    elif corruption == 'candidate':
        report['candidates'][0]['left_source_sha256'] = 'wrong'
    elif corruption == 'method':
        report['fingerprint_method_key_counts'] = {'old': 4, 'method': 1}
    else:
        report['generation']['pair_generation_limit_reached'] = True
    atomic_json(path, report)
    with pytest.raises(ValueError):
        screen(dataset, path, tmp_path/'screened')
