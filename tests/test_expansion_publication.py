import gzip
import hashlib
import json
import sqlite3

import pytest

pq = pytest.importorskip('pyarrow.parquet')

from samuged import expansion_publication as ep
from samuged import work_identity_merge as wim
from samuged.catalog import build_catalog
from samuged.dataset import digest, file_digest
from samuged.publication_schema import phrase_schema
from scripts.prepare_publication import parquet_views
from test_work_identity_merge import make_indexes

REGISTRY_ROWS = [dict(dataset_id='lakh', dataset_license='CC-BY-4.0'), dict(dataset_id='pdmx', dataset_license='CC-BY-4.0'),
                 dict(dataset_id='maestro', dataset_license='CC-BY-NC-SA-4.0')]


def midi_payload(n):
    return b'MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0' + bytes([n])


def phrase(source_id, source_path, sha, n, artist_from_path):
    payload = midi_payload(n)
    return dict(phrase_id=f'p{n:02d}', source_id=source_id, source_path=source_path, source_sha256=sha, kind='melodic',
        family_id=f'f{n}', part_name='Lead', occurrences=[dict(start_tick=0, end_tick=10), dict(start_tick=20, end_tick=30)],
        matcher_flags=dict(source_verified=True), start_tick=0, end_tick=10, ticks_per_beat=480, note_count=6,
        occurrence_count=2, program=0, duration_beats=4.0, recurrence_score=0.5, onsets_beats=[0.0, 1.0],
        durations_beats=[1.0, 1.0], pitches=[60, 62], velocities=[80, 90], midi_path=f'midi/melodic/p{n:02d}.mid',
        midi_sha256=hashlib.sha256(payload).hexdigest(), artist_from_path=artist_from_path, title_from_path='path title',
        split='train', split_group='batch-group'), payload


