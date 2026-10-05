import pytest
from samuged.midi import MidiSong, Part
from scripts.build_player_notes import occurrence_windows


def song(drums=False):
    return MidiSong(ticks_per_beat=100, tempos=[(0, 500000), (100, 1000000)],
                    meters=[(0, 4, 4)], warnings=[],
                    parts=[Part(index=2, track=1, channel=9 if drums else 0,
                                program=0, name='test', is_drum=drums, notes=[])])


def test_occurrences_use_tempo_map_and_deduplicate():
    record = {'source_sha256': 'a', 'part_index': 2, 'occurrences': [
        {'start_tick': 100, 'end_tick': 200},
        {'start_tick': 0, 'end_tick': 100},
        {'start_tick': 100, 'end_tick': 200},
        {'start_tick': 200, 'end_tick': 300, 'source_verified': False}]}
    meta = {'source_sha256': 'a', 'part': {'index': 2}}
    assert occurrence_windows(record, song(), meta) == [[0, .5], [.5, 1.5]]
    assert occurrence_windows(record, song(), {**meta, 'source_sha256': 'b'}) == []
    assert occurrence_windows(record, song(), {**meta, 'part': {'index': 3}}) == []


def test_merged_percussion_requires_same_source_parts():
    record = {'source_sha256': 'a', 'part_index': -1, 'kind': 'percussion',
              'source_part_indices': [2], 'occurrence_ticks': [{'start': 0, 'end': 100}]}
    meta = {'source_sha256': 'a', 'part': {'index': 0, 'is_drum': True, 'percussion_merge': True}}
    assert occurrence_windows(record, song(True), meta) == [[0, .5]]
    assert occurrence_windows({**record, 'source_part_indices': [3]}, song(True), meta) == []


def test_invalid_saved_window_is_rejected():
    with pytest.raises(ValueError):
        occurrence_windows({'source_sha256': 'a', 'occurrences': [{'start': 100, 'end': 0}]},
                           song(), {'source_sha256': 'a', 'part': {'index': 2}})
