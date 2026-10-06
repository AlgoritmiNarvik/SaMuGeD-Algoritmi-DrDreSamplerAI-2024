import json
import sqlite3
import pytest

from samuged.work_identity import (initialize, run, status, review, phrase_evidence,
    Client, BudgetReached, project, NoRedirect)

WORK = '00000000-0000-0000-0000-000000000001'
RECORDING = '00000000-0000-0000-0000-000000000002'


def setup(tmp_path, monkeypatch):
    from test_catalog_metadata import index
    from samuged.source_rights import prepare as scan
    from samuged.source_usage import prepare
    meta, _ = index(tmp_path, monkeypatch)
    catalog = tmp_path/'catalog.sqlite'
    rights = tmp_path/'rights.sqlite'
    scan(meta, catalog, rights, {'local': tmp_path}, workers=1)
    usage = tmp_path/'usage.sqlite'
    prepare(rights, catalog, usage)
    work = tmp_path/'works.sqlite'
    result = initialize(usage, work)
    assert result['sources'] == 1
    return usage, catalog, work


def test_candidates_review_and_phrase_inheritance(tmp_path, monkeypatch):
    meta, catalog, work = setup(tmp_path, monkeypatch)
    def get(self, entity, identifier=None, query=None):
        writer = {'type': 'composer', 'artist': {'name': 'Bach', 'id': WORK}}
        payload = dict(id=WORK, title='Song', relations=[writer], iswcs=['T-000.000.001-0'])
        return ({'works': [payload]} if query else payload), {'url': 'https://musicbrainz.org/work/'+WORK}
    monkeypatch.setattr(Client, 'get', get)
    outcome = run(work)
    assert outcome['work_candidates'] == 1
    row = phrase_evidence(catalog, meta, work)[0]
    assert row['identity_status'] == 'unresolved' and row['work_id'] is None
    assert row['candidates'][0]['work_id'] == WORK
    key = row['source_key']
    revision = review(work, key, WORK, 'accepted', 'Reviewer',
        'https://example.org/analysis', 'Musical comparison and source score checked')
    row = phrase_evidence(catalog, meta, work, source_key=key)[0]
    assert row['revision'] == revision and row['work_id'] == WORK
    assert row['musical_work_license_status'] == 'unknown'
    assert row['new_music_reuse_clearance'] == row['overall_clearance_status'] == 'not_established'
    review(work, key, WORK, 'unresolved', 'Reviewer', 'https://example.org/analysis', 'Conflicting evidence')
    assert phrase_evidence(catalog, meta, work)[0]['work_id'] is None
    assert status(work)['provider_access'][0]['status'] == 'access_required'
    with sqlite3.connect(meta) as db:db.execute("UPDATE source_usage SET score_review_status='conflict'")
    with pytest.raises(ValueError, match='metadata hash'):phrase_evidence(catalog, meta, work)


def test_cache_budget_and_projection(tmp_path, monkeypatch):
    _, _, path = setup(tmp_path, monkeypatch)
    class Response:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def read(self, n):return json.dumps(dict(id=WORK, title='Song', tags=['do not retain'], score=100)).encode()
    monkeypatch.setattr('time.sleep', lambda _: None)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        client = Client(db, 1)
        monkeypatch.setattr(client.opener, 'open', lambda *a, **k: Response())
        payload, evidence = client.get('work', identifier=WORK)
        assert 'tags' not in payload and 'score' not in payload
        assert client.get('work', identifier=WORK)[1] == evidence and client.requests == 1
        with pytest.raises(BudgetReached):client.get('recording', identifier=RECORDING)
        with pytest.raises(ValueError):client.get('work', identifier='../../bad')
    assert project('work', {'relations': [{'type':'publisher', 'target-type':'artist', 'artist':{'name':'X'}}]})['relations'] == []
    with pytest.raises(ValueError):NoRedirect().redirect_request(None, None, 302, None, None, 'http://localhost')


def test_failure_and_budget_resume(tmp_path, monkeypatch):
    _, _, path = setup(tmp_path, monkeypatch)
    def budget(*args, **kwargs):raise BudgetReached()
    monkeypatch.setattr(Client, 'get', budget)
    assert run(path)['coverage'] == {'pending': 1}
    def fail(*args, **kwargs):raise TimeoutError()
    monkeypatch.setattr(Client, 'get', fail)
    assert run(path)['coverage'] == {'error': 1}
    monkeypatch.setattr(Client, 'get', lambda *a, **k: ({'works': []}, {}))
    assert run(path)['coverage'] == {'no_candidate': 1}
    with pytest.raises(ValueError):run(path, requests=True)
    with pytest.raises(FileExistsError):initialize(tmp_path/'usage.sqlite', path)


def test_recording_relationship_and_ambiguity(tmp_path, monkeypatch):
    _, _, path = setup(tmp_path, monkeypatch)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE queue SET query_kind='recording',creator='Artist'")
    def get(self, entity, identifier=None, query=None):
        if query:return {'recordings': [{'id':RECORDING, 'title':'Song', 'artist-credit':[{'name':'Artist', 'joinphrase':''}]}]}, {}
        if entity == 'recording':return {'relations':[{'type':'performance', 'work':{'id':WORK}}]}, {}
        return {'id':WORK, 'title':'Song', 'relations':[]}, {}
    monkeypatch.setattr(Client, 'get', get)
    assert run(path)['coverage'] == {'candidate':1}
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT recording_id FROM work_candidates').fetchone()[0] == RECORDING
    with pytest.raises(ValueError):review(path, 'missing', WORK, 'accepted', 'R', 'https://example.org', 'check')
    with pytest.raises(ValueError):review(path, 'missing', WORK, 'accepted', 'R', 'javascript:bad', 'check')


