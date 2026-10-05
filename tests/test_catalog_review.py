import json
import sqlite3

import pytest

from samuged.catalog import build_catalog
from samuged.catalog_review import review
from samuged.catalog_search import export
from samuged.dataset import file_digest
from test_catalog import setup_manifest


def catalog(tmp_path):
    manifest_path=setup_manifest(tmp_path)
    manifest=json.loads(manifest_path.read_text())
    record=json.loads((tmp_path/'records.jsonl').read_text())
    record.update(musical_sha256='arrangement',split='train',search_limited=True,
                  warnings=['parse warning'],annotations=[dict(category='genre_raw',value='folk',
                    evidence_url='https://example.org/score',method='upstream')])
    (tmp_path/'records.jsonl').write_text(json.dumps(record))
    record.update(source_id='b',split='test',source_sha256='different-bytes')
    (tmp_path/'other.jsonl').write_text(json.dumps(record))
    manifest['datasets'].append({**manifest['datasets'][0],'dataset_id':'other'})
    manifest['builds'].append(dict(dataset_id='other',records='other.jsonl'))
    manifest_path.write_text(json.dumps(manifest))
    output=tmp_path/'catalog.sqlite'
    build_catalog(manifest_path,output,max_output_mb=4,min_free_mb=0)
    return output


def test_cross_corpus_arrangement_conflict_and_coverage(tmp_path):
    path=catalog(tmp_path);before=file_digest(path)
    result=review(path)
    assert result['catalog_sha256']==before==file_digest(path)
    assert result['duplicate_candidates']['matching_bytes']['candidate_groups']==0
    groups=result['duplicate_candidates']['matching_normalized_arrangement']
    assert groups['candidate_groups']==groups['cross_corpus_groups']==groups['evaluation_split_conflict_groups']==1
    assert {r['dataset_id'] for r in groups['examples'][0]['members']}=={'local','other'}
    assert result['corpora'][0]['sources_with_phrases']==1
    assert result['corpora'][0]['search_limited_sources']==1
    assert result['annotation_coverage'][0]['labeled_sources']==1
    assert result['rights_evidence'][0]['redistribution_status']=='unknown'
    assert result['sources_removed'] is result['splits_changed'] is result['published'] is False
    out=tmp_path/'review.json';export(result,out)
    assert json.loads(out.read_text())==result


def test_unknown_hashes_do_not_form_groups_and_missing_fields_remain_missing(tmp_path):
    path=catalog(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE sources SET source_sha256='',musical_sha256=NULL,artist=NULL,title='',split='unassigned'")
    result=review(path,sample_limit=0)
    assert all(g['candidate_groups']==0 for g in result['duplicate_candidates'].values())
    assert all(r['missing_artist']==r['missing_title']==r['missing_byte_hash']==r['missing_arrangement_hash']==1 for r in result['corpora'])
    assert all(r['sources_without_evaluation_split']==1 for r in result['corpora'])


def test_samples_are_bounded_without_changing_counts(tmp_path):
    path=catalog(tmp_path)
    result=review(path,sample_limit=0)
    group=result['duplicate_candidates']['matching_normalized_arrangement']
    assert group['candidate_groups']==1 and group['examples']==[] and group['examples_truncated']


@pytest.mark.parametrize('limit',[-1,101,True,1.5])
def test_invalid_sample_limit(tmp_path,limit):
    with pytest.raises(ValueError,match='sample limit'):
        review(tmp_path/'missing',sample_limit=limit)
