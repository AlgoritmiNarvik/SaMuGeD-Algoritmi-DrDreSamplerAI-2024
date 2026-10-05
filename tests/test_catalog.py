import json
from pathlib import Path
import sqlite3
import pytest
from samuged.catalog import build_catalog


def setup_manifest(tmp_path, *, rights='unknown'):
    rows = [dict(source_id='a',source_path="artist/O'Brien.mid",status='ok',
        artist_from_path="O'Brien'); DROP TABLE sources; --",title_from_path='Song',algorithm='aligned_closed',
        source_sha256='abc',phrases=[dict(phrase_id='p',kind='melodic',program=24,
            duration_beats=4,pitches=[60,64],velocities=[80,100],onsets_beats=[0,1],
            occurrence_count=3,recurrence_score=.8)])]
    (tmp_path/'records.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    manifest = dict(schema_version=1,datasets=[dict(dataset_id='local',name='Local',version='1',
        source_url='https://example.org',dataset_license='unknown',composition_rights=rights,
        redistribution_status='unknown')],builds=[dict(dataset_id='local',records='records.jsonl')])
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest));return path


def test_catalog_preserves_uncertainty_and_injection_labels(tmp_path):
    manifest=setup_manifest(tmp_path);out=tmp_path/'catalog.sqlite'
    receipt=build_catalog(manifest,out,max_output_mb=4,min_free_mb=0)
    assert receipt['sources']==1 and receipt['phrases']==1
    with sqlite3.connect(out) as db:
        row=db.execute('SELECT instrument_family, composition_rights,velocity_mean,onset_density,identity_evidence FROM phrase_catalog JOIN sources USING(source_key)').fetchone()
        assert row==('guitar','unknown',90,0.5,'source_filename_unverified')
        assert db.execute('SELECT artist FROM sources').fetchone()[0].startswith("O'Brien")
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_failure_does_not_leave_partial_database(tmp_path):
    manifest=setup_manifest(tmp_path,rights='verified');out=tmp_path/'out.sqlite'
    with pytest.raises(ValueError,match='evidence'):
        build_catalog(manifest,out,max_output_mb=4,min_free_mb=0)
    assert not out.exists()
    assert not list(tmp_path.glob('samuged-catalog-*'))


def test_existing_output_is_preserved(tmp_path):
    manifest=setup_manifest(tmp_path);out=tmp_path/'out.sqlite';out.write_bytes(b'keep')
    with pytest.raises(FileExistsError):build_catalog(manifest,out)
    assert out.read_bytes()==b'keep'


def test_multi_corpus_keeps_original_ids_separate(tmp_path):
    path=setup_manifest(tmp_path);manifest=json.loads(path.read_text())
    manifest['datasets'].append({**manifest['datasets'][0],'dataset_id':'other'})
    manifest['builds'].append(dict(dataset_id='other',records='records.jsonl'))
    path.write_text(json.dumps(manifest));out=tmp_path/'out.sqlite'
    receipt=build_catalog(path,out,max_output_mb=4,min_free_mb=0)
    assert receipt['sources']==2 and receipt['phrases']==2
    with sqlite3.connect(out) as db:
        assert db.execute('SELECT count(DISTINCT phrase_key) FROM phrases').fetchone()[0]==2


def test_failed_source_remains_accounted(tmp_path):
    path=setup_manifest(tmp_path)
    (tmp_path/'records.jsonl').write_text(json.dumps(dict(source_id='bad',source_path='bad.mid',status='error',phrases=[])))
    result=build_catalog(path,tmp_path/'out.sqlite',max_output_mb=4,min_free_mb=0)
    assert result['sources']==1 and result['phrases']==0


def test_nonfinite_score_is_rejected(tmp_path):
    path=setup_manifest(tmp_path);records=tmp_path/'records.jsonl'
    row=json.loads(records.read_text());row['phrases'][0]['recurrence_score']=float('nan')
    records.write_text(json.dumps(row))
    with pytest.raises(ValueError,match='finite'):
        build_catalog(path,tmp_path/'out.sqlite',max_output_mb=4,min_free_mb=0)
    assert not (tmp_path/'out.sqlite').exists()
