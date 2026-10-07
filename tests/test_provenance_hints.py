import gzip
import json
import sqlite3
from collections import namedtuple

import pytest

from samuged.provenance_hints import classify, declaration, export, extract, prepare, summary

Usage = namedtuple('Usage', 'total used free')


def hints_of(*fields):
    return {key: value for key, value in extract([(f'field.{kind}', kind, text) for kind, text in fields]).items()}


def types(*fields):
    return {(kind, value) for kind, value in hints_of(*fields)}


@pytest.mark.parametrize('title,code', [('Mary Nairn. Ru2.155', 'Ru2.155'), ('Wild Goose Chace. JJo.174', 'JJo.174'),
    ('Sleepy Moggy. JJo6.15', 'JJo6.15'), ('The Hurry. Roose.0097', 'Roose.0097'), ('Untitled by Pleyel EHo.106', 'EHo.106')])
def test_collection_codes_stay_unmapped(title, code):
    hints = hints_of(('title', title))
    basis, evidence = hints[('collection_code', code)]
    assert basis == 'field.title' and evidence['mapping'] == 'unmapped_requires_review'
    assert set(evidence) == {'prefix', 'number', 'mapping'}


@pytest.mark.parametrize('title,expected', [('Suite No. 1 BWV 1007', {('catalogue_number', 'BWV 1007')}),
    ('Symphony 5', set()), ('Sonata Op. 27 No. 3', {('catalogue_number', 'Op 27')}), ('Sonata K. 331', {('catalogue_number', 'K 331')}),
    ('Impromptu D. 899', {('catalogue_number', 'D 899')}), ('Prelude in D 5', set()), ('Psalm23', set()), ('Blink182', set())])
def test_catalogue_numbers_are_not_collection_codes(title, expected):
    assert types(('title', title)) == expected


def test_year_life_dates_and_named_extraction():
    found = types(('creator', 'Urheber unbekannt, 1720 belegt'))
    assert ('year_claim', '1720') in found and ('unattributed_claim', 'Urheber unbekannt, 1720 belegt') in found
    found = types(('creator', 'Urheber unbekanntDatum in der hier transkribierten schriftlichen Quelle: 1776 - 1791'))
    assert ('year_claim', '1776-1791') in found and not any(k == 'life_dates_claim' for k, _ in found)
    hints = hints_of(('creator', "Turlough O'Connor (1670-1738)"))
    assert hints[('life_dates_claim', '1670-1738')][1]['name_text'] == "Turlough O'Connor"
    assert hints[('named_creator_extracted', "Turlough O'Connor")][1]['role'] == 'composer_claim_unverified'
    assert not any(k == 'year_claim' for k, _ in hints)
    assert ('named_creator_extracted', 'John Stanley') in types(('creator', 'John Stanley,1712-1786'))
    found = types(('creator', 'Urheber: Johann Abraham Peter SchultErstbeleg: 1779 (Komponiert)Datum in der Quelle: 1792'))
    assert {('named_creator_extracted', 'Johann Abraham Peter Schult'), ('year_claim', '1779'), ('year_claim', '1792')} <= found
    assert types(('title', 'Lancers 1820')) == set() and ('year_claim', '1820') in types(('subtitle', 'printed c. 1820'))
    assert types(('creator', 'Urheber: unbekannt')) == {('unattributed_claim', 'Urheber: unbekannt')}


def test_collector_unattributed_and_generic_artist():
    hints = hints_of(('creator', 'after Mr. Beamish'), ('creator', 'Arr. Camille Blecher'), ('creator', 'collected by C. Sharp'),
                     ('creator', 'sung by Mrs. Powell'), ('creator', 'Transcribed by Simon Furey F:http://www.vwml.org/record/RVW2/1/134Mrs. Powell'))
    roles = {value: evidence['role'] for (kind, value), (_, evidence) in hints.items() if kind == 'collector_attribution'}
    assert roles == {'after Mr. Beamish': 'collector', 'Arr. Camille Blecher': 'arranger', 'collected by C. Sharp': 'collector',
                     'sung by Mrs. Powell': 'performer_source', 'Transcribed by Simon Furey F': 'transcriber'}
    assert types(('title', 'After the Ball')) == set()
    for value in ('Traditional', 'Trad.', 'anon.', '?', 'Unknown'):
        assert ('unattributed_claim', value) in types(('creator', value))
    assert types(('creator', 'Frédéric Chopin')) == set()
    assert ('generic_uploader_artist', 'Misc tunes') in types(('artist', 'Misc tunes'))
    assert not any(k == 'generic_uploader_artist' for k, _ in types(('artist', 'Mischa Maisky'), ('creator', 'Misc tunes')))


