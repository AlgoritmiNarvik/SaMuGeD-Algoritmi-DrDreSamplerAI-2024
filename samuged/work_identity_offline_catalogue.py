"""Offline work candidates for MAESTRO rows through composer identity and catalogue numbers.

Classical titles in MAESTRO name a composer and a catalogue number (Op. 27 No. 2, BWV 846, K. 331, D. 960,
Hob. XVI:52, WoO 80, S. 178, L. 106). MusicBrainz records the same numbers as work attributes and inside work
titles and aliases. This module has two steps that never use the network, never open the mutable work index and
never write to an input.

`subset` streams the verified MusicBrainz Postgres full export once and keeps the works of the composers named in
the MAESTRO queue (identified by MBID through the offline works index, or by an unambiguous person name), with
their composer relations, aliases, attributes and part relations. `prepare` matches every MAESTRO queue row of the
immutable work index against that subset: the composer must resolve to one artist, the title must carry a
catalogue number (or a quoted nickname) and the number must agree with a work attribute, a work title or an alias
of that composer. Matched movements collapse to their parent work. The result is a sidecar index of candidates.

Nothing in either output is a verified identity or a rights clearance. A catalogue number agreement says that a
label agrees with a database entry. It does not compare the music and it says nothing about who owns the work.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata

from .dataset import file_digest
from .musicbrainz_dump import CREATOR_TYPES, META, _reserve, _ro, _signature, _unchanged, name_key
from .musicbrainz_fullexport import _command, _rows, _tar, _verified
from .work_identity import label, mbid, now
from .work_identity_offline import LICENSE, LICENSE_URL, _guard

SUBSET_POLICY = 'musicbrainz-fullexport-catalogue-subset-v1'
POLICY, PROVIDER = 'work-candidates-v4-catalogue', 'musicbrainz_fullexport_catalogue'
METHOD = 'composer_identity_and_catalogue_number_agreement_not_MIDI_identity'
DATASET = 'maestro'
BATCH, PROGRESS = 50000, 1000000
PAGES = 1048576  # 4 GiB at a fixed 4 KiB page size
UNVERIFIED = dict(identity_verified=False, rights_clearance='not_established')
REASONS = ('candidate', 'composer_not_identified', 'no_catalogue_number', 'catalogue_number_without_work',
           'missing_title', 'title_not_usable', 'missing_creator')
IDENTIFIED = ('disambiguated_by_work_relation', 'single_person_candidate')
PERSON = 1  # MusicBrainz artist type id for a person
MAX_PARENTS = 20

# Column count and kept positions per table of the full export. Tables in AT_LEAST are checked up to the last kept column.
TABLES = {
    'artist': (19, (0, 1, 2, 3, 10)),               # id, gid, name, sort_name, type
    'l_artist_work': (9, (2, 3, 1)),                # entity0 artist, entity1 work, link
    'l_work_work': (9, (2, 3, 1)),                  # entity0 parent work, entity1 part, link
    'link': (11, (0, 1)),                           # id, link_type
    'link_type': (7, (0, 4, 5, 6)),                 # id, entity_type0, entity_type1, name
    'work': (7, (0, 1, 2, 3)),                      # id, gid, name, type
    'work_alias': (8, (1, 2)),                      # work, name
    'work_attribute': (5, (1, 2, 3, 4)),            # work, type, allowed_value, text
    'work_attribute_type': (2, (0, 1)),             # id, name
    'work_attribute_type_allowed_value': (3, (0, 1, 2)),  # id, type, value
}
AT_LEAST = {'link_type', 'work_alias', 'work_attribute_type', 'work_attribute_type_allowed_value'}
STAGING = '''
CREATE TABLE s_artist(id INTEGER PRIMARY KEY,gid TEXT,name TEXT,sort_name TEXT,type INTEGER,selected_by TEXT);
CREATE TABLE s_l_artist_work(artist INTEGER,work INTEGER,link INTEGER);
CREATE TABLE s_l_work_work(parent INTEGER,part INTEGER,link INTEGER);
CREATE TABLE s_link(id INTEGER PRIMARY KEY,link_type INTEGER);
CREATE TABLE s_link_type(id INTEGER PRIMARY KEY,entity_type0 TEXT,entity_type1 TEXT,name TEXT);
CREATE TABLE s_work(id INTEGER PRIMARY KEY,gid TEXT,name TEXT,type INTEGER);
CREATE TABLE s_work_alias(work INTEGER,name TEXT);
CREATE TABLE s_work_attribute(work INTEGER,type INTEGER,allowed_value INTEGER,text TEXT);
CREATE TABLE s_work_attribute_type(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE s_work_attribute_type_allowed_value(id INTEGER PRIMARY KEY,type INTEGER,value TEXT);
'''
SUBSET_SCHEMA = '''
CREATE TABLE provenance(policy TEXT,dump_json TEXT,inputs_json TEXT,composer_count INTEGER,created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0),rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE composers(artist_id INTEGER PRIMARY KEY,gid TEXT UNIQUE,name TEXT,sort_name TEXT,type INTEGER,selected_by TEXT);
CREATE TABLE works(work_id INTEGER PRIMARY KEY,gid TEXT UNIQUE,name TEXT,type INTEGER);
CREATE TABLE work_composers(work_id INTEGER,artist_id INTEGER,role TEXT);
CREATE INDEX work_composer_key ON work_composers(artist_id,work_id);
CREATE TABLE work_aliases(work_id INTEGER,name TEXT);
CREATE INDEX work_alias_key ON work_aliases(work_id);
CREATE TABLE work_attributes(work_id INTEGER,attribute_type TEXT,value TEXT);
CREATE INDEX work_attribute_key ON work_attributes(work_id);
CREATE TABLE work_parts(parent_id INTEGER,part_id INTEGER,PRIMARY KEY(parent_id,part_id));
CREATE INDEX work_part_key ON work_parts(part_id);
CREATE TABLE work_links(work0 INTEGER,work1 INTEGER,link_type TEXT,PRIMARY KEY(work0,work1,link_type));
CREATE INDEX work_link_key ON work_links(work1);
'''
SCHEMA = f'''
CREATE TABLE provenance(policy TEXT,inputs_json TEXT,dump_json TEXT,selection_json TEXT,created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0),rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE queue(source_key TEXT PRIMARY KEY,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,
    status TEXT CHECK(status IN ('candidate','no_candidate','missing_labels')),reason TEXT CHECK(reason IN {REASONS}),
    updated_on TEXT);
CREATE INDEX queue_status ON queue(status,reason,source_key);
CREATE TABLE work_candidates(source_key TEXT REFERENCES queue,work_id TEXT,recording_id TEXT,title TEXT,evidence_json TEXT,
    match_status TEXT CHECK(match_status='candidate'),PRIMARY KEY(source_key,work_id,recording_id));
CREATE TABLE source_matches(source_key TEXT PRIMARY KEY REFERENCES queue,composer_components INTEGER,composers_resolved INTEGER,
    catalogue_keys_json TEXT,matched_work_count INTEGER,parent_work_count INTEGER,truncated INTEGER);
'''

# Catalogue systems. A key is the system prefix plus the normalized number, for example op27no2, op27, bwv846, k331,
# d960, hobxvi52, woo80, s178, l106. Systems bound to composers are only read when the composer surname is listed.
PATTERNS = [
    ('op', re.compile(r'\b(?:op|opus)\.?\s*(?:posth\.?\s*)?(\d+[a-z]?)(?:\s*[,/:-]?\s*(?:no|nr|n|number)\.?\s*(\d+))?', re.I)),
    ('woo', re.compile(r'\bwoo\.?\s*(\d+)', re.I)),
    ('k', re.compile(r'\b(?:k|kv|kk)\.?\s*(\d+[a-z]?)(?:/(\d+[a-z]?))?', re.I)),
    ('d', re.compile(r'\bd\.?\s*(\d+[a-z]?)', re.I)),
    ('bwv', re.compile(r'\bbwv\.?\s*(\d+[a-z]?)', re.I)),
    ('hob', re.compile(r'\bhob\.?\s*([xvi]+)\s*[:/.]?\s*(\d+)', re.I)),
    ('s', re.compile(r'\bs\.?\s*(\d+[a-z]?)(?:\s*[,/:-]?\s*(?:no|nr|n)?\.?\s*(\d+))?', re.I)),
    ('l', re.compile(r'\bl\.?\s*(\d+)', re.I)),
    ('sz', re.compile(r'\bsz\.?\s*(\d+)', re.I)),
    ('wq', re.compile(r'\bwq\.?\s*(\d+)', re.I)),
    ('hwv', re.compile(r'\bhwv\.?\s*(\d+)', re.I)),
    ('bv', re.compile(r'\bbv\.?\s*(\d+)', re.I)),
    ('m', re.compile(r'\bm\.?\s*(\d+)', re.I)),
]
SYSTEMS = {'k': {'mozart', 'scarlatti'}, 'd': {'schubert'}, 'bwv': {'bach'}, 'hob': {'haydn'}, 's': {'liszt'},
           'l': {'debussy', 'scarlatti'}, 'woo': {'beethoven'}, 'sz': {'bartok'}, 'wq': {'bach'}, 'hwv': {'handel'},
           'bv': {'busoni'}, 'm': {'franck'}}
# MusicBrainz work attribute type names, folded, that carry a catalogue number of one of the systems above.
ATTRIBUTE_SYSTEMS = {'opus': 'op', 'bwv': 'bwv', 'kv': 'k', 'k': 'k', 'kochel': 'k', 'd': 'd', 'deutsch': 'd', 'hob': 'hob',
                     'hoboken': 'hob', 'woo': 'woo', 's': 's', 'searle': 's', 'l': 'l', 'lesure': 'l', 'longo': 'l',
                     'kirkpatrick': 'k', 'hwv': 'hwv', 'wq': 'wq', 'wotquenne': 'wq', 'sz': 'sz', 'szollosy': 'sz',
                     'bv': 'bv', 'm': 'm'}
KEY_ATTRIBUTE = 'key'
KEY = re.compile(r'\bin\s+([a-g])\s*(sharp|flat|♯|♭|#|b)?\s*[- ]?\s*(major|minor|dur|moll)\b', re.I)
NICKNAME = re.compile(r'[“"«]([^”"»]{5,60})[”"»]')
MOVEMENT = re.compile(r'(?:[ivxl]+\.|\d+\.|no\.?\s*\d|nr\.?\s*\d|prelude|fugue|praeludium|fuga|allegr|andant|adagi|presto|larg|lent|vivace|moderato|grave|menuet|minuet|gigue|sarabande|courante|allemande|bourr|gavotte|rondo|finale|scherzo|variation|intro|aria|march|waltz|dance|act\b|acte\b|book\b|livre\b|anhang)', re.I)


def fold(text):
    text = unicodedata.normalize('NFKD', text or '').replace('‐', '-')
    return re.sub(r'[^a-z0-9#:/ ]+', ' ', text.encode('ascii', 'ignore').decode().lower())


def _name(text):
    """Folded text with single spaces, so that titles, aliases and nicknames compare exactly."""
    return ' '.join(fold(text).split())


def catalogue_keys(title, composer):
    """Catalogue keys of a title for one composer. Bare opus keys are weaker than opus with number."""
    surname = set(fold(composer).split())
    text = fold(title)
    out = set()
    for system, pattern in PATTERNS:
        if system in SYSTEMS and not (SYSTEMS[system] & surname):
            continue
        for match in pattern.finditer(text):
            groups = [g for g in match.groups() if g]
            if system == 'op':
                out.add('op'+groups[0])
                if len(groups) > 1:
                    out.add('op'+groups[0]+'no'+groups[1])
            elif system == 'hob':
                out.add('hob'+groups[0]+groups[1])
            elif system == 's' and len(groups) > 1:
                out.add('s'+groups[0]); out.add('s'+groups[0]+'no'+groups[1])
            elif system == 'k' and len(groups) > 1:
                out.add('k'+groups[0]); out.add('k'+groups[1])
            else:
                out.add(system+groups[0])
    return out


def specific(key):
    return not re.fullmatch(r'(op|s)\d+[a-z]?', key)


def attribute_keys(attribute_type, value, composer):
    """Catalogue keys of one MusicBrainz work attribute, read with the same patterns as a title."""
    system = ATTRIBUTE_SYSTEMS.get(re.sub(r'[^a-z]', '', fold(attribute_type)))
    if system is None or (system in SYSTEMS and not (SYSTEMS[system] & set(fold(composer).split()))):
        return set()
    return {k for k in catalogue_keys(f'{system}. {value}', composer) if k.startswith(system)}


def title_key(title):
    match = KEY.search(fold((title or '').replace('♯', ' sharp').replace('♭', ' flat')))  # fold drops these signs, so replace first
    if not match:
        return None
    note, accidental, mode = match.groups()
    accidental = {'#': 'sharp', 'b': 'flat', None: ''}.get(accidental, accidental or '')
    mode = {'dur': 'major', 'moll': 'minor'}.get(mode.lower(), mode.lower())
    return ' '.join(filter(None, (note, accidental, mode)))


def nicknames(title):
    return {_name(n) for n in NICKNAME.findall(title or '') if len(_name(n)) >= 5}


def _integer(value):
    return None if value is None else int(value)


def composer_names(work_index: Path, offline_index: Path):
    """MAESTRO composer components: name key to MBID (through the offline creator identities) or None."""
    found = {}
    with closing(_ro(work_index)) as work, closing(_ro(offline_index)) as offline:
        for (raw,) in work.execute('SELECT creator FROM queue WHERE dataset_id=?', (DATASET,)):
            for part in (raw or '').split(' / '):
                key = name_key(part)
                if len(key.replace(' ', '')) >= 3:
                    found.setdefault(key, None)
        for key in list(found):
            row = offline.execute('SELECT status,artist_id FROM creator_identities WHERE creator_key=?', (key,)).fetchone()
            if row and row[0] in IDENTIFIED and row[1]:
                found[key] = (mbid(row[1]), row[0])
    return found


def _load(db, tar, composers, state, limit):
    gids = {v[0] for v in composers.values() if v}
    names = set(composers)
    meta, seen = {}, set()
    for member in tar:  # Member names are compared, never used as paths.
        if member.name in META and member.isfile() and member.size <= 4096:
            meta[member.name] = tar.extractfile(member).read(4096).decode('utf-8').strip()
            continue
        if not member.name.startswith('mbdump/'):
            continue
        if set(META) - set(meta):
            raise ValueError('dump metadata members missing')
        table = member.name[len('mbdump/'):]
        if table not in TABLES:
            continue
        if table in seen or not member.isfile():
            raise ValueError(f'unexpected member {member.name}')
        seen.add(table)
        buffer = []
        for fields in _rows(tar, member, table, state, limit, TABLES, AT_LEAST):
            if table == 'artist':
                kind = _integer(fields[4])  # Names select persons only, so a group namesake is never kept by name.
                by = 'gid' if fields[1] in gids else 'name' if kind == PERSON and (name_key(fields[2]) in names or name_key(fields[3]) in names) else None
                if by is None:
                    continue
                state['kept'] += 1
                buffer.append((int(fields[0]), mbid(fields[1]), fields[2], fields[3], kind, by))
            elif table in {'l_artist_work', 'l_work_work', 'link'}:
                buffer.append(tuple(map(int, fields)))
            elif table == 'work':
                buffer.append((int(fields[0]), fields[1], fields[2], _integer(fields[3])))
            elif table == 'work_attribute':
                buffer.append((int(fields[0]), int(fields[1]), _integer(fields[2]), fields[3]))
            elif table == 'work_attribute_type_allowed_value':
                buffer.append((int(fields[0]), int(fields[1]), fields[2]))
            elif table in {'work_alias', 'work_attribute_type'}:
                buffer.append((int(fields[0]), fields[1]))
            else:  # link_type
                buffer.append((int(fields[0]), *fields[1:]))
            if len(buffer) >= BATCH:
                db.executemany(f'INSERT INTO s_{table} VALUES ({",".join("?"*len(buffer[0]))})', buffer); buffer.clear()
        if buffer:
            db.executemany(f'INSERT INTO s_{table} VALUES ({",".join("?"*len(buffer[0]))})', buffer)
    if set(META) - set(meta):
        raise ValueError('dump metadata members missing')
    if missing := sorted(set(TABLES) - seen):
        raise ValueError('dump member missing: '+', '.join(missing))
    return dict(timestamp=meta['TIMESTAMP'], replication_sequence=int(meta['REPLICATION_SEQUENCE']),
                schema_sequence=int(meta['SCHEMA_SEQUENCE']))


def _one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def _prune(db):
    """Keep the works of the selected composers, their parts and parents, and resolve names; drop the staging tables."""
    db.execute('CREATE INDEX s_aw ON s_l_artist_work(artist)')
    db.execute('CREATE INDEX s_ww0 ON s_l_work_work(parent)')
    db.execute('CREATE INDEX s_ww1 ON s_l_work_work(part)')
    db.execute('CREATE INDEX s_wa ON s_work_alias(work)')
    db.execute('CREATE INDEX s_wt ON s_work_attribute(work)')
    db.execute('INSERT INTO composers SELECT id,gid,name,sort_name,type,selected_by FROM s_artist ORDER BY id')
    roles = sorted(CREATOR_TYPES)
    marks = ','.join('?'*len(roles))
    if _one(db, f'''SELECT count(*) FROM s_l_artist_work x JOIN s_link l ON l.id=x.link JOIN s_link_type t ON t.id=l.link_type
            WHERE x.artist IN (SELECT artist_id FROM composers) AND t.name IN ({marks})
            AND (t.entity_type0!='artist' OR t.entity_type1!='work')''', *roles):
        raise ValueError('artist work link type has unexpected entity types')
    db.execute(f'''INSERT INTO work_composers SELECT DISTINCT x.work,x.artist,t.name FROM s_l_artist_work x
        JOIN composers c ON c.artist_id=x.artist JOIN s_link l ON l.id=x.link JOIN s_link_type t ON t.id=l.link_type
        WHERE t.name IN ({marks}) ORDER BY x.work,x.artist,t.name''', roles)
    db.execute('''CREATE TEMP TABLE kept(work_id INTEGER PRIMARY KEY)''')
    db.execute('INSERT OR IGNORE INTO temp.kept SELECT work_id FROM work_composers')
    parts = '''SELECT x.parent,x.part FROM s_l_work_work x JOIN s_link l ON l.id=x.link JOIN s_link_type t ON t.id=l.link_type
        WHERE t.name='parts' AND t.entity_type0='work' AND t.entity_type1='work' '''
    for _ in range(3):  # Sets, pieces, movements: three levels of parts and one level of parents.
        db.execute(f'INSERT OR IGNORE INTO temp.kept SELECT part FROM ({parts}) WHERE parent IN (SELECT work_id FROM temp.kept)')
    db.execute(f'INSERT OR IGNORE INTO temp.kept SELECT parent FROM ({parts}) WHERE part IN (SELECT work_id FROM temp.kept)')
    db.execute('INSERT INTO works SELECT id,mbid(gid),name,type FROM s_work WHERE id IN (SELECT work_id FROM temp.kept) ORDER BY id')
    if _one(db, 'SELECT count(*) FROM temp.kept WHERE work_id NOT IN (SELECT work_id FROM works)'):
        raise ValueError('work relation with a dangling reference')
    db.execute(f'''INSERT INTO work_parts SELECT DISTINCT parent,part FROM ({parts})
        WHERE parent IN (SELECT work_id FROM works) AND part IN (SELECT work_id FROM works)''')
    db.execute('''INSERT OR IGNORE INTO work_links SELECT x.parent,x.part,t.name FROM s_l_work_work x JOIN s_link l ON l.id=x.link
        JOIN s_link_type t ON t.id=l.link_type WHERE t.entity_type0='work' AND t.entity_type1='work'
        AND x.parent IN (SELECT work_id FROM works) AND x.part IN (SELECT work_id FROM works)''')
    db.execute('INSERT INTO work_aliases SELECT work,name FROM s_work_alias WHERE work IN (SELECT work_id FROM works) ORDER BY work,name')
    db.execute('''INSERT INTO work_attributes SELECT a.work,t.name,coalesce(a.text,v.value) FROM s_work_attribute a
        JOIN s_work_attribute_type t ON t.id=a.type LEFT JOIN s_work_attribute_type_allowed_value v ON v.id=a.allowed_value
        WHERE a.work IN (SELECT work_id FROM works) ORDER BY a.work,t.name''')
    db.execute('DROP TABLE temp.kept')
    for table in ('s_artist', 's_l_artist_work', 's_l_work_work', 's_link', 's_link_type', 's_work', 's_work_alias',
                  's_work_attribute', 's_work_attribute_type', 's_work_attribute_type_allowed_value'):
        db.execute(f'DROP TABLE {table}')


def subset(export_dir: Path, work_index: Path, offline_index: Path, output: Path, *, limit=None, decompressor=None):
    """Build the composer work subset once. Inputs stay read only and the archive is verified first."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    _reserve(output.parent)
    command = _command(decompressor)
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in dict(work_index=work_index, offline_index=offline_index).items()}
    composers = composer_names(work_index, offline_index)
    handle, dump, stamp = _verified(export_dir)
    dump.update(signature_status=_signature(export_dir), decompressor=' '.join(command) if command else 'python-tarfile-bz2')
    started = time.monotonic()
    state = dict(lines_read={t: 0 for t in TABLES}, total=0, kept=0, truncated=False, started=started)
    with handle, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staging, final = Path(temp)/'staging.sqlite', Path(temp)/'subset.sqlite'
        with closing(sqlite3.connect(staging)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.execute('PRAGMA synchronous=OFF'); db.execute('PRAGMA journal_mode=OFF')
            db.create_function('mbid', 1, mbid, deterministic=True)
            db.executescript(STAGING+SUBSET_SCHEMA)
            with _tar(handle, command) as tar:
                dump.update(_load(db, tar, composers, state, limit))
            _unchanged(handle, stamp)
            try:
                _prune(db)
            except sqlite3.OperationalError as exc:
                if 'user-defined function' in str(exc):
                    raise ValueError('invalid MusicBrainz ID') from exc
                raise
            dump.update(lines_read=state['lines_read'], truncated=state['truncated'])
            if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
                raise ValueError('input changed')
            inputs['composer_names'] = {k: (v[0] if v else None) for k, v in sorted(composers.items())}
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,0,?)', (SUBSET_POLICY, json.dumps(dump, ensure_ascii=False),
                       json.dumps(inputs), len(composers), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('subset integrity check failed')
            _reserve(output.parent)
            db.execute('VACUUM INTO ?', (str(final),))
        os.link(final, output)  # Fails rather than overwrite an output created meanwhile.
    result = subset_status(output)
    result.update(elapsed_seconds=round(time.monotonic()-started, 1), output_sha256=file_digest(output),
                  output_bytes=output.stat().st_size)
    return result


