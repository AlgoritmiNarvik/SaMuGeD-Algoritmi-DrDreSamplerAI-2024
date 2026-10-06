import json
import sqlite3
import pytest
from samuged.metadata_links import candidates


def test_ambiguous_recordings_remain_candidates(tmp_path,monkeypatch):
    p=tmp_path/'metadata.sqlite';db=sqlite3.connect(p)
    db.execute('CREATE TABLE records(source_key TEXT,artist TEXT,title TEXT,dataset_id TEXT)')
    db.execute('INSERT INTO records VALUES (?,?,?,?)',('source','Nirvana','Come_As_You_Are','lakh'));db.commit();db.close()
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'recordings':[{'id':str(i),'title':'Come as You Are','artist-credit':[{'name':'Nirvana'}]} for i in range(2)]}).encode()
    monkeypatch.setattr('urllib.request.urlopen',lambda request,timeout:Response())
    result=candidates(p)
    assert len(result['candidates'])==2
    assert all(r['match_status']=='candidate' for r in result['candidates'])
    assert all(r['metadata_license']=='CC0-1.0' for r in result['candidates'])


def test_service_failure_stops_requests(tmp_path,monkeypatch):
    p=tmp_path/'metadata.sqlite';db=sqlite3.connect(p)
    db.execute('CREATE TABLE records(source_key TEXT,artist TEXT,title TEXT,dataset_id TEXT)')
    db.executemany('INSERT INTO records VALUES (?,?,?,?)',[(str(i),'Artist','Song','lakh') for i in range(2)]);db.commit();db.close()
    def fail(*args,**kwargs):raise TimeoutError()
    monkeypatch.setattr('urllib.request.urlopen',fail)
    result=candidates(p);assert result['source_queries']==1 and len(result['failures'])==1
