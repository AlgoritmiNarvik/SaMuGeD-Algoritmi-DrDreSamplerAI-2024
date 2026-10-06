import json
import shutil
import sqlite3
import pytest
from samuged.catalog_metadata import prepare, search, import_links
from samuged.catalog import build_catalog
from test_catalog import setup_manifest


def index(tmp_path,monkeypatch):
    monkeypatch.setattr(shutil,'disk_usage',lambda _:shutil._ntuple_diskusage(10**12,0,10**12))
    m=setup_manifest(tmp_path);r=tmp_path/'records.jsonl';row=json.loads(r.read_text())
    row['upstream_metadata']={'composer_name':'Bach','license':'publicdomain','license_url':'https://example.org','genres':['classical']}
    r.write_text(json.dumps(row));c=tmp_path/'catalog.sqlite';build_catalog(m,c,max_output_mb=4,min_free_mb=0)
    out=tmp_path/'metadata.sqlite';receipt=prepare(c,out,max_output_mb=4);return out,receipt


def test_search_rights_and_groups(tmp_path,monkeypatch):
    out,receipt=index(tmp_path,monkeypatch)
    assert receipt['source_records']==1
    rows=search(out,text='Bach',composer='Bach',score_license='publicdomain')
    assert len(rows)==1 and rows[0]['composition_rights']=='unknown'
    assert rows[0]['evaluation_split']=='unassigned' and rows[0]['candidate_group']
    assert search(out,text='" OR 1=1 --')==[]
    with pytest.raises(FileExistsError):prepare(tmp_path/'catalog.sqlite',out)


def test_links_do_not_promote_identity_and_rollback(tmp_path,monkeypatch):
    out,_=index(tmp_path,monkeypatch);key=search(out)[0]['source_key'];entity='00000000-0000-0000-0000-000000000001'
    link=dict(source_key=key,provider='musicbrainz',entity_id=entity,title='Song',artist='Artist',
        evidence_url='https://musicbrainz.org/recording/'+entity,metadata_license='CC0-1.0',match_status='candidate',method='title_artist_search',retrieved_on='2026-10-06')
    with pytest.raises(ValueError):import_links(out,[link,{**link,'source_key':'missing'}])
    db=sqlite3.connect(out);assert db.execute('SELECT count(*) FROM external_links').fetchone()[0]==0
    import_links(out,[link]);assert db.execute('SELECT count(*) FROM external_links').fetchone()[0]==1
    assert search(out)[0]['identity_evidence']=='source_filename_unverified';db.close()

@pytest.mark.parametrize('limit',[0,501,True])
def test_result_bounds(tmp_path,monkeypatch,limit):
    out,_=index(tmp_path,monkeypatch)
    with pytest.raises(ValueError):search(out,limit=limit)


def test_global_union_is_transitive_and_does_not_assign_splits(tmp_path,monkeypatch):
    out,_=index(tmp_path,monkeypatch)
    catalog=tmp_path/'catalog.sqlite';db=sqlite3.connect(catalog)
    columns=[r[1] for r in db.execute('PRAGMA table_info(sources)')]
    base=dict(zip(columns,db.execute('SELECT * FROM sources').fetchone()));base['note_count']=10
    db.execute('UPDATE sources SET note_count=10,source_sha256=?,musical_sha256=?',('bytes1','notes1'))
    for key,byte,music in [('b','bytes1','notes2'),('c','bytes2','notes2')]:
        row={**base,'source_key':key,'source_id':key,'source_sha256':byte,'musical_sha256':music}
        db.execute('INSERT INTO sources VALUES ('+','.join('?' for _ in columns)+')',[row[k] for k in columns])
    db.commit();db.close();target=tmp_path/'union.sqlite';receipt=prepare(catalog,target,max_output_mb=4)
    assert receipt['candidate_groups']==1
    assert {r['evaluation_split'] for r in search(target)}=={'unassigned'}