def subset_status(path: Path):
    with closing(_ro(path)) as db:
        policy, dump, inputs, count = db.execute('SELECT policy,dump_json,inputs_json,composer_count FROM provenance').fetchone()
        return dict(policy=policy, dump=json.loads(dump), inputs=json.loads(inputs), composer_names=count,
                    composers=_one(db, 'SELECT count(*) FROM composers'),
                    composers_by_gid=_one(db, "SELECT count(*) FROM composers WHERE selected_by='gid'"),
                    works=_one(db, 'SELECT count(*) FROM works'), work_composers=_one(db, 'SELECT count(*) FROM work_composers'),
                    work_aliases=_one(db, 'SELECT count(*) FROM work_aliases'),
                    work_attributes=_one(db, 'SELECT count(*) FROM work_attributes'),
                    attribute_types=dict(db.execute('SELECT attribute_type,count(*) FROM work_attributes GROUP BY 1 ORDER BY 2 DESC')),
                    work_parts=_one(db, 'SELECT count(*) FROM work_parts'),
                    work_links=dict(db.execute('SELECT link_type,count(*) FROM work_links GROUP BY 1 ORDER BY 2 DESC')), **UNVERIFIED)


def dump_block(sub, work_sha, offline_sha):
    rows = sub.execute('SELECT policy,dump_json,inputs_json FROM provenance').fetchall()
    if len(rows) != 1 or rows[0][0] != SUBSET_POLICY:
        raise ValueError('subset needs exactly one catalogue subset provenance row')
    dump, inputs = json.loads(rows[0][1]), json.loads(rows[0][2])
    if dump.get('truncated'):
        raise ValueError('subset pass was truncated')
    if inputs.get('work_index', {}).get('sha256') != work_sha or inputs.get('offline_index', {}).get('sha256') != offline_sha:
        raise ValueError('subset was built from other inputs')
    return dict(export_name=dump['export_name'], archive=dump['archive'], archive_sha256=dump['sha256'],
                timestamp=dump['timestamp'], replication_sequence=dump['replication_sequence'],
                schema_sequence=dump['schema_sequence'])