def test_scoped_ownership_claim_does_not_grant_use(tmp_path, monkeypatch):
    from samuged.work_identity import observe_rights
    meta, catalog, path = setup(tmp_path, monkeypatch)
    key = phrase_evidence(catalog, meta, path)[0]['source_key']
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (key, WORK, '', 'Song', '{}', 'candidate'))
    evidence = dict(source_key=key, work_id=WORK, provider='manual', rights_layer='composition',
        intended_use='midi_publication', territory='NO', holder='Declared holder',
        license_declaration='permission not established', conditions=['Verify arrangement rights'],
        metadata_license='local review only', evidence_url='https://example.org/score', reviewer='Reviewer')
    observe_rights(path, **evidence)
    row = phrase_evidence(catalog, meta, path)[0]
    assert row['rights_observations'][0]['territory'] == 'NO'
    assert row['rights_observations'][0]['status'] == 'claimed_unverified'
    assert row['work_id'] is None and row['midi_publication_clearance'] == 'not_established'
    with pytest.raises(ValueError, match='access'):observe_rights(path, **dict(evidence, provider='the_mlc'))
    with pytest.raises(ValueError):observe_rights(path, **dict(evidence, rights_layer='all_rights'))


def test_process_lock_and_missing_index(tmp_path, monkeypatch):
    import fcntl
    _, _, path = setup(tmp_path, monkeypatch)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):run(path)
    with pytest.raises(FileNotFoundError):status(tmp_path/'missing.sqlite')
    assert not (tmp_path/'missing.sqlite').exists()


def test_cache_tampering_and_wrong_api_entity(tmp_path, monkeypatch):
    _, _, path = setup(tmp_path, monkeypatch)
    class Response:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def read(self, n):return json.dumps(dict(id=RECORDING, title='Wrong')).encode()
    monkeypatch.setattr('time.sleep', lambda _: None)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        client = Client(db, 5)
        monkeypatch.setattr(client.opener, 'open', lambda *a, **k: Response())
        with pytest.raises(ValueError, match='entity mismatch'):client.get('work', identifier=WORK)
        assert db.execute('SELECT count(*) FROM cache').fetchone()[0] == 0
        client.get('recording', identifier=RECORDING)
        db.execute("UPDATE cache SET payload_json='{}'");db.commit()
        with pytest.raises(ValueError, match='cache hash'):client.get('recording', identifier=RECORDING)


def test_search_boundaries_and_query_literal(tmp_path, monkeypatch):
    from samuged.work_identity import search_candidates
    _, _, path = setup(tmp_path, monkeypatch)
    assert len(search_candidates(path, text='Song')) == 1
    assert search_candidates(path, text="' OR 1=1 --") == []
    assert search_candidates(path, text='%') == []
    with pytest.raises(ValueError):search_candidates(path, limit=True)
    with pytest.raises(ValueError):search_candidates(path, work_id='../bad')


@pytest.mark.parametrize('a,b,expected',[
    ('Collins_Phil','Phil Collins','normalized_tokens'),
    ('J. S. Bach','Johann Sebastian Bach','initials_candidate'),
    ('Bach','Johann Sebastian Bach',None),
    ('J. Bach','C. Bach',None),
    ('Frédéric Chopin','Frederic Chopin','normalized_tokens')])
def test_name_variants_remain_candidate_evidence(a,b,expected):
    from samuged.work_identity import creator_agreement
    assert creator_agreement(a,b)==expected


def test_apostrophe_and_accent_normalization():
    from samuged.work_identity import label
    assert label("Can't Stop")==label('Cant_Stop')
    assert label('Sérieuses')==label('serieuses')


def test_service_backoff_respects_request_budget(tmp_path,monkeypatch):
    import urllib.error
    from email.message import Message
    _,_,path=setup(tmp_path,monkeypatch)
    waits=[];monkeypatch.setattr('time.sleep',waits.append)
    headers=Message();headers['Retry-After']='8'
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row;client=Client(db,2)
        def busy(*args,**kwargs):raise urllib.error.HTTPError('https://musicbrainz.org',503,'busy',headers,None)
        monkeypatch.setattr(client.opener,'open',busy)
        with pytest.raises(BudgetReached):client.get('work',identifier=WORK)
        assert client.requests==2 and 8 in waits and 15 in waits
        assert db.execute('SELECT count(*) FROM cache').fetchone()[0]==0


def test_work_alias_requires_creator_agreement(tmp_path,monkeypatch):
    _,_,path=setup(tmp_path,monkeypatch)
    def get(self,entity,identifier=None,query=None):
        if query:return {'works':[{'id':WORK,'title':'Different canonical title'}]},{}
        return {'id':WORK,'title':'Different canonical title','aliases':['Song'],
            'relations':[{'type':'composer','artist':{'name':'Bach'}}]},{}
    monkeypatch.setattr(Client,'get',get)
    assert run(path)['coverage']=={'candidate':1}
