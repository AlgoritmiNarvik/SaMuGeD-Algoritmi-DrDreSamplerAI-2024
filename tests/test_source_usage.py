import csv
import gzip
import json
import pytest

from samuged.source_usage import assess, load_scores, prepare, source_path


def record(dataset='pdmx', license_id='CC-BY-4.0'):
    return dict(dataset_id=dataset, dataset_license=license_id, conditions_json='[]',
                evidence_url='https://zenodo.org/records/15571083',
                score_license_declaration='publicdomain',
                score_license_url='https://creativecommons.org/publicdomain/mark/1.0/')


def score():
    return dict(mid='./mid/0/file.mid', metadata='./metadata/5/123.json',
                license='publicdomain', license_url=record()['score_license_url'],
                license_conflict='False', **{'subset:no_license_conflict': 'True',
                                           'subset:all_valid': 'True'})


def test_consistent_score_declaration_is_not_verified_clearance():
    row = assess(record(), score(), csv_sha256='bound')
    assert row['commercial_terms_status'] == 'conditional_declared'
    assert row['overall_clearance_status'] == 'not_established'
    assert row['score_review_status'] == 'declaration_consistent'
    assert row['source_score_id'] == '123'
    assert row['usage_evidence']['score']['csv_sha256'] == 'bound'
    assert row['usage_evidence']['score']['score_page_verified'] is False


@pytest.mark.parametrize('change', [dict(license_conflict='True'),
    dict(license='cc0'), dict(license_url='https://unrelated.example/'),
    {'subset:no_license_conflict': 'False'}])
def test_conflicts_never_become_permission(change):
    row = assess(record(), dict(score(), **change))
    assert row['score_review_status'] == 'conflict'
    assert row['commercial_terms_status'] == row['research_terms_status'] == 'unresolved'


def test_missing_evidence_and_unknown_license_do_not_grant_use():
    assert assess(record())['score_review_status'] == 'incomplete'
    assert assess(record())['commercial_terms_status'] == 'unresolved'
    row = assess(record('unrecognized', 'MIT'))
    assert row['research_terms_status'] == row['commercial_terms_status'] == 'unresolved'
    assert assess(dict(record('lakh'), evidence_url=None))['commercial_terms_status'] == 'unresolved'


def test_noncommercial_research_does_not_remove_maestro_restriction():
    row = assess(record('maestro', 'CC-BY-NC-SA-4.0'))
    assert row['research_terms_status'] == 'conditional_declared'
    assert row['redistribution_terms_status'] == 'conditional_declared'
    assert row['commercial_terms_status'] == 'restricted_declared'
    assert row['overall_clearance_status'] == 'not_established'


def test_duplicate_paths_are_rejected_and_no_basename_join(tmp_path):
    p = tmp_path/'scores.csv'
    with p.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(score()))
        writer.writeheader();writer.writerow(score());writer.writerow(score())
    with pytest.raises(ValueError, match='ambiguous'):load_scores(p)
    assert source_path('./mid/0/file.mid') != source_path('./mid/1/file.mid')
    with pytest.raises(ValueError):source_path('../file.mid')


def test_prepare_search_export_and_input_binding(tmp_path, monkeypatch):
    from test_catalog_metadata import index
    from samuged.catalog_metadata import search
    from samuged.source_rights import prepare as scan, export_records
    metadata, _ = index(tmp_path, monkeypatch)
    catalog = tmp_path/'catalog.sqlite'
    rights = tmp_path/'rights.sqlite'
    scan(metadata, catalog, rights, {'local': tmp_path}, workers=1)
    output = tmp_path/'usage.sqlite'
    receipt = prepare(rights, catalog, output)
    assert receipt['source_records'] == 1
    row = search(output, commercial_terms='unresolved')[0]
    assert row['overall_clearance_status'] == 'not_established'
    assert row['usage_evidence']['scope'].startswith('declared corpus')
    assert search(output, commercial_terms='restricted_declared') == []
    with pytest.raises(ValueError, match='usage annotation'):search(rights, commercial_terms='unresolved')
    with pytest.raises(ValueError):search(output, commercial_terms='allowed')
    portable = tmp_path/'usage.jsonl.gz';export_records(output, portable)
    with gzip.open(portable, 'rt') as stream:exported = json.loads(stream.readline())
    assert exported['usage_conditions'] == row['usage_conditions']
    assert exported['overall_clearance_status'] == 'not_established'
    with pytest.raises(FileExistsError):prepare(rights, catalog, output)
    import sqlite3
    with sqlite3.connect(rights) as db:db.execute("UPDATE records SET source_sha256='changed'")
    with pytest.raises(ValueError, match='source hash'):prepare(rights, catalog, tmp_path/'invalid.sqlite')
    assert not (tmp_path/'invalid.sqlite').exists()