COMPOSER_ROLES = {'composer', 'writer', 'librettist', 'lyricist'}
ARRANGER_ROLES = set(CREATOR_TYPES) - COMPOSER_ROLES
# Work to work relation types whose entity1 is derived from entity0; a derived work is dropped when its original matched too.
DERIVED = {'arrangement', 'medley', 'based on', 'revision', 'later version', 'other version', 'orchestration',
           'translation', 'transliteration', 'later translated version', 'later parody version'}
TEMPO_WORDS = set('''allegro allegretto andante andantino adagio adagietto largo larghetto lento presto prestissimo vivace
    vivo moderato grave molto assai non troppo ma poco piu meno con brio maestoso cantabile sostenuto espressivo
    agitato appassionato tranquillo scherzando giocoso grazioso dolce animato marcia tempo di'''.split())
FORMS = {'sonata': {'sonata', 'sonate', 'sonaten', 'sonatina', 'sonatine'}, 'etude': {'etude', 'etudes', 'etuden', 'study', 'studies'},
         'nocturne': {'nocturne', 'nocturnes', 'notturno'}, 'impromptu': {'impromptu', 'impromptus'},
         'ballade': {'ballade', 'ballades', 'balladen'}, 'scherzo': {'scherzo', 'scherzi', 'scherzos'},
         'prelude': {'prelude', 'preludes', 'praeludium', 'praeludien', 'preludio'}, 'fugue': {'fugue', 'fugues', 'fuge', 'fugen', 'fuga'},
         'mazurka': {'mazurka', 'mazurkas'}, 'waltz': {'waltz', 'waltzes', 'valse', 'valses', 'walzer'},
         'polonaise': {'polonaise', 'polonaises'}, 'rondo': {'rondo', 'rondeau'},
         'variations': {'variations', 'variationen', 'variation', 'variazioni'}, 'fantasy': {'fantasy', 'fantasie', 'fantasia', 'fantaisie', 'fantasien', 'fantasiestucke', 'fantasiestuck', 'phantasiestucke', 'fantasias'},
         'toccata': {'toccata'}, 'concerto': {'concerto', 'konzert', 'konzerte', 'concertos', 'concerti'}, 'rhapsody': {'rhapsody', 'rhapsodie', 'rhapsodies', 'rhapsodien', 'rapszodia'},
         'barcarolle': {'barcarolle'}, 'intermezzo': {'intermezzo', 'intermezzi'}, 'suite': {'suite', 'suites'},
         'partita': {'partita', 'partitas'}, 'symphony': {'symphony', 'symphonie', 'sinfonie', 'sinfonia'},
         'trio': {'trio'}, 'quartet': {'quartet', 'quartett'}, 'march': {'march', 'marche', 'marsch'},
         'moment': {'moment', 'moments'}, 'humoresque': {'humoresque', 'humoreske'}, 'novelette': {'novelette', 'novelletten'},
         'elegy': {'elegy', 'elegie'}, 'berceuse': {'berceuse'}, 'tarantella': {'tarantella', 'tarantelle'},
         'chaconne': {'chaconne', 'ciaccona'}, 'passacaglia': {'passacaglia'}, 'overture': {'overture', 'ouverture'},
         'mass': {'mass', 'messe', 'missa'}, 'song': {'song', 'songs', 'lied', 'lieder'}}
