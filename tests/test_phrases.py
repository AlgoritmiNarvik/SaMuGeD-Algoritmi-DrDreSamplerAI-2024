from dataclasses import asdict, replace
import random

import pytest

from samuged.midi import MidiSong, Note, Part
from samuged.phrases import Config, extract, skyline


def make_song(repeats=3, transpose=0, jitter=0, altered=False, rhythm_change=False, ppq=480):
    pitches = [60, 62, 65, 64, 67, 65, 62, 60, 64, 65, 69, 67]
    notes = []
    for rep in range(repeats):
        for i, pitch in enumerate(pitches):
            start = round((rep*12 + i*.5)*ppq)
            if rep and i:
                start += round(jitter * ppq * (-1 if i%2 else 1))
            if rhythm_change and rep:
                start += round(i*.25*ppq)
            notes.append(Note(start, start+round(.4*ppq), pitch+rep*transpose+(1 if altered and rep and i==5 else 0), 90))
    part = Part(0, 1, 0, 0, "melody", False, notes)
    return MidiSong(ppq, [part], [(0, 500000)], [(0, 4, 4)], [])


def target(result, length=12):
    return next((x for x in result["phrases"] if x["note_count"] == length), None)


def test_recovers_nonadjacent_repetitions():
    result = extract(make_song(), Config(lengths=(12,)))
    phrase = target(result)
    assert phrase is not None
    assert phrase["occurrence_count"] == 3
    assert [o["start_tick"] for o in phrase["occurrences"]] == [0, 5760, 11520]


def test_transposition_ablation_and_tick_resolution():
    cfg = Config(lengths=(12,), mode="transposed")
    a = target(extract(make_song(transpose=3), cfg))
    b = target(extract(make_song(transpose=3, ppq=960), cfg))
    assert a is not None and b is not None
    assert a["family_id"] == b["family_id"]
    assert [x["transpose_semitones"] for x in a["occurrences"]] == [0, 3, 6]
    assert not extract(make_song(repeats=2, transpose=3), replace(cfg, mode="exact"))["phrases"]


def test_timing_and_pitch_variation_recovered():
    song = make_song(repeats=2, transpose=5, jitter=.04, altered=True)
    cfg = Config(lengths=(12,))
    phrase = target(extract(song, cfg))
    assert phrase is not None and phrase["occurrence_count"] == 2
    assert not extract(song, replace(cfg, mode="transposed"))["phrases"]


def test_different_rhythm_is_not_a_repeat():
    song = make_song(repeats=2, rhythm_change=True)
    assert not extract(song, Config(lengths=(12,)))["phrases"]


def test_single_phrase_and_overlapping_rotations_do_not_count_as_repeats():
    song = make_song(repeats=1)
    assert not extract(song, Config(lengths=(12,)))["phrases"]
    notes = [Note(i*240, i*240+240, 60+i%3, 100) for i in range(16)]
    song.parts[0].notes = notes
    assert not extract(song, Config(lengths=(12,)))["phrases"]


def test_drum_exclusion_does_not_stop_later_melody():
    song = make_song()
    song.parts.insert(0, Part(7, 0, 9, 0, "drums", True, song.parts[0].notes))
    song.parts.insert(1, Part(8, 1, 0, 0, "empty", False, []))
    result = extract(song, Config(lengths=(12,)))
    assert target(result)["part_index"] == 0


def test_skyline_order_invariance_and_no_mutation():
    song = make_song()
    part = song.parts[0]
    part.notes += [Note(n.start, n.end, n.pitch-12, n.velocity) for n in part.notes[:]]
    before = asdict(song)
    a = extract(song, Config(lengths=(12,)))
    assert asdict(song) == before
    random.Random(42).shuffle(part.notes)
    b = extract(song, Config(lengths=(12,)))
    assert a == b
    assert len(skyline(part, 480)) == 36


def test_empty_and_constant_note_tracks():
    song = make_song()
    song.parts[0].notes = []
    assert not extract(song)["phrases"]
    song.parts[0].notes = [Note(i*480, i*480+400, 60, 80) for i in range(48)]
    assert not extract(song)["phrases"]


def test_resource_limits_are_visible():
    result = extract(make_song(), Config(max_stream_notes=10))
    assert result["search_limited"]
    assert result["part_stats"][0]["note_limit_reached"]
    assert not result["phrases"]


def test_bad_config_fails_before_work():
    for values in ({"mode":"oops"}, {"lengths":(0,)}, {"min_beats":50},
                   {"top_k":0}, {"timing_tolerance":float("nan")}, {"pitch_error_fraction":.5}):
        with pytest.raises(ValueError):
            Config(**values)


def test_exact_mode_keeps_transposed_families_separate():
    song=make_song(repeats=2)
    notes=[Note(n.start,n.end,n.pitch+5,n.velocity) for n in song.parts[0].notes]
    song.parts.append(Part(1,2,1,0,'second',False,notes))
    phrases=extract(song,Config(lengths=(12,),mode='exact'))['phrases']
    assert len(phrases)==2
    assert len({p['family_id'] for p in phrases})==2


def test_window_resource_cap_visible_in_strict_mode():
    result=extract(make_song(),Config(mode='exact',max_windows=2))
    assert result['search_limited']
    assert result['part_stats'][0]['windows_considered']==2
    assert result['part_stats'][0]['window_limit_reached']


def test_disjoint_pitch_seeds_survive_allowed_mutations():
    from samuged.phrases import window,match,_seeds
    pitches=[60,62,65,64,67,65,62,60,64,65,69,67]*2
    a=[Note(i*240,i*240+180,p,90) for i,p in enumerate(pitches)]
    b=[Note(n.start+10000,n.end+10000,n.pitch+(1 if i in (1,11,21) else 0),90) for i,n in enumerate(a)]
    left,right=window(a,0,24,480),window(b,0,24,480)
    assert match(left,right,Config()) is not None
    assert set(_seeds(left)) & set(_seeds(right))