def test_subtitle_hints():
    found = types(('subtitle', 'Bezeichnung standardisiert: Husaren Dantz [Sammelbezeichnung];'), ('subtitle', 'Longways for as many as will.'),
                  ('subtitle', '2nd Setting'), ('title', 'Reel setting 3'))
    assert {('standardized_title_claim', 'Husaren Dantz [Sammelbezeichnung]'), ('dance_instruction', 'Longways for as many as will.'),
            ('setting_number', '2'), ('setting_number', '3')} <= found
    assert types(('subtitle', 'Sea shanty'), ('subtitle', 'From Christmas Carols Ancient & Modern')) == set()


def test_urls_keep_only_domain_outside_public_archives():
    hints = hints_of(('creator', 'CMDRESIGNATIONhttp://www.hymnary.org/hymn/ELW2006/782'), ('url', 'https://musescore.com/user/9/scores/123'),
                     ('url', 'https://www.example.com/profile/jane?id=7'), ('url', 'https://musescore.com/user/9'),
                     ('creator', 'F:http://www.vwml.org/record/RVW2/1/134Mrs. Powell'))
    refs = {value: evidence for (kind, value), (_, evidence) in hints.items() if kind == 'external_reference'}
    assert refs['http://www.hymnary.org/hymn/ELW2006/782']['archive_record'] is True
    assert refs['http://www.vwml.org/record/RVW2/1/134'] == dict(domain='vwml.org', archive_record=True)
    assert 'https://musescore.com/user/9/scores/123' in refs and refs['example.com']['archive_record'] is False
    assert 'musescore.com' in refs and not any('jane' in value or 'user/9' == value[-6:] for value in refs)


def test_identifier_only_title():
    assert ('identifier_only_title', '[ID 10-117a]') in extract([], 'identifier_only', '[ID 10-117a]')
    assert extract([], 'usable', 'A tune') == {}


def classed(title_status='usable', creator=None, titles=(), **fields):
    hints = extract([(f'x.{k}', k.rstrip('0123456789'), v) for k, v in fields.items()])
    return classify(title_status, creator, hints, titles)


def test_claim_class_precedence():
    assert classed('identifier_only', 'J. S. Bach')[:2] == ('identifier_only_source', 'source_identifier_or_musical_review')
    claim, route, reasons = classed(creator='J. S. Bach', title='Tune. JJo.174')
    assert (claim, route) == ('named_creator_claim', 'title_and_creator_candidate_search')
    assert 'collection_or_collector_or_misc_tunes' in reasons
    assert classed(creator='Urheber unbekannt', creator1='Urheber unbekannt')[0] == 'unattributed_traditional'
    assert classed(creator1="Turlough O'Connor (1670-1738)")[0] == 'named_creator_claim'
    assert classed(creator1='Urheber unbekannt, 1720 belegt', artist='Misc tunes')[0] == 'dated_anonymous_source'
    assert classed(subtitle='Bezeichnung standardisiert: Menuett', creator1='Datum: 1776')[0] == 'dated_anonymous_source'
    assert classed(artist='Misc tunes')[0] == 'traditional_collection_transcription'
    assert classed(artist='Misc Praise Songs')[0] == 'hymn_or_sacred_reference'
    assert classed(titles=['Old Hundredth Psalm'])[0] == 'hymn_or_sacred_reference'
    assert classed(creator1='CMD http://hymnary.org/hymn/X/1')[0] == 'hymn_or_sacred_reference'
    assert classed(creator1='Traditional')[0] == 'unattributed_traditional'
    assert classed(titles=['A tune']) == ('title_only_unclassified', 'title_only_namesake_review', ['no_specific_signal'])