FORM_OF = {word: form for form, words in FORMS.items() for word in words}


def forms_in(text):
    return {FORM_OF[w] for w in fold(text).split() if w in FORM_OF}


class Reference:
    """In memory catalogue index over the read only subset: composer and key to works."""
    def __init__(self, sub, composers):
        self.sub = sub
        self.by_gid = {gid: (aid, name) for aid, gid, name in sub.execute('SELECT artist_id,gid,name FROM composers')}
        self.gid_of = {aid: gid for gid, (aid, _) in self.by_gid.items()}
        self.by_name = defaultdict(set)
        for aid, gid, name, sort_name, kind in sub.execute('SELECT artist_id,gid,name,sort_name,type FROM composers'):
            if kind == PERSON:
                for key in {name_key(name), name_key(sort_name)}:
                    self.by_name[key].add(gid)
        self.composers = composers
        self.works = {w: (gid, name, kind) for w, gid, name, kind in sub.execute('SELECT work_id,gid,name,type FROM works')}
        self.parents, self.children = defaultdict(set), defaultdict(set)
        for parent, part in sub.execute('SELECT parent_id,part_id FROM work_parts'):
            self.parents[part].add(parent); self.children[parent].add(part)
        self.originals = defaultdict(set)  # derived work -> original works
        if sub.execute("SELECT 1 FROM sqlite_master WHERE name='work_links'").fetchone():
            for original, derived, kind in sub.execute('SELECT work0,work1,link_type FROM work_links'):
                if kind in DERIVED:
                    self.originals[derived].add(original)
        self.relations = defaultdict(list)
        self.composer_works, self.arranger_works = defaultdict(set), defaultdict(set)
        for work, artist, role in sub.execute('SELECT work_id,artist_id,role FROM work_composers ORDER BY work_id,artist_id,role'):
            self.relations[work].append((artist, role))
            (self.composer_works if role in COMPOSER_ROLES else self.arranger_works)[artist].add(work)
        self.aliases = defaultdict(list)
        for work, name in sub.execute('SELECT work_id,name FROM work_aliases'):
            self.aliases[work].append(name)
        self.attributes = defaultdict(list)
        self.key_attribute = {}
        for work, kind, value in sub.execute('SELECT work_id,attribute_type,value FROM work_attributes'):
            self.attributes[work].append((kind, value))
            if re.sub(r'[^a-z]', '', fold(kind)) == KEY_ATTRIBUTE:
                self.key_attribute[work] = fold(value).replace('-', ' ').strip()
        self.index = {}  # (artist id, 'composer' or 'all') -> ((kind, key) -> works, {folded name: works} for top level works)

    def family(self, works):
        family, frontier = set(works), set(works)
        for _ in range(3):
            frontier = {c for w in frontier for c in self.children.get(w, ())} - family
            family |= frontier
        return family

    def ancestors(self, work):
        found, frontier = set(), {work}
        for _ in range(3):
            frontier = {p for w in frontier for p in self.parents.get(w, ())} - found
            found |= frontier
        return found

    def lookup(self, artist, scope):
        """Key and nickname indexes of one composer, over own works (composer roles) or every creator role."""
        if (artist, scope) not in self.index:
            composer = self.by_gid[self.gid_of[artist]][1]
            seeds = self.composer_works.get(artist, set()) | (self.arranger_works.get(artist, set()) if scope == 'all' else set())
            keys, names = defaultdict(set), defaultdict(set)
            for work in self.family(seeds):
                for kind, value in self.attributes.get(work, ()):
                    for key in attribute_keys(kind, value, composer):
                        keys['attribute', key].add(work)
                texts = (self.works[work][1], *self.aliases.get(work, ()))
                for text in texts:
                    for key in catalogue_keys(text, composer):
                        keys['title', key].add(work)
                if not self.parents.get(work):
                    for text in texts:
                        names[_name(text)].add(work)
                        # The prefix is cut from the raw title, because fold has already turned ',' and '(' into spaces.
                        names[_name(re.split(r' ?[:,(] ?| from ', text.casefold(), maxsplit=1)[0])].add(work)
                        for nick in nicknames(text):
                            names[nick].add(work)
            self.index[artist, scope] = (keys, names)
        return self.index[artist, scope]

    def composer(self, component):
        """(gid, name, agreement, status) for one creator component, or None."""
        key = name_key(component)
        known = self.composers.get(key)
        if known and known[0] in self.by_gid:
            return known[0], self.by_gid[known[0]][1], 'composer_identity', known[1]
        gids = self.by_name.get(key, set())
        if len(gids) == 1:
            gid = next(iter(gids))
            return gid, self.by_gid[gid][1], 'composer_name_single_namesake', 'single_person_namesake'
        return None

    def reduce(self, works, key=None):
        """Reduce matched works to the works themselves: highest matched ancestor, no derived works, no movement
        of another matched work and, for a bare opus, the set rather than its numbered pieces."""
        kept = {w for w in works if not (self.ancestors(w) & works)}
        kept = {w for w in kept if not (self.originals.get(w, set()) & works)}
        titles = {w: _name(self.works[w][1]) for w in kept}
        names = {w: {titles[w], *(_name(a) for a in self.aliases.get(w, ()))} for w in kept}
        # A title of the form "<another matched work>: <movement>" names a part of that work. A work never counts its own names.
        kept = {w for w in kept if not any(titles[w].startswith(n) and titles[w][len(n):].lstrip().startswith(':')
                                           for v in kept if v != w for n in names[v])}
        whole = {w for w in kept if not is_movement(self.works[w][1], self.composer_of(w))}
        if whole:
            kept = whole
        if key is not None and not specific(key):
            sets = {w for w in kept if not any(k.startswith(key+'no') for k in self.own_keys(w))}
            if sets:
                kept = sets
        return kept, works - kept

    def composer_of(self, work):
        return ' '.join(self.by_gid[self.gid_of[a]][1] for a, _ in self.relations.get(work, ())[:1])

    def own_keys(self, work):
        composer = self.composer_of(work)
        return set().union(*(catalogue_keys(t, composer) for t in (self.works[work][1], *self.aliases.get(work, ()))))


