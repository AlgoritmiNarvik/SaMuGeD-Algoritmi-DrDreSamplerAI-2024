import hashlib
import json
from pathlib import Path

import mido
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.extend_loop_space import (CORPORA, card, catalog_row, estimate_pulse, estimate_space_tempo, main,
                                       midi_onsets, rank_rows, select, structural)


def phrase(pid, *, occ=5, beats=8.0, notes=12, pitches=(60, 62, 64, 65), score=0.9, artist='A', title='T'):
    return {'phrase_id': pid, 'source_id': 's-' + pid, 'source_path': f'mid/{pid}.mid', 'source_sha256': '0' * 64,
            'artist': artist, 'title': title, 'kind': 'melodic', 'note_count': notes, 'occurrence_count': occ,
            'duration_beats': beats, 'recurrence_score': score, 'pitches': list(pitches) * (notes // len(pitches) + 1),
            'program': 0}


def test_structural_filter_matches_the_motif_rule():
    assert structural(phrase('a'))
    assert not structural(phrase('b', notes=7))
    assert not structural(phrase('c', pitches=(60, 62, 64)))
    assert not structural(phrase('d', beats=3.5))


def test_rank_rows_orders_by_occurrence_then_duration_and_keeps_one_per_title():
    rows = [phrase('low', occ=2, title='Low'), phrase('top', occ=9, beats=4.0), phrase('top-dup', occ=9, beats=8.0),
            phrase('other', occ=9, beats=8.0, title='Other'), phrase('tie', occ=9, beats=8.0, title='Tie', notes=8)]
    chosen = [r['phrase_id'] for r in rank_rows(rows, 10)]
    assert chosen == ['other', 'top-dup', 'tie', 'low']
    assert [r['phrase_id'] for r in rank_rows(rows, 2)] == ['other', 'top-dup']


def test_select_writes_a_bounded_selection_from_parquet(tmp_path):
    rows = [phrase('p1', occ=3, title='One'), phrase('p2', occ=7, title='Two'), phrase('p3', occ=1, notes=6, title='Three')]
    folder = tmp_path / 'data' / 'pdmx_melodic'
    folder.mkdir(parents=True)
    table = pa.Table.from_pylist([{**r, 'pitches': json.dumps(r['pitches'])} for r in rows])
    pq.write_table(table, folder / 'part-00000.parquet')
    selection = select('pdmx', tmp_path / 'data', tmp_path / 'sel.json', limit=5)
    assert [c['phrase_id'] for c in selection['candidates']] == ['p2', 'p1']
    assert selection['candidates'][0]['rank'] == 1
    assert selection['phrase_rows_considered'] == 3
    assert selection['rights_clearance'] == 'not_established'
    assert json.loads((tmp_path / 'sel.json').read_text())['config'] == 'pdmx_melodic'


def test_select_refuses_a_missing_configuration(tmp_path):
    with pytest.raises(ValueError):
        select('maestro', tmp_path, tmp_path / 'sel.json')


def test_catalog_row_carries_the_corpus_tempo_label():
    metadata = {'tempo_changes': [{'microseconds_per_beat': 500_000}], 'period': {'period_beats': 8.0, 'policy': 'fallback_pad_phrase_to_whole_bars_at_start_meter'},
                'cycle_seconds': 4.0, 'part': {'program': 0}}
    candidate = {'phrase_id': 'x', 'artist': '', 'title': 'Sonata', 'kind': 'melodic', 'source_path': '2004/a.midi', 'occurrence_count': 8}
    row = catalog_row(3, candidate, metadata, [0.1] * 96, CORPORA['maestro'])
    assert row['bpm'] == 120.0
    assert row['tempo_label'] == 'nominal BPM, no tempo map'
    assert row['period_method'] == 'fallback pad phrase to whole bars at start meter'
    assert row['rank'] == 3 and row['default_layer'] == 'solo'
    assert catalog_row(1, candidate, metadata, [], CORPORA['pdmx'])['tempo_label'] == 'BPM at cycle start'


def test_card_section_is_replaced_not_duplicated(tmp_path):
    path = tmp_path / 'README.md'
    path.write_text('---\ntitle: x\n---\n\n# Space\n\nBody.\n')
    groups = {'pdmx': {'title': 'PDMX scores', 'license': 'CC BY 4.0', 'rows': [1, 2]},
              'maestro': {'title': 'MAESTRO performances', 'license': 'CC BY NC SA 4.0, noncommercial use only', 'rows': [1]}}
    card(path, groups, 3)
    card(path, groups, 3)
    text = path.read_text()
    assert text.count('## Corpus expansion tabs') == 1
    assert 'Body.' in text
    assert '- MAESTRO performances: 1 loops, source license CC BY NC SA 4.0, noncommercial use only.' in text
    assert 'no tempo map' in text
    assert 'a pulse estimated from the onset intervals of each phrase' in text


def test_player_template_uses_the_row_tempo_label():
    template = (Path(__file__).resolve().parents[1] / 'scripts' / 'loop_player.html').read_text()
    assert "row.tempo_label||'BPM at cycle start'" in template


def test_player_template_appends_the_tempo_note():
    template = (Path(__file__).resolve().parents[1] / 'scripts' / 'loop_player.html').read_text()
    assert r"${row.tempo_note?' '+row.tempo_note:''}" in template


def test_player_template_honours_the_catalog_group_order():
    template = (Path(__file__).resolve().parents[1] / 'scripts' / 'loop_player.html').read_text()
    assert 'catalog.group_order' in template


def chord_beats(beats: int = 16, subdivisions=(3, 9)) -> list[float]:
    """Beats every 0.5 s, a second note 10 ms after each beat, and a 0.25 s subdivision after some beats."""
    onsets = []
    for k in range(beats):
        onsets += [k * 0.5, k * 0.5 + 0.01]
        if k in subdivisions:
            onsets.append(k * 0.5 + 0.25)
    return onsets


def test_estimate_pulse_finds_the_beat_under_chords_and_subdivisions():
    onsets = chord_beats()
    estimate = estimate_pulse(onsets)
    assert estimate['bpm'] == 120.0 and estimate['pulse_bpm'] == 120.0
    assert estimate['pulse_seconds'] == 0.5
    assert estimate['interval_count'] == 17
    assert estimate_pulse(list(reversed(onsets))) == estimate


def test_estimate_pulse_folds_a_fast_pulse_into_the_tactus_range():
    estimate = estimate_pulse([k * 0.3 for k in range(10)])
    assert estimate['pulse_bpm'] == 200.0
    assert estimate['bpm'] == 100.0


def test_estimate_pulse_needs_three_intervals():
    assert estimate_pulse([0.0, 0.5, 1.0]) is None
    assert estimate_pulse([0.0, 0.5, 1.0, 1.5]) is not None


def test_estimate_pulse_keeps_the_beat_when_one_interval_splits_in_two():
    onsets = [k * 0.5 for k in range(10)] + [0.25]  # one 0.25 s subdivision between the first two beats
    estimate = estimate_pulse(onsets)
    assert estimate['pulse_seconds'] == 0.5 and estimate['bpm'] == 120.0


def test_estimate_pulse_does_not_prefer_a_period_longer_than_a_second():
    onsets = [0.0, 0.5] + [2.5 + 2.0 * k for k in range(9)]  # one 0.5 s interval and nine 2 s intervals
    estimate = estimate_pulse(onsets)
    assert estimate['pulse_seconds'] == 0.5 and estimate['bpm'] == 120.0


def write_loop(path: Path, *, beats: int = 8, step: int = 480, tempo: int = 500_000) -> None:
    """A loop MIDI with one note every step ticks at 480 ticks per beat."""
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=tempo, time=0))
    for beat in range(beats):
        track.append(mido.Message('note_on', note=60, velocity=80, time=0 if beat == 0 else step - step // 2))
        track.append(mido.Message('note_off', note=60, velocity=0, time=step // 2))
    midi.save(path)


def make_space(root: Path, *, beats: int = 8, step: int = 480) -> Path:
    space = root / 'space'
    folder = space / 'audio' / 'pid1'
    folder.mkdir(parents=True)
    (space / 'rendering').mkdir()
    write_loop(folder / 'loop.mid', beats=beats, step=step)
    (folder / 'metadata.json').write_text('{}\n')
    (folder / 'hashes.json').write_text(json.dumps({'artifacts': [{'path': 'audio/x/loop.flac'}]}))
    row = {'rank': 1, 'phrase_id': 'pid1', 'artist': 'A', 'title': 'Study', 'kind': 'melodic', 'bpm': 120.0,
           'tempo_label': 'nominal BPM, no tempo map', 'cycle_seconds': 4.0, 'program': 0}
    group = {'title': 'MAESTRO performances', 'description': 'test group',
             'license': 'CC BY NC SA 4.0, noncommercial use only', 'rows': [row]}
    (space / 'catalog.json').write_text(json.dumps({'group_order': ['maestro'], 'groups': {'maestro': group}}))
    return space


def test_midi_onsets_follow_the_tempo_map(tmp_path):
    path = tmp_path / 'loop.mid'
    write_loop(path, beats=4, tempo=600_000)
    assert midi_onsets(path) == pytest.approx([0.0, 0.6, 1.2, 1.8])


def test_tempo_step_estimates_the_maestro_rows(tmp_path, capsys):
    space = make_space(tmp_path)
    main(['tempo', '--space', str(space), '--group', 'maestro'])
    summary = json.loads(capsys.readouterr().out)
    assert summary['maestro'] == {'rows': 1, 'estimated': 1, 'min_bpm': 120.0, 'median_bpm': 120.0, 'max_bpm': 120.0}
    row = json.loads((space / 'catalog.json').read_text())['groups']['maestro']['rows'][0]
    assert row['bpm'] == 120.0 and row['bpm_nominal'] == 120.0
    assert row['tempo_label'] == 'estimated BPM from onset intervals'
    assert 'nominal 120 BPM with no tempo map' in row['tempo_note']
    metadata = json.loads((space / 'audio' / 'pid1' / 'metadata.json').read_text())
    assert metadata['tempo_estimate']['bpm'] == 120.0 and metadata['tempo_estimate']['nominal_bpm'] == 120.0
    receipt = json.loads((space / 'rendering' / 'tempo_estimates.json').read_text())
    assert receipt['version'] == 'samuged-tempo-estimate-v1'
    assert receipt['identity_verified'] is False and receipt['rights_clearance'] == 'not_established'
    assert 'estimated BPM from onset intervals' in (space / 'index.html').read_text()


def test_tempo_rerun_keeps_the_file_nominal_tempo(tmp_path):
    space = make_space(tmp_path, step=384)  # 0.4 s onsets, 150 BPM against a nominal 120
    estimate_space_tempo(space, ['maestro'])
    estimate_space_tempo(space, ['maestro'])
    row = json.loads((space / 'catalog.json').read_text())['groups']['maestro']['rows'][0]
    assert row['bpm'] == 150.0 and row['bpm_nominal'] == 120.0
    assert 'nominal 120 BPM' in row['tempo_note']


def test_tempo_leaves_rows_without_an_estimate_unchanged(tmp_path):
    space = make_space(tmp_path, beats=2)  # one interval, below the three interval minimum
    summary = estimate_space_tempo(space, ['maestro'])
    row = json.loads((space / 'catalog.json').read_text())['groups']['maestro']['rows'][0]
    assert summary['maestro']['estimated'] == 0 and summary['maestro']['median_bpm'] is None
    assert row['bpm'] == 120.0 and 'bpm_nominal' not in row and row['tempo_label'] == 'nominal BPM, no tempo map'
    assert json.loads((space / 'audio' / 'pid1' / 'metadata.json').read_text()) == {}


def test_tempo_refreshes_the_metadata_hash(tmp_path):
    space = make_space(tmp_path)
    folder = space / 'audio' / 'pid1'
    (folder / 'hashes.json').write_text(json.dumps({'phrase_id': 'pid1', 'artifacts': [
        {'path': 'pid1/loop.mid', 'bytes': 1, 'sha256': '0' * 64},
        {'path': 'pid1/metadata.json', 'bytes': 2, 'sha256': '0' * 64}]}))
    estimate_space_tempo(space, ['maestro'])
    artifacts = {a['path']: a for a in json.loads((folder / 'hashes.json').read_text())['artifacts']}
    data = (folder / 'metadata.json').read_bytes()
    assert artifacts['pid1/metadata.json'] == {'path': 'pid1/metadata.json', 'bytes': len(data),
                                               'sha256': hashlib.sha256(data).hexdigest()}
    assert artifacts['pid1/loop.mid']['sha256'] == '0' * 64


def test_tempo_refreshes_the_card_and_refuses_unknown_groups(tmp_path):
    space = make_space(tmp_path)
    (space / 'README.md').write_text('# Space\n\nBody.\n')
    with pytest.raises(ValueError):
        estimate_space_tempo(space, ['pdmx'])
    estimate_space_tempo(space, ['maestro'])
    text = (space / 'README.md').read_text()
    assert 'a pulse estimated from the onset intervals of each phrase' in text
    assert '- MAESTRO performances: 1 loops' in text
