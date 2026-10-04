from samuged.midi import MidiSong
from scripts.prepare_space_revision import time_at
from scripts.rerender_loop_space import update_waveforms


def test_note_clock_integrates_tempo_changes_and_tick_zero():
    song = MidiSong(ticks_per_beat=480, parts=[],
                    tempos=[(0, 500_000), (480, 1_000_000)],
                    meters=[(0, 4, 4)], warnings=[])
    assert time_at(song, 0) == 0
    assert time_at(song, 480) == 0.5
    assert time_at(song, 960) == 1.5


def test_audio_revision_updates_nested_layers_by_identity():
    row = {'phrase_id': 'melody', 'waveform': [1],
           'with_drums': {'phrase_id': 'paired', 'waveform': [2]},
           'drums_only': {'phrase_id': 'drums', 'waveform': [3]}}
    catalog = {'groups': {'popular': {'rows': [row]}}}
    update_waveforms(catalog, {'melody': [4], 'paired': [5], 'drums': [6]})
    assert row['waveform'] == [4]
    assert row['with_drums']['waveform'] == [5]
    assert row['drums_only']['waveform'] == [6]