def is_movement(title, composer):
    """True when the text after the last colon looks like a movement label without a catalogue number of its own."""
    head, sep, tail = (title or '').rpartition(':')
    tail = tail.strip()
    if not sep or not tail or catalogue_keys(tail, composer):
        return False
    return bool(MOVEMENT.match(tail)) or len(tail.split()) <= 4


def usable_nicknames(title):
    return {n for n in nicknames(title) if len(n) >= 6 and not set(n.split()) <= TEMPO_WORDS}


def _hits(ref, artist, scope, keys, names):
    """Matched works of one composer for a title: the most specific resolving catalogue key, else a nickname."""
    index, nick = ref.lookup(artist, scope)
    for key in sorted(keys, key=lambda k: (not specific(k), k)):
        works = set()
        for kind in ('attribute', 'title'):
            works |= index.get((kind, key), set())
        if works:
            kind = 'attribute' if index.get(('attribute', key)) else 'title'
            return kind, key, works
    for nick_text in sorted(names):
        works = nick.get(nick_text, set())
        if works:
            return 'nickname', nick_text, works
    return None


def match(row, ref, dump):
    key, _, _, raw_title, raw_creator, title_status, basis = row
    title, creator = label(raw_title), label(raw_creator)
    if not title:
        return 'missing_labels', 'missing_title', [], None
    if title_status not in (None, 'usable'):
        return 'missing_labels', 'title_not_usable', [], None
    if not creator:
        return 'missing_labels', 'missing_creator', [], None
    components = [c for c in (raw_creator or '').split(' / ') if label(c)]
    resolved = [(i, c, found) for i, c in enumerate(components) for found in [ref.composer(c)] if found]
    if not resolved:
        return 'no_candidate', 'composer_not_identified', [], (key, len(components), 0, '[]', 0, 0, 0)
    keys_by_component = {c: catalogue_keys(raw_title, c) for _, c, _ in resolved}
    names = usable_nicknames(raw_title)
    all_keys = sorted(set().union(*keys_by_component.values()))
    if not all_keys and not names:
        return 'no_candidate', 'no_catalogue_number', [], (key, len(components), len(resolved), '[]', 0, 0, 0)
    found = {}  # work id -> match entry
    dropped = 0
    for position, component, (gid, name, agreement, status) in resolved:
        artist = ref.by_gid[gid][0]
        hit = _hits(ref, artist, 'composer' if position == 0 else 'all', keys_by_component[component], names)
        if hit is None:
            continue
        kind, matched_key, works = hit
        kept, descendants = ref.reduce(works, matched_key if kind != 'nickname' else None)
        dropped += len(works) - len(kept)
        for work in kept:
            found.setdefault(work, dict(component=component, gid=gid, name=name, agreement=agreement, status=status, kind=kind,
                                        key=matched_key, descendants=sorted(ref.works[w][1] for w in descendants)[:10],
                                        related=sorted(ref.works[w][0] for w in descendants)[:100]))
    if not found:
        return 'no_candidate', 'catalogue_number_without_work', [], (key, len(components), len(resolved), json.dumps(all_keys), 0, 0, 0)
    truncated = len(found) > MAX_PARENTS
    chosen = sorted(found, key=lambda w: ref.works[w][0])[:MAX_PARENTS]
    source_key_text, source_forms = title_key(raw_title), forms_in(raw_title)
    rows = []
    for work in chosen:
        entry = found[work]
        gid, name, kind = ref.works[work]
        work_key = ref.key_attribute.get(work)
        key_agreement = 'unknown' if not source_key_text or not work_key else 'agrees' if work_key == source_key_text else 'disagrees'
        work_forms = set().union(forms_in(name), *(forms_in(a) for a in ref.aliases.get(work, ())),
                                 *(forms_in(ref.works[c][1]) for c in ref.children.get(work, ())))
        form_agreement = 'unknown' if not source_forms or not work_forms else 'agrees' if source_forms & work_forms else 'disagrees'
        relations = [dict(type=role, artist=dict(id=ref.gid_of[artist], name=ref.by_gid[ref.gid_of[artist]][1]))
                     for artist, role in ref.relations.get(work, ())]
        title_agreement = {'attribute': 'catalogue_number_attribute', 'title': 'catalogue_number_title', 'nickname': 'nickname_quoted'}[entry['kind']]
        basis_json = dict(source_creator_basis=basis or 'original_catalog_labels_unverified', query_title=raw_title,
            query_creator=raw_creator, title_agreement=title_agreement, catalogue_key=entry['key'],
            catalogue_key_specific=specific(entry['key']) if entry['kind'] != 'nickname' else False,
            key_agreement=key_agreement, source_key=source_key_text, work_key=work_key,
            form_agreement=form_agreement, source_forms=sorted(source_forms), work_forms=sorted(work_forms),
            creator_agreement=entry['agreement'],
            composer=dict(gid=entry['gid'], name=entry['name'], component=entry['component'], identity_status=entry['status']),
            matched_part_titles=entry['descendants'][:10], related_work_ids=entry['related'], derived_or_part_works_dropped=dropped,
            title_namesake_count=len(found), distinct_work_candidates=len(found), multiple_work_candidates=len(found) > 1,
            parents_truncated=truncated, musical_comparison='not_performed', source_identity_verified=False)
        work_block = dict(gid=gid, title=name, type=kind, relations=relations)
        evidence = dict(provider=PROVIDER, policy=POLICY, metadata_license=LICENSE, metadata_license_url=LICENSE_URL,
            method=METHOD, dump=dump, match_basis=basis_json, work=work_block,
            musical_work_license_status='unknown', rights_holder_status='not_established', **UNVERIFIED)
        rows.append((key, gid, '', name, json.dumps(evidence, ensure_ascii=False), 'candidate'))
    matched = len(found) + dropped
    return 'candidate', 'candidate', rows, (key, len(components), len(resolved), json.dumps(all_keys), matched, len(found), int(truncated))


