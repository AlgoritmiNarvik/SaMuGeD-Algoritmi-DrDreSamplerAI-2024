import pytest
from samuged.track_metadata import describe,creator_kind,clean


def record(**changes):
    return dict(dict(title='A song',composer=None,artist=None,dataset_id='pdmx'),**changes)


@pytest.mark.parametrize('value',['Misc tunes','Misc Traditional','Anonymous','anon.','Urheber unbekannt','arr. Someone','after Mr Beamish','NA'])
def test_generic_and_role_ambiguous_names_not_promoted(value):
    result=describe(record(),dict(artist_name=value))
    assert result['search_creator'] is None
    assert result['clearance_status']=='not_established'


def test_artist_hint_retains_uncertain_role_and_raw_values():
    result=describe(record(),dict(artist_name='Grant Colfax Tullar',song_name='A song'))
    assert result['search_creator']=='Grant Colfax Tullar'
    assert result['creator_basis']=='upstream_artist_role_unverified'
    assert result['original']['composer'] is None
    assert 'creator_role_unverified' in result['gaps']


def test_encoding_and_identifier_titles_remain_visible():
    assert describe(record(title='[ID 10-117a]'))['title_status']=='identifier_only'
    assert describe(record(title='Ø¹ÙÙÙ'))['title_status']=='suspect_encoding'
    assert clean('NA') is None
    assert creator_kind('Frédéric Chopin')=='named_claim'


def test_named_composer_takes_precedence_and_artist_not_owner():
    result=describe(record(composer='J. S. Bach'),dict(artist_name='Publisher'))
    assert result['search_creator']=='J. S. Bach'
    assert result['identity_status']=='unresolved'
    assert 'composition_rights_unverified' in result['gaps']


def test_full_audit_keeps_inputs_and_rejects_missing_binding(tmp_path,monkeypatch):
    import csv,json,sqlite3
    from test_work_identity import setup
    from samuged.track_metadata import prepare,FIELDS
    from samuged.dataset import file_digest
    meta,catalog,work=setup(tmp_path,monkeypatch)
    csv_path=tmp_path/'pdmx.csv'
    with csv_path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['mid',*FIELDS]);writer.writeheader()
    before=file_digest(work)
    output=tmp_path/'audited.sqlite'
    receipt=prepare(meta,catalog,csv_path,work,output)
    assert receipt['source_records']==1 and file_digest(work)==before
    with sqlite3.connect(output) as db:
        row=json.loads(db.execute('SELECT evidence_json FROM track_metadata').fetchone()[0])
        assert row['clearance_status']=='not_established'
        assert row['original']['composer']=='Bach'
    with pytest.raises(FileExistsError):prepare(meta,catalog,csv_path,work,output)
    with sqlite3.connect(meta) as db:db.execute("UPDATE records SET title='changed'")
    with pytest.raises(ValueError,match='binding'):prepare(meta,catalog,csv_path,work,tmp_path/'bad.sqlite')
    assert not (tmp_path/'bad.sqlite').exists()


def test_equal_bytes_give_hints_and_conflicts_never_rights(tmp_path,monkeypatch):
    import csv,json,sqlite3
    from test_work_identity import setup
    from samuged.track_metadata import prepare,FIELDS,duplicate_hints
    meta,catalog,work=setup(tmp_path,monkeypatch)
    csv_path=tmp_path/'pdmx.csv'
    with csv_path.open('w',newline='') as f:csv.DictWriter(f,fieldnames=['mid',*FIELDS]).writeheader()
    audited=tmp_path/'audit.sqlite';prepare(meta,catalog,csv_path,work,audited)
    with sqlite3.connect(audited) as db:
        db.execute("INSERT INTO queue VALUES ('missing','abc','local','Song',NULL,'work','missing_labels',NULL,NULL)")
        evidence=describe(record())
        db.execute('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)',('missing','usable','missing','unresolved',json.dumps(evidence['gaps']),json.dumps(evidence)))
    output=tmp_path/'hints.sqlite';receipt=duplicate_hints(audited,output)
    assert receipt['creator_hints']==1
    with sqlite3.connect(output) as db:
        evidence=json.loads(db.execute("SELECT evidence_json FROM track_metadata WHERE source_key='missing'").fetchone()[0])
        assert evidence['search_creator']=='Bach' and evidence['original']['composer'] is None
        assert evidence['clearance_status']=='not_established'
    with sqlite3.connect(audited) as db:
        db.execute("INSERT INTO queue VALUES ('different','abc','local','Song','Mozart','work','pending',NULL,NULL)")
    conflicted=tmp_path/'conflict.sqlite';receipt=duplicate_hints(audited,conflicted)
    assert receipt['creator_hints']==0 and receipt['conflicting_hint_records']==1
    with sqlite3.connect(conflicted) as db:
        assert db.execute("SELECT creator FROM queue WHERE source_key='missing'").fetchone()[0] is None


def test_audit_gaps_are_searchable_and_inherited_by_phrase(tmp_path,monkeypatch):
    import csv
    from test_work_identity import setup
    from samuged.track_metadata import prepare,FIELDS
    from samuged.work_identity import search_candidates,phrase_evidence
    meta,catalog,work=setup(tmp_path,monkeypatch)
    csv_path=tmp_path/'pdmx.csv'
    with csv_path.open('w',newline='') as f:csv.DictWriter(f,fieldnames=['mid',*FIELDS]).writeheader()
    output=tmp_path/'audit.sqlite';prepare(meta,catalog,csv_path,work,output)
    rows=search_candidates(output,gap='composition_rights_unverified')
    assert len(rows)==1 and rows[0]['source_metadata_audit']['original']['composer']=='Bach'
    assert search_candidates(output,gap='nonexistent')==[]
    assert phrase_evidence(catalog,meta,output)[0]['source_metadata_audit']['identity_status']=='unresolved'
    with pytest.raises(ValueError,match='audit required'):search_candidates(work,gap='anything')