def track(title, composer=None, artist=None, status='usable'):
    return json.dumps(dict(original=dict(title=title, composer=composer, artist=artist),
        upstream=dict(title=title, song_name=title, artist_name=artist, composer_name=composer), search_title=title, title_status=status))


def score(sha, title, subtitle='', composer='', artist='Misc tunes', pd=True):
    return json.dumps(dict(source_sha256=sha, public_score_fields=dict(title=title, file_score_title=title, subtitle=subtitle,
        composer_name=composer, artist_name=artist, song_name=title, is_public_domain=pd, license='publicdomain' if pd else 'cc-by',
        url='https://musescore.com/user/1/scores/7'), upstream_declarations=dict(license_url='https://creativecommons.org/publicdomain/mark/1.0/', is_public_domain=pd)))


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.provenance_hints.shutil.disk_usage', lambda p: Usage(0, 0, 20*1024**3))
    work, scores = tmp_path/'work.sqlite', tmp_path/'scores.sqlite'
    rows = [('a', 'ha', 'pdmx', 'Wild Goose Chace. JJo.174', None, 'usable', None, 'Misc tunes'),
            ('b', 'hb', 'pdmx', '[ID 10-117a]', None, 'identifier_only', None, 'Misc tunes'),
            ('c', 'hc', 'lakh', 'How Will I Know', 'Whitney Houston', 'usable', None, 'Whitney Houston'),
            ('d', 'hd', 'pdmx', 'Abide with me', None, 'usable', None, 'Misc Praise Songs')]
    with sqlite3.connect(work) as db:
        db.executescript('''CREATE TABLE queue(source_key TEXT PRIMARY KEY,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,
            query_kind TEXT,status TEXT,error TEXT,updated_on TEXT);
            CREATE TABLE track_metadata(source_key TEXT PRIMARY KEY,title_status TEXT,creator_status TEXT,creator_basis TEXT,gaps_json TEXT,evidence_json TEXT);''')
        for key, sha, dataset, title, creator, status, composer, artist in rows:
            db.execute('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)', (key, sha, dataset, title, creator, 'work', 'pending', None, None))
            db.execute('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)', (key, status, 'missing', 'unresolved', '[]', track(title, composer, artist, status)))
    with sqlite3.connect(scores) as db:
        db.execute('CREATE TABLE score_metadata(source_key TEXT PRIMARY KEY,source_sha256 TEXT,score_id TEXT,source_url TEXT,composer_claim TEXT,review_required INTEGER,evidence_json TEXT)')
        db.executemany('INSERT INTO score_metadata VALUES (?,?,?,?,?,?,?)', [
            ('a', 'ha', '7', 'https://musescore.com/user/1/scores/7', '', 0, score('ha', 'Wild Goose Chace. JJo.174', 'Longways for as many as will.')),
            ('b', 'hb', '8', 'https://musescore.com/user/1/scores/8', 'Trad.', 0, score('hb', '[ID 10-117a]', pd=False)),
            ('d', 'hd', '9', 'https://musescore.com/user/1/scores/9', '', 0, score('hd', 'Abide with me', artist='Misc Praise Songs'))])
    return work, scores, tmp_path/'hints.sqlite'