def prepare(work_index: Path, offline_index: Path, subset_path: Path, output: Path, *, limit=None):
    """Build a new sidecar index. Inputs are opened read only and re-hashed at the end."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    _guard(output)
    started = time.monotonic()
    paths = dict(work_index=work_index, offline_index=offline_index, subset=subset_path)
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in paths.items()}
    composers = composer_names(work_index, offline_index)
    with closing(_ro(work_index)) as source:
        rows = source.execute('''SELECT q.source_key,q.source_sha256,q.dataset_id,q.title,q.creator,t.title_status,t.creator_basis
            FROM queue q LEFT JOIN track_metadata t USING(source_key) WHERE q.dataset_id=? ORDER BY q.source_key''', (DATASET,)).fetchall()
    truncated = limit is not None and len(rows) > limit
    rows = rows[:limit]
    with closing(_ro(subset_path)) as sub, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        dump = dump_block(sub, inputs['work_index']['sha256'], inputs['offline_index']['sha256'])
        ref = Reference(sub, composers)
        target = Path(temp)/'offline.sqlite'
        with closing(sqlite3.connect(target)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.executescript(SCHEMA)
            buffers = dict(queue=[], work_candidates=[], source_matches=[])
            for n, row in enumerate(rows, 1):
                key, sha, dataset, raw_title, raw_creator = row[:5]
                state, reason, candidates, matched = match(row, ref, dump)
                buffers['queue'].append((key, sha, dataset, raw_title, raw_creator, 'work', state, reason, now()))
                buffers['work_candidates'] += candidates
                if matched:
                    buffers['source_matches'].append(matched)
                if n % 500 == 0 or n == len(rows):
                    for table, values in buffers.items():
                        if values:
                            db.executemany(f'INSERT INTO {table} VALUES ({",".join("?"*len(values[0]))})', values)
                            values.clear()
            if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
                raise ValueError('input changed during prepare')
            selection = dict(dataset=DATASET, query_kind='work', limit=limit, truncated=truncated, sources=len(rows),
                             max_parent_works=MAX_PARENTS, composer_names=len(composers),
                             composer_names_identified=sum(1 for v in composers.values() if v))
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,0,?)', (POLICY, json.dumps(inputs), json.dumps(dump),
                       json.dumps(selection), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('offline index integrity check failed')
        os.link(target, output)  # Fails rather than overwrite an output created meanwhile.
    return dict(status(output), selection=selection, elapsed_seconds=round(time.monotonic()-started, 1),
                output_sha256=file_digest(output), output_bytes=output.stat().st_size)


def status(index: Path):
    with closing(_ro(index)) as db:
        agreement = "json_extract(evidence_json,'$.match_basis.title_agreement')"
        return dict(policy=POLICY, sources=_one(db, 'SELECT count(*) FROM queue'),
            queue_status=dict(db.execute('SELECT status,count(*) FROM queue GROUP BY 1')),
            reasons=dict(db.execute('SELECT reason,count(*) FROM queue GROUP BY 1')),
            work_candidates=_one(db, 'SELECT count(*) FROM work_candidates'),
            candidate_sources=_one(db, 'SELECT count(DISTINCT source_key) FROM work_candidates'),
            single_candidate_sources=_one(db, 'SELECT count(*) FROM (SELECT source_key FROM work_candidates GROUP BY 1 HAVING count(*)=1)'),
            distinct_works=_one(db, 'SELECT count(DISTINCT work_id) FROM work_candidates'),
            title_agreement=dict(db.execute(f'SELECT {agreement},count(*) FROM work_candidates GROUP BY 1')),
            key_agreement=dict(db.execute("SELECT json_extract(evidence_json,'$.match_basis.key_agreement'),count(*) FROM work_candidates GROUP BY 1")),
            form_agreement=dict(db.execute("SELECT json_extract(evidence_json,'$.match_basis.form_agreement'),count(*) FROM work_candidates GROUP BY 1")),
            creator_agreement=dict(db.execute("SELECT json_extract(evidence_json,'$.match_basis.creator_agreement'),count(*) FROM work_candidates GROUP BY 1")),
            truncated_sources=_one(db, 'SELECT count(*) FROM source_matches WHERE truncated'), **UNVERIFIED)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('subset')
    for name in ('export', 'work-index', 'offline-index', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--limit', type=int); build.add_argument('--decompressor')
    commands.add_parser('subset-status').add_argument('--subset', type=Path, required=True)
    prep = commands.add_parser('prepare')
    for name in ('work-index', 'offline-index', 'subset', 'output'):
        prep.add_argument('--'+name, type=Path, required=True)
    prep.add_argument('--limit', type=int)
    commands.add_parser('status').add_argument('--index', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'subset':
        result = subset(args.export, args.work_index, args.offline_index, args.output, limit=args.limit, decompressor=args.decompressor)
    elif args.command == 'subset-status':
        result = subset_status(args.subset)
    elif args.command == 'prepare':
        result = prepare(args.work_index, args.offline_index, args.subset, args.output, limit=args.limit)
    else:
        result = status(args.index)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
