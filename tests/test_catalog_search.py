import csv
import json
from pathlib import Path
import sqlite3
import pytest
from samuged.catalog import build_catalog
from samuged.catalog_search import connect,export,info,search
from test_catalog import setup_manifest


def catalog(tmp_path):
    manifest=setup_manifest(tmp_path)
    path=tmp_path/'records.jsonl';row=json.loads(path.read_text())
    row['title_from_path']='100% _ motif'
    row['upstream_metadata']={'license':'publicdomain','composer_name':'Composer'}
    row['annotations']=[dict(category='genre_raw',value='classical-folk',evidence_url='https://example.org',method='upstream')]
    path.write_text(json.dumps(row))
    output=tmp_path/'catalog#?.sqlite';build_catalog(manifest,output,max_output_mb=4,min_free_mb=0)
    return output


def test_filters_preserve_declared_license_and_unknown_rights(tmp_path):
    path=catalog(tmp_path)
    rows=search(path,kind='melodic',instrument='guitar',category='genre_raw',value='classical-folk',rights='unknown')
    assert len(rows)==1
    assert rows[0]['score_license_declaration']=='publicdomain'
    assert rows[0]['redistribution_status']=='unknown'
    assert rows[0]['identity_evidence']=='source_filename_unverified'
    assert search(path,rights='verified')==[]
    assert search(path,min_repeats=4)==[]
    assert search(path,min_beats=5)==[]


def test_search_treats_sql_and_wildcards_as_literal_data(tmp_path):
    path=catalog(tmp_path)
    assert len(search(path,text='100% _'))==1
    assert search(path,text="'); DROP TABLE phrases; --")==[]
    assert len(search(path,text="O'Brien"))==1
    assert info(path,category='genre_raw')['category_values']==[{'value':'classical-folk','source_records':1}]
    with connect(path) as db:
        with pytest.raises(sqlite3.OperationalError):db.execute('DELETE FROM sources')


@pytest.mark.parametrize('kwargs',[{'sort':'title; DELETE FROM sources'},{'limit':501},{'limit':0},
    {'category':'genre_raw'},{'min_beats':float('nan')},{'min_beats':5,'max_beats':4},{'min_repeats':0}])
def test_invalid_filter_cannot_run(tmp_path,kwargs):
    path=catalog(tmp_path)
    with pytest.raises(ValueError):search(path,**kwargs)


def test_exports_are_atomic_and_csv_formula_safe(tmp_path):
    rows=[{'title':'=HYPERLINK("bad")','phrase_key':'abc'}]
    json_path=tmp_path/'out.json';export(rows,json_path)
    assert json.loads(json_path.read_text())==rows
    csv_path=tmp_path/'out.csv';export(rows,csv_path,format='csv')
    assert next(csv.DictReader(csv_path.open()))['title'].startswith("'=")
    with pytest.raises(FileExistsError):export([],json_path)
    assert json.loads(json_path.read_text())==rows
