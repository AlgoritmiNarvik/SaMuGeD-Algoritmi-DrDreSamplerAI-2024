import json
from pathlib import Path

import mido
import pytest

from samuged.dataset import _work, build, code_digest, digest, discover, finalize, source_labels
from samuged.phrases import Config
from dataclasses import asdict


def write_song(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for rep in range(3):
        for i, pitch in enumerate([60, 62, 65, 64, 67, 65, 62, 60, 64, 65, 69, 67]):
            track.append(mido.Message('note_on', note=pitch, velocity=90,
                                      time=24+(2880 if rep and i == 0 else 0)))
            track.append(mido.Message('note_off', note=pitch, time=216))
    midi.save(path)


def test_hidden_artist_included_and_external_symlink_skipped(tmp_path):
    source = tmp_path/'source'
    write_song(source/'.38 Special'/'song.mid')
    external = tmp_path/'other.mid'
    write_song(external)
    (source/'link.mid').symlink_to(external)
    assert [p.relative_to(source).as_posix() for p in discover(source)] == ['.38 Special/song.mid']


def test_numbered_arrangements_group_by_artist_and_title():
    assert source_labels('Artist/Title.2.mid')['song_key'] == source_labels('Artist/Title.mid')['song_key']
    assert source_labels('Artist/Title.mid')['song_key'] != source_labels('Other/Title.mid')['song_key']


def test_worker_export_resume_and_corrupt_artifact_rebuilt(tmp_path):
    source = tmp_path/'input.mid'
    output = tmp_path/'out'
    write_song(source)
    args = (str(source), 'Artist/input.mid', str(output), asdict(Config(lengths=(12,))), 'test-code', True, False)
    row = _work(args)
    assert row['status'] == 'ok'
    assert len(row['phrases']) >= 1
    target = output/row['phrases'][0]['midi_path']
    before = target.read_bytes()
    assert _work(args) == row
    target.write_bytes(b'broken')
    rebuilt = _work(args)
    assert target.read_bytes() == before
    assert rebuilt['phrases'] == row['phrases']


def test_invalid_file_is_accounted_for(tmp_path):
    source=tmp_path/'bad.mid'
    source.write_bytes(b'not MIDI')
    row = _work((str(source),'Artist/bad.mid',str(tmp_path/'out'),asdict(Config()),'test',False,False))
    assert row['status'] == 'error' and row['error_type'] == 'ValueError'
    assert row['phrases'] == []


def test_family_split_conflicts_and_artist_groups(tmp_path):
    rows=[]
    for i in range(100):
        rows.append({'source_id':f'{i:024x}', 'source_path':f'A{i}/x.mid','source_sha256':f'{i:064x}',
            'artist_from_path':f'A{i}','title_from_path':'x','artist_key':f'a{i}','song_key':f'{i}',
            'status':'ok','note_count':12,'musical_sha256':str(i),'elapsed_seconds':0.1,
            'ticks_per_beat':480,'phrases':[{'kind':'melodic','family_id':'same'}]})
    summary=finalize(rows,tmp_path, {})
    phrases=[json.loads(line) for line in (tmp_path/'phrases.jsonl').read_text().splitlines()]
    assert summary['source_files']==100
    assert summary['family_split_conflict_rows']>0
    assert {r['split'] for r in phrases} == {'train','overlap_excluded'}
    assert len({r['split'] for r in phrases if r['split'] != 'overlap_excluded'})==1


def test_identical_bytes_keep_path_specific_provenance(tmp_path):
    source=tmp_path/'input.mid'
    write_song(source)
    common=(str(source),'',str(tmp_path/'out'),asdict(Config(lengths=(12,))),'same',False,False)
    a=_work((common[0],'ArtistA/First.mid',*common[2:]))
    b=_work((common[0],'ArtistB/Second.mid',*common[2:]))
    assert a['source_sha256']==b['source_sha256']
    assert a['source_id']!=b['source_id']
    assert b['artist_from_path']=='ArtistB' and b['title_from_path']=='Second'


def test_transient_error_is_retried(tmp_path, monkeypatch):
    import samuged.dataset as module
    source=tmp_path/'input.mid'
    write_song(source)
    args=(str(source),'Artist/song.mid',str(tmp_path/'out'),asdict(Config(lengths=(12,))),'test',False,False)
    original=module.load_midi
    def fail(_):
        raise OSError('transient read failure')
    monkeypatch.setattr(module,'load_midi',fail)
    assert _work(args)['status']=='error'
    monkeypatch.setattr(module,'load_midi',original)
    assert _work(args)['status']=='ok'


def test_missing_file_is_accounted_for(tmp_path):
    row=_work((str(tmp_path/'gone.mid'),'Artist/gone.mid',str(tmp_path/'out'),asdict(Config()),'test',False,False))
    assert row['outcome']=='read_error'
    assert row['source_sha256'] is None


def test_word_order_artist_aliases_group_conservatively():
    assert source_labels('Jackson_Michael/Smooth_Criminal.mid')['artist_key'] == source_labels('Michael_Jackson/Smooth_Criminal.1.mid')['artist_key']


@pytest.mark.parametrize('algorithm', ['aligned', 'aligned_indexed'])
def test_aligned_worker_exports_source_verified_occurrences(tmp_path, algorithm):
    from samuged.aligned import AlignedConfig
    source = tmp_path/'source.mid'
    output = tmp_path/'aligned'
    write_song(source)
    row = _work((str(source), 'Artist/source.mid', str(output),
                 asdict(AlignedConfig()), 'aligned-run', True, False, algorithm, False))
    assert row['status'] == 'ok'
    assert row['phrases']
    for phrase in row['phrases']:
        assert phrase['matcher_flags']['monotone_alignment']
        assert (output/phrase['midi_path']).is_file()
        assert all(occ['matched_note_pairs'] and occ['source_verified']
                   for occ in phrase['occurrences'])


def test_build_rejects_mismatched_algorithm_configuration(tmp_path):
    from samuged.aligned import AlignedConfig
    with pytest.raises(TypeError, match='AlignedConfig'):
        build(tmp_path, tmp_path/'out', Config(), algorithm='aligned')
    with pytest.raises(TypeError, match='reference algorithm requires Config'):
        build(tmp_path, tmp_path/'out', AlignedConfig())
    with pytest.raises(ValueError, match='algorithm'):
        build(tmp_path, tmp_path/'out', Config(), algorithm='unknown')


def test_recovery_is_opt_in_and_source_receipts_are_saved(tmp_path):
    source = tmp_path/'source.mid'
    write_song(source)
    midi = mido.MidiFile(source)
    midi.tracks[0].insert(0, mido.MetaMessage('key_signature', key='C'))
    midi.save(source)
    original = source.read_bytes().replace(b'\xff\x59\x02\x00\x00', b'\xff\x59\x02\x08\x00', 1)
    source.write_bytes(original)
    args = (str(source), 'Artist/source.mid', str(tmp_path/'out'), asdict(Config()),
            'recovery-run', False, False)
    strict = _work(args)
    assert strict['status'] == 'error'
    assert strict['error_type'] == 'KeySignatureError'
    recovered = _work((*args, 'reference', True))
    assert recovered['status'] == 'ok'
    assert len(recovered['metadata_repairs']) == 1
    assert recovered['metadata_repairs'][0]['original_payload_hex'] == '0800'
    assert recovered['phrases']
    assert source.read_bytes() == original
