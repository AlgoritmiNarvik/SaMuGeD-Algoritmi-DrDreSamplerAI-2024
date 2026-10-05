import json
from pathlib import Path
import mido
import pytest
from samuged.aligned import AlignedConfig
from samuged.audit import audit
from samuged.catalog import build_catalog
from samuged.corpus_release import prepare
from samuged.dataset import atomic_json, build, canonical_json, file_digest


def fixture(root):
    source=root/'pdmx_full_input';source.mkdir()
    midi=mido.MidiFile(ticks_per_beat=480);track=mido.MidiTrack();midi.tracks.append(track)
    for _ in range(4):
        for pitch in (60,62,64,65,67,65,64,62):
            track.extend([mido.Message('note_on',note=pitch,velocity=90,time=0),mido.Message('note_off',note=pitch,time=240)])
    official=[]
    for name in ('a.mid','b.mid'):
        midi.save(source/name)
        official.append(dict(source_path=name,artist_from_path='Score contributor',title_from_path='Study',
            identity_evidence='upstream_score_metadata_unverified',upstream_metadata=dict(composer_name='Composer',
                genres='classical',license='publicdomain',license_url='https://example.org/declaration')))
    metadata=root/'pdmx_metadata.jsonl';metadata.write_text(''.join(canonical_json(r)+'\n' for r in official))
    full=root/'pdmx_full';batch=full/'builds/000000'
    build(source,batch,AlignedConfig(),algorithm='aligned_closed',workers=1)
    assert audit(source,batch,require_full=True,reextract=True)['passed']
    atomic_json(full/'plan.json',{'source_files':2,'metadata_sha256':file_digest(metadata)})
    atomic_json(full/'progress.json',{'status':'extracted_and_batch_audited_pending_global_splits'})
    registry=root/'registry.json';registry.write_text(json.dumps({'sources':[dict(dataset_id='pdmx',name='PDMX',version='test',
        source_url='https://example.org/pdmx',dataset_license='CC-BY-4.0',composition_rights='declared',redistribution_status='unknown')]}))
    return registry,batch


def test_snapshot_has_verified_artifacts_and_sortable_labels(tmp_path):
    registry,batch=fixture(tmp_path);out=tmp_path/'release'
    receipt=prepare(tmp_path,out,registry=registry,max_output_mb=2)
    assert receipt['complete_extraction'] and receipt['source_files']==2
    assert receipt['duplicate_groups']==1
    rows=[json.loads(line) for line in (out/'sources.jsonl').read_text().splitlines()]
    assert all(r['split']=='unassigned' and r['split_group'] is None for r in rows)
    assert rows[0]['upstream_metadata']['source_tempo_events']
    assert rows[0]['artist_from_path']=='Score contributor'
    assert rows[0]['phrases'] and 'matched_note_pairs' not in rows[0]['phrases'][0]['occurrences'][0]
    for row in rows:
        for phrase in row['phrases']:assert file_digest(out/phrase['midi_path'])==phrase['midi_sha256']
    build_catalog(out/'catalog_manifest.json',out/'catalog.sqlite',max_output_mb=4,min_free_mb=0)
    import sqlite3
    with sqlite3.connect(out/'catalog.sqlite') as db:
        assert db.execute("SELECT COUNT(*) FROM annotations WHERE category='genre_raw' AND value='classical'").fetchone()[0]==2
        assert db.execute('SELECT DISTINCT redistribution_status FROM phrase_catalog').fetchall()==[('unknown',)]


def test_unfinished_snapshot_requires_explicit_partial_label(tmp_path):
    registry,_=fixture(tmp_path)
    atomic_json(tmp_path/'pdmx_full/progress.json',{'status':'running'})
    with pytest.raises(ValueError,match='not finished'):prepare(tmp_path,tmp_path/'out',registry=registry,max_output_mb=2)
    receipt=prepare(tmp_path,tmp_path/'partial',registry=registry,allow_partial=True,max_output_mb=2)
    assert not receipt['complete_extraction']


def test_changed_audited_manifest_cannot_enter_snapshot(tmp_path):
    registry,batch=fixture(tmp_path)
    with (batch/'sources.jsonl').open('a') as stream:stream.write('{}\n')
    with pytest.raises(ValueError,match='changed after audit'):prepare(tmp_path,tmp_path/'out',registry=registry,max_output_mb=2)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('artifact',['source','midi'])
def test_changed_music_cannot_enter_snapshot(tmp_path,artifact):
    registry,batch=fixture(tmp_path)
    row=json.loads(next((batch/'sources.jsonl').open()))
    target=tmp_path/'pdmx_full_input'/row['source_path'] if artifact=='source' else batch/row['phrases'][0]['midi_path']
    target.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed after audit'):
        prepare(tmp_path,tmp_path/'out',registry=registry,max_output_mb=2)
    assert not (tmp_path/'out').exists()
    assert not list(tmp_path.glob('samuged-release-*'))
