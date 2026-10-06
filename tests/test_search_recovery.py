import gzip
import json
import sqlite3
from collections import namedtuple

import pytest

from samuged.search_recovery import prepare, search


def fixture(tmp_path, monkeypatch, records=None):
    monkeypatch.setattr('samuged.search_recovery.shutil.disk_usage',lambda p:namedtuple('Usage','total used free')(0,0,20*1024**3))
    index=tmp_path/'work.sqlite'
    with sqlite3.connect(index) as db:
        db.execute('CREATE TABLE queue(source_key TEXT,source_sha256 TEXT)')
        db.executemany('INSERT INTO queue VALUES (?,?)',[('a','hash-a'),('b','hash-b')])
    base=dict(dataset_id='pdmx',title='Café tune',creator_search_hint=None,original_source_path='mid/123.mid',search_route='title_and_source_identifier_review',identity_verified=False,rights_clearance='not_established')
    rows=records or [dict(base,source_key='a',source_sha256='hash-a'),dict(base,source_key='b',source_sha256='hash-b')]
    packets=tmp_path/'packets.jsonl.gz'
    with gzip.open(packets,'wt') as f:
        for row in rows:f.write(json.dumps(row)+'\n')
    return packets,index,tmp_path/'out.sqlite',rows


def test_queries_shared_sources_separate(tmp_path,monkeypatch):
    packets,index,out,_=fixture(tmp_path,monkeypatch)
    before=index.read_bytes();result=prepare(packets,index,out)
    assert result['sources']==2 and result['query_groups']==1
    assert index.read_bytes()==before
    found=search(out,'cafe tune')
    assert {r['source_key'] for r in found}=={'a','b'}
    assert all(r['identity_verified'] is False and r['query_group_role']=='request_cache_only_not_verified_work' for r in found)


@pytest.mark.parametrize('change',[{'source_sha256':'wrong'},{'identity_verified':True},{'rights_clearance':'allowed'},{'search_route':'guess'}])
def test_fail_closed(tmp_path,monkeypatch,change):
    _,_,_,rows=fixture(tmp_path,monkeypatch)
    rows[0].update(change)
    packets=tmp_path/'packets.jsonl.gz'
    with gzip.open(packets,'wt') as f:
        for row in rows:f.write(json.dumps(row)+'\n')
    with pytest.raises(ValueError):prepare(packets,tmp_path/'work.sqlite',tmp_path/'out.sqlite')
    assert not (tmp_path/'out.sqlite').exists()


def test_duplicate_or_incomplete_sources(tmp_path,monkeypatch):
    packets,index,out,rows=fixture(tmp_path,monkeypatch)
    for values in ([rows[0]], [rows[0],rows[0]]):
        with gzip.open(packets,'wt') as f:
            for row in values:f.write(json.dumps(row)+'\n')
        with pytest.raises(ValueError):prepare(packets,index,out)
        assert not out.exists()


def test_search_bounds_and_literal_tokens(tmp_path,monkeypatch):
    packets,index,out,_=fixture(tmp_path,monkeypatch);prepare(packets,index,out)
    assert search(out,'cafe OR missing')==[]
    assert search(out,'!!!')==[]
    for limit in (0,101,True):
        with pytest.raises(ValueError):search(out,'cafe',limit=limit)


def test_different_creators_do_not_share_query_group(tmp_path,monkeypatch):
    packets,index,out,rows=fixture(tmp_path,monkeypatch)
    for row,creator in zip(rows,['Alice','Bob']):
        row.update(creator_search_hint=creator,search_route='title_and_creator_candidate_search')
    with gzip.open(packets,'wt') as f:
        for row in rows:f.write(json.dumps(row)+'\n')
    assert prepare(packets,index,out)['query_groups']==2
    assert search(out,'Alice')[0]['source_key']=='a'


def test_storage_reserve_and_existing_output(tmp_path,monkeypatch):
    packets,index,out,_=fixture(tmp_path,monkeypatch)
    out.write_text('keep')
    with pytest.raises(FileExistsError):prepare(packets,index,out)
    assert out.read_text()=='keep'
    out.unlink()
    monkeypatch.setattr('samuged.search_recovery.shutil.disk_usage',lambda p:namedtuple('Usage','total used free')(0,0,10*1024**3))
    with pytest.raises(ValueError,match='reserve'):prepare(packets,index,out)
    assert not out.exists()