def write_build(folder, sources, phrases):
    """A build folder with the audited artifact set: manifests, config, summary, MIDI and a passing audit."""
    (folder/'midi'/'melodic').mkdir(parents=True)
    (folder/'sources.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in sources))
    (folder/'phrases.jsonl').write_text(''.join(json.dumps(p)+'\n' for p, _ in phrases))
    for p, payload in phrases:
        (folder/p['midi_path']).write_bytes(payload)
    (folder/'build_config.json').write_text(json.dumps(dict(code_sha256='code', run_key='run')))
    (folder/'summary.json').write_text('{}')
    audit = dict(passed=True, full_source_coverage_required=True, reextraction_required=True, source_files=len(sources),
                 phrase_rows=len(phrases), source_manifest_sha256=file_digest(folder/'sources.jsonl'),
                 phrase_manifest_sha256=file_digest(folder/'phrases.jsonl'),
                 build_config_sha256=file_digest(folder/'build_config.json'), summary_sha256=file_digest(folder/'summary.json'))
    (folder/'audit.json').write_text(json.dumps(audit))


def usage_row(key, sha, dataset):
    row = {k: None for k in ep.USAGE_TEXT}
    row.update({k: 0 for k in ep.USAGE_INT})
    row.update(corpus_conditions=['Attribution'], copyright_notices=[], external_metadata_candidates=[],
               usage_conditions=['Attribution'], usage_evidence=dict(dataset_url='https://example.org'))
    row.update(source_key=key, source_sha256=sha, dataset_id=dataset, overall_clearance_status='not_established',
               title='Title', status='ok')
    return row


def hint_row(key, sha, dataset):
    return dict(source_key=key, source_sha256=sha, dataset_id=dataset, claim_class='unknown', search_route='none',
                reasons=['r'], hints=[dict(hint_type='x', value='y')], identity_status='unverified',
                rights_clearance='not_established', policy='provenance-hints-v1')


@pytest.fixture
def env(tmp_path):
    root = tmp_path/'expansion'
    full = root/'pdmx_full'
    pdmx_sources, batches = [], []
    for b in range(2):
        rows, items = [], []
        for s in range(2):
            n = b*2+s
            sid, path, sha = f'pdmx-{n}', f'mid/{n}/score{n}.mid', f'sha-pdmx-{n}'
            item = phrase(sid, path, sha, n, 'mid')
            items.append(item)
            rows.append(dict(source_id=sid, source_path=path, source_sha256=sha, status='ok'))
            pdmx_sources.append(dict(source_id=sid, source_path=path, source_sha256=sha, status='ok',
                artist_from_path=f'Score artist {n}', title_from_path=f'Score title {n}',
                identity_evidence='upstream_score_metadata_unverified', phrases=[item[0]]))
        write_build(full/'builds'/f'00000{b}', rows, items)
    (full/'plan.json').write_text(json.dumps(dict(source_files=4)))
    (full/'progress.json').write_text(json.dumps(dict(status='extracted_and_batch_audited_pending_global_splits')))
    maestro = root/'maestro_full_closed'
    item = phrase('maestro-0', '2004/perf.midi', 'sha-maestro-0', 9, '2004')
    write_build(maestro, [dict(source_id='maestro-0')], [item])
    records = dict(pdmx=pdmx_sources, maestro=[dict(source_id='maestro-0', source_path='2004/perf.midi',
        source_sha256='sha-maestro-0', status='ok', artist_from_path='', title_from_path='Etude', phrases=[item[0]])],
        lakh=[dict(source_id='lakh-0', source_path='A/B.mid', source_sha256='sha-lakh-0', status='ok',
                   artist_from_path='A', title_from_path='B', phrases=[])])
    snapshot = tmp_path/'snapshot'; snapshot.mkdir()
    for name, rows in records.items():
        (snapshot/f'{name}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    manifest = dict(schema_version=1, builds=[dict(dataset_id=n, records=f'{n}.jsonl') for n in records],
        datasets=[dict(dataset_id=n, name=n, version='1', source_url='https://example.org', dataset_license='CC-BY-4.0',
                       composition_rights='unknown', redistribution_status='unknown') for n in records])
    (snapshot/'manifest.json').write_text(json.dumps(manifest))
    catalog = snapshot/'combined_catalog.sqlite'
    build_catalog(snapshot/'manifest.json', catalog, max_output_mb=4, min_free_mb=0)
    with sqlite3.connect(catalog) as db:
        builds = dict(db.execute('SELECT dataset_id,build_id FROM builds'))
    sources = [(digest((builds[d], r['source_id'])), r['source_sha256'], d) for d, rows in records.items() for r in rows]
    sources.sort()
    queue = [(k, h, d, 'Title', 'Creator', 'recording' if d == 'lakh' else 'work', 'pending') for k, h, d in sources]
    paths = make_indexes(tmp_path, queue, candidates=False)
    identity = tmp_path/'work_identity_v06.jsonl.gz'
    wim.prepare(paths['work_index'], paths['offline_index'], paths['recordings_index'], paths['assessment'], identity,
                metadata=paths['metadata'], catalogue_index=paths['catalogue_index'])
    usage, hints = tmp_path/'usage_metadata.jsonl.gz', tmp_path/'provenance_hints.jsonl.gz'
    for path, make in ((usage, usage_row), (hints, hint_row)):
        with gzip.open(path, 'wt') as stream:
            for k, h, d in sources:
                stream.write(json.dumps(make(k, h, d))+'\n')
    registry = tmp_path/'sources.json'
    registry.write_text(json.dumps(dict(sources=REGISTRY_ROWS)))
    kwargs = dict(pdmx_root=full, maestro_dataset=maestro, catalog=catalog, usage=usage, hints=hints, identity=identity,
                  assessment=paths['assessment'], registry=registry)
    return tmp_path, kwargs, sources


def build(env, name='public', **changes):
    tmp_path, kwargs, _ = env
    out = tmp_path/name
    result = ep.prepare(out, **{**kwargs, **changes})
    return out, result


def table(out, name):
    return pq.read_table(out/'data'/name)


def test_phrase_configs_reuse_the_published_schema(env):
    out, result = build(env)
    assert result['rows'] == dict(pdmx_melodic=4, maestro_melodic=1, source_terms=6, provenance_hints=6, work_identity=6)
    for name in ep.PHRASE_CONFIGS:
        for part in (out/'data'/name).glob('*.parquet'):
            assert pq.ParquetFile(part).schema_arrow.equals(phrase_schema())
    # The Lakh builder writes the same schema, so the configurations concatenate without casting.
    tmp_path = env[0]
    lakh = tmp_path/'lakh'; lakh.mkdir()
    item, payload = phrase('lakh-0', 'A/B.mid', 'sha-lakh-0', 7, 'A')
    (lakh/'midi'/'melodic').mkdir(parents=True)
    (lakh/item['midi_path']).write_bytes(payload)
    (lakh/'phrases.jsonl').write_text(json.dumps(item)+'\n')
    parquet_views(lakh, tmp_path/'lakh_public', 'closed')
    assert pq.read_schema(tmp_path/'lakh_public'/'data'/'closed_melodic'/'all.parquet').equals(phrase_schema())


def test_artist_and_title_come_from_the_catalog(env):
    out, _ = build(env)
    rows = table(out, 'pdmx_melodic').to_pylist()
    assert [(r['source_id'], r['artist'], r['title']) for r in rows] == [
        (f'pdmx-{n}', f'Score artist {n}', f'Score title {n}') for n in range(4)]
    assert {r['split'] for r in rows} == {'unassigned'}
    keys = {s for s, _, _ in env[2]}
    assert all(r['split_group'] in keys for r in rows)  # catalog split_group is empty, so the source key is used
    maestro = table(out, 'maestro_melodic').to_pylist()[0]
    assert (maestro['artist'], maestro['title'], maestro['source_path']) == ('', 'Etude', '2004/perf.midi')
    assert hashlib.sha256(maestro['midi_bytes']).hexdigest() == maestro['midi_sha256']
    assert json.loads(maestro['occurrences_json'])[1]['start_tick'] == 20


def test_midi_hash_mismatch_stops_without_output(env):
    tmp_path, kwargs, _ = env
    midi = next((kwargs['pdmx_root']/'builds'/'000001'/'midi'/'melodic').glob('*.mid'))
    midi.write_bytes(b'changed')
    with pytest.raises(ValueError, match='MIDI hash'):
        ep.prepare(tmp_path/'public', **kwargs)
    assert not (tmp_path/'public').exists()
    assert not list(tmp_path.glob('.public.*'))


def test_phrase_bound_to_a_different_catalog_source_is_refused(env):
    tmp_path, kwargs, _ = env
    batch = kwargs['pdmx_root']/'builds'/'000000'
    rows = [json.loads(line) for line in (batch/'phrases.jsonl').read_text().splitlines()]
    rows[0]['source_sha256'] = 'other'
    (batch/'phrases.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    audit = json.loads((batch/'audit.json').read_text())
    audit['phrase_manifest_sha256'] = file_digest(batch/'phrases.jsonl')
    (batch/'audit.json').write_text(json.dumps(audit))
    with pytest.raises(ValueError, match='differs from the catalog'):
        ep.prepare(tmp_path/'public', **kwargs)


def test_failed_or_changed_audit_is_refused(env):
    tmp_path, kwargs, _ = env
    (kwargs['maestro_dataset']/'summary.json').write_text('{"changed": true}')
    with pytest.raises(ValueError, match='changed after audit'):
        ep.prepare(tmp_path/'public', **kwargs)


def test_sharding_splits_rows_by_file(env):
    out, _ = build(env, rows_per_file=3)
    assert sorted(p.name for p in (out/'data'/'pdmx_melodic').glob('*.parquet')) == ['part-00000.parquet', 'part-00001.parquet']
    assert [pq.ParquetFile(p).metadata.num_rows for p in sorted((out/'data'/'source_terms').glob('*.parquet'))] == [3, 3]
    assert table(out, 'pdmx_melodic').num_rows == 4
    assert ep.verify(out)['configs']['pdmx_melodic']['files'] == 2


def test_metadata_configs_have_unique_shared_keys(env):
    import pyarrow as pa
    out, _ = build(env)
    keys = {name: table(out, name).column('source_key').to_pylist() for name in ep.METADATA_CONFIGS}
    expected = sorted(k for k, _, _ in env[2])
    assert all(sorted(v) == expected for v in keys.values())
    terms = table(out, 'source_terms')
    assert terms.schema.equals(ep.metadata_schema('source_terms'))
    row = terms.to_pylist()[0]
    assert json.loads(row['usage_evidence_json']) == dict(dataset_url='https://example.org')
    assert row['warning_count'] == 0 and 'corpus_conditions' not in row
    identity_table = table(out, 'work_identity')
    assert identity_table.schema.equals(ep.metadata_schema('work_identity'))
    assert identity_table.schema.field('dump_catalogue_status').type == pa.string()
    assert identity_table.schema.field('dump_catalogue_reason').type == pa.string()
    identity = identity_table.to_pylist()
    assert {(r['dataset_id'], r['dump_catalogue_status']) for r in identity} == {
        ('pdmx', None), ('lakh', None), ('maestro', 'no_candidate')}
    assert {r['identity_status'] for r in identity} == {'unresolved'} and {r['candidate_count'] for r in identity} == {0}
    assert json.loads(identity[0]['candidates_json']) == []
    phrase_ids = set(table(out, 'pdmx_melodic').column('source_id').to_pylist())
    assert phrase_ids <= set(terms.column('source_id').to_pylist())


def test_duplicate_metadata_key_is_refused(env):
    tmp_path, kwargs, sources = env
    with gzip.open(kwargs['hints'], 'wt') as stream:
        for k, h, d in [sources[0], *sources]:
            stream.write(json.dumps(hint_row(k, h, d))+'\n')
    with pytest.raises(ValueError, match='duplicate source key in provenance_hints'):
        ep.prepare(tmp_path/'public', **kwargs)


def test_unexpected_metadata_field_is_refused(env):
    tmp_path, kwargs, sources = env
    with gzip.open(kwargs['usage'], 'wt') as stream:
        for k, h, d in sources:
            stream.write(json.dumps({**usage_row(k, h, d), 'surprise': 1})+'\n')
    with pytest.raises(ValueError, match='keys differ'):
        ep.prepare(tmp_path/'public', **kwargs)


def test_identity_export_must_match_its_assessment(env):
    tmp_path, kwargs, _ = env
    other = tmp_path/'other_assessment.sqlite'
    other.write_bytes(kwargs['assessment'].read_bytes() + b'\0')
    with pytest.raises(ValueError, match='another assessment'):
        ep.prepare(tmp_path/'public', **{**kwargs, 'assessment': other})


def test_receipt_contents(env):
    out, _ = build(env)
    receipt = json.loads((out/'evidence'/'expansion_build_receipt.json').read_text())
    assert receipt['identity_verified'] is False and receipt['rights_clearance'] == 'not_established'
    assert receipt['configs']['pdmx_melodic']['license'] == 'CC-BY-4.0'
    assert 'Public Domain Mark' in receipt['configs']['pdmx_melodic']['per_source']
    assert receipt['configs']['maestro_melodic']['license'] == 'CC-BY-NC-SA-4.0'
    assert receipt['configs']['work_identity']['musicbrainz_fields'] == 'CC0-1.0'
    assert {k: v['rows'] for k, v in receipt['configs'].items()} == dict(
        pdmx_melodic=4, maestro_melodic=1, source_terms=6, provenance_hints=6, work_identity=6)
    assert receipt['dataset_sources'] == dict(lakh=1, maestro=1, pdmx=4)
    for name in ('catalog', 'usage', 'hints', 'identity', 'identity_receipt', 'assessment', 'registry'):
        assert len(receipt['inputs'][name]['sha256']) == 64
    assert receipt['inputs']['pdmx']['batches'] == 2 and receipt['inputs']['pdmx']['complete_extraction'] is True
    inventory = json.loads((out/'evidence'/'expansion_inventory.json').read_text())['files']
    assert 'evidence/expansion_build_receipt.json' in inventory and 'data/pdmx_melodic/part-00000.parquet' in inventory
    assert all(v['sha256'] == file_digest(out/k) for k, v in inventory.items())
    assert not (out/'README.md').exists() and not (out/'publication_inventory.json').exists()


def test_verify_passes_and_detects_a_changed_row_count(env):
    out, _ = build(env)
    result = ep.verify(out)
    assert result['passed'] is True and result['configs']['pdmx_melodic']['midi_checked'] == 4
    part = out/'data'/'maestro_melodic'/'part-00000.parquet'
    rows = pq.read_table(part)
    pq.write_table(rows.slice(0, 0), part)
    inventory_path = out/'evidence'/'expansion_inventory.json'
    inventory = json.loads(inventory_path.read_text())
    inventory['files']['data/maestro_melodic/part-00000.parquet'] = dict(bytes=part.stat().st_size, sha256=file_digest(part))
    inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match='row count differs'):
        ep.verify(out)


def test_verify_detects_a_changed_file(env):
    out, _ = build(env)
    part = out/'data'/'provenance_hints'/'part-00000.parquet'
    part.write_bytes(part.read_bytes() + b'\0')
    with pytest.raises(ValueError, match='inventory mismatch'):
        ep.verify(out)


def test_verify_detects_a_midi_hash_mismatch(env):
    out, _ = build(env)
    part = out/'data'/'pdmx_melodic'/'part-00000.parquet'
    rows = pq.read_table(part).to_pylist()
    rows[1]['midi_bytes'] = b'other'
    import pyarrow as pa
    pq.write_table(pa.Table.from_pylist(rows, schema=phrase_schema()), part)
    inventory_path = out/'evidence'/'expansion_inventory.json'
    inventory = json.loads(inventory_path.read_text())
    inventory['files']['data/pdmx_melodic/part-00000.parquet'] = dict(bytes=part.stat().st_size, sha256=file_digest(part))
    inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match='midi_sha256'):
        ep.verify(out)


def test_existing_output_is_preserved(env):
    tmp_path, kwargs, _ = env
    (tmp_path/'public').mkdir()
    with pytest.raises(FileExistsError):
        ep.prepare(tmp_path/'public', **kwargs)


def test_sample_is_deterministic_and_bounded():
    assert ep._sample(10) == list(range(10))
    sample = ep._sample(460000)
    assert sample == ep._sample(460000) and 1000 <= len(sample) <= 1001 and sample[-1] == 459999
