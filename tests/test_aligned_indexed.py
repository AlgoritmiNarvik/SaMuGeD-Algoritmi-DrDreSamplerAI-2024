import pytest

from samuged.aligned import AlignedConfig, extract_aligned
from samuged.aligned_indexed import extract_indexed
from samuged.midi import MidiSong, Note, Part


PPQ = 480
PITCHES = [60, 62, 65, 64, 67, 65, 62, 60]
ONSETS = [0.0, 0.75, 1.5, 2.25, 3.0, 3.75, 4.5, 5.25]


def pattern(start, pitches=PITCHES, onsets=ONSETS):
    return [
        Note(round((start + onset) * PPQ), round((start + onset + 0.4) * PPQ), pitch, 90)
        for pitch, onset in zip(pitches, onsets)
    ]


def song_with(second_pitches=PITCHES, second_onsets=ONSETS):
    notes = pattern(4.0) + pattern(16.0, second_pitches, second_onsets)
    notes.sort(key=lambda note: (note.start, note.pitch))
    return MidiSong(
        PPQ,
        [Part(0, 1, 0, 0, "melody", False, notes)],
        [(0, 500000)],
        [(0, 4, 4)],
        [],
    )


def assert_same_phrases(song, cfg=None):
    cfg = cfg or AlignedConfig(top_k=10)
    frozen = extract_aligned(song, cfg)
    indexed = extract_indexed(song, cfg)
    assert indexed["phrases"] == frozen["phrases"]
    return indexed


def test_exact_fast_path_preserves_output_and_bypasses_seed_work():
    result = assert_same_phrases(song_with())
    stats = result["part_stats"][0]
    assert stats["exact_fast_path_hits"] > 0
    assert stats["seed_keys_bypassed"] == stats["exact_fast_path_hits"]
    assert stats["seed_key_calls"] < stats["windows"]
    assert stats["exact_key_cache_hits"] > 0


@pytest.mark.parametrize("edit", ["insert", "delete"])
def test_internal_edit_alignment_is_unchanged(edit):
    pitches, onsets = list(PITCHES), list(ONSETS)
    if edit == "insert":
        pitches.insert(4, 66)
        onsets.insert(4, 2.7)
    else:
        del pitches[4]
        del onsets[4]
    assert_same_phrases(song_with(pitches, onsets))


def test_hard_negative_and_bucket_limit_semantics_are_unchanged():
    scaled = [onset * 1.45 for onset in ONSETS]
    assert_same_phrases(song_with(PITCHES, scaled))
    cfg = AlignedConfig(top_k=10, max_bucket=1)
    frozen = extract_aligned(song_with(), cfg)
    indexed = extract_indexed(song_with(), cfg)
    assert indexed["phrases"] == frozen["phrases"]
    assert indexed["search_limited"] == frozen["search_limited"]
    assert indexed["part_stats"][0]["saturated_seed_buckets"] == frozen["part_stats"][0]["saturated_seed_buckets"]
    stats = indexed["part_stats"][0]
    assert sum(stats["saturated_seed_key_types"].values()) == stats["saturated_seed_buckets"]
    assert stats["max_seed_bucket_size"] <= cfg.max_bucket
    assert stats["saturated_seed_postings_dropped"] >= stats["saturated_seed_buckets"]