def test_prepare_summary_and_export(tmp_path, monkeypatch):
    work, scores, out = fixture(tmp_path, monkeypatch)
    before = (work.read_bytes(), scores.read_bytes())
    result = prepare(work, scores, out)
    assert (work.read_bytes(), scores.read_bytes()) == before
    assert result['sources'] == 4 and result['identity_verified'] is False and result['rights_clearance'] == 'not_established'
    assert result['claim_classes'] == {'lakh': {'named_creator_claim': 1}, 'pdmx': {'traditional_collection_transcription': 1,
        'identifier_only_source': 1, 'hymn_or_sacred_reference': 1}}
    assert summary(out) == {k: result[k] for k in summary(out)}
    assert result['hint_types']['upstream_pd_declaration'] == dict(rows=2, sources=2)
    with sqlite3.connect(out) as db:
        assert db.execute('SELECT identity_verified,rights_clearance,policy FROM provenance').fetchone() == (0, 'not_established', 'provenance-hints-v1')
        assert set(json.loads(db.execute('SELECT inputs_json FROM provenance').fetchone()[0]).values()) == {result['inputs'][str(work)], result['inputs'][str(scores)]}
        assert db.execute("SELECT DISTINCT identity_status,rights_clearance FROM claim_class").fetchall() == [('unverified', 'not_established')]
        evidence = json.loads(db.execute("SELECT evidence_json FROM hints WHERE hint_type='upstream_pd_declaration'").fetchone()[0])
        assert evidence['declaration_not_clearance'] is True
    exported = tmp_path/'hints.jsonl.gz'
    assert export(out, exported)['lines'] == 4
    with gzip.open(exported, 'rt') as f:
        lines = [json.loads(line) for line in f]
    first = lines[0]
    assert set(first) == {'source_key', 'source_sha256', 'dataset_id', 'claim_class', 'search_route', 'reasons', 'hints',
                          'identity_status', 'rights_clearance', 'policy'}
    assert first['source_key'] == 'a' and first['identity_status'] == 'unverified' and first['policy'] == 'provenance-hints-v1'
    assert {'hint_type', 'value', 'basis_field', 'evidence'} == set(first['hints'][0])
    assert {'collection_code', 'dance_instruction', 'generic_uploader_artist'} <= {h['hint_type'] for h in first['hints']}
    with pytest.raises(FileExistsError):
        export(out, exported)
    with pytest.raises(ValueError, match='limit'):
        export(out, tmp_path/'small.jsonl.gz', max_output_mb=0)
    assert not (tmp_path/'small.jsonl.gz').exists()


def test_source_binding_failure(tmp_path, monkeypatch):
    work, scores, out = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(scores) as db:
        db.execute("UPDATE score_metadata SET source_sha256='other' WHERE source_key='a'")
    with pytest.raises(ValueError, match='binding'):
        prepare(work, scores, out)
    assert {p.name for p in tmp_path.iterdir()} == {'work.sqlite', 'scores.sqlite'}
    with sqlite3.connect(scores) as db:
        db.execute("UPDATE score_metadata SET source_sha256='ha' WHERE source_key='a'")
        db.execute("INSERT INTO score_metadata VALUES ('z','hz','1','',NULL,0,'{}')")
    with pytest.raises(ValueError, match='outside'):
        prepare(work, scores, out)


def test_output_exists_and_storage_reserve(tmp_path, monkeypatch):
    work, scores, out = fixture(tmp_path, monkeypatch)
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        prepare(work, scores, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.provenance_hints.shutil.disk_usage', lambda p: Usage(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        prepare(work, scores, out)
    assert not out.exists()


def test_attribution_marker_is_kept_as_evidence():
    hints = hints_of(('creator', 'attr. John French (1753-1803)'))
    assert hints[('named_creator_extracted', 'John French')][1]['attribution_marker'] is True


def test_pd_declaration_conflict_is_flagged_without_new_class():
    conflict = dict(public_score_fields=dict(license='publicdomain', license_id=8, license_version='4.0', is_public_domain=False),
                    upstream_declarations=dict(is_public_domain=False, license_url='https://creativecommons.org/publicdomain/mark/1.0/',
                                               license_string='<a href="x">Public domain</a>'))
    value, evidence = declaration(conflict)
    assert value == 'publicdomain' and evidence['declaration_conflict'] is True and evidence['declaration_not_clearance'] is True
    assert set(evidence) == {'is_public_domain', 'upstream_is_public_domain', 'license', 'license_id', 'license_version',
                             'license_url', 'declaration_not_clearance', 'declaration_conflict'}
    hints = {('upstream_pd_declaration', value): ('score.public_score_fields.license', evidence)}
    assert classify('usable', None, hints) == ('title_only_unclassified', 'title_only_namesake_review',
                                               ['no_specific_signal', 'upstream_pd_declaration_conflict'])
    conflict['public_score_fields']['is_public_domain'] = True
    assert 'declaration_conflict' not in declaration(conflict)[1]


def test_additional_public_archives_keep_full_url():
    refs = {value for kind, value in types(('creator', 'see https://www.cpdl.org/wiki/index.php/Old_Hundredth'),
                                           ('creator', 'https://library.efdss.org/archives/record/123'))}
    assert refs == {'https://www.cpdl.org/wiki/index.php/Old_Hundredth', 'https://library.efdss.org/archives/record/123'}
