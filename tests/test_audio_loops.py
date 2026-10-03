from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version as package_version
import json
from pathlib import Path
import wave

import mido
import numpy as np
import pytest

from samuged.audio_loops import (
    SAMPLE_RATE,
    VERSION,
    _renderer_provenance,
    active_meter,
    infer_loop_period,
    load_phrase_ids,
    process_steady_cycle,
    seconds_between,
    source_cycle_notes,
    write_pcm24_wave,
    write_repeated_midi,
)
from samuged.midi import MidiSong, Note, Part, export_phrase


def _song() -> tuple[MidiSong, Part]:
    part = Part(
        index=0,
        track=1,
        channel=2,
        program=29,
        name="source guitar",
        is_drum=False,
        notes=[
            Note(100, 220, 60, 80),
            Note(400, 650, 64, 90),
            Note(560, 900, 67, 70),
            Note(580, 620, 69, 60),
        ],
    )
    return (
        MidiSong(
            ticks_per_beat=100,
            parts=[part],
            tempos=[(0, 500_000), (300, 1_000_000), (550, 250_000)],
            meters=[(0, 4, 4), (500, 3, 4)],
            warnings=[],
        ),
        part,
    )


def _row(*, duration: int, starts: list[int], ppq: int = 240) -> dict:
    return {
        "phrase_id": "test",
        "ticks_per_beat": ppq,
        "start_tick": starts[0],
        "end_tick": starts[0] + duration,
        "occurrences": [
            {"start_tick": start, "end_tick": start + duration} for start in starts
        ],
    }


def _absolute(track: mido.MidiTrack):
    tick = 0
    result = []
    for message in track:
        tick += message.time
        result.append((tick, message))
    return result


def test_recurrence_period_prefers_frequent_nonoverlapping_grid() -> None:
    thunder = infer_loop_period(
        _row(duration=1437, starts=[25921, 27841, 29761, 31680, 33601])
    )
    exodus = infer_loop_period(
        _row(duration=732, starts=[771, 1539, 2307, 3075], ppq=96)
    )

    assert thunder.period_ticks == 1920
    assert thunder.period_beats == 8
    assert thunder.policy == "frequent_nonoverlapping_occurrence_start_difference"
    assert thunder.supporting_difference_count == 4
    assert exodus.period_ticks == 768
    assert exodus.period_beats == 8


def test_period_fallback_pads_to_whole_beat_without_claiming_evidence() -> None:
    decision = infer_loop_period(_row(duration=595, starts=[100], ppq=100))

    assert decision.period_ticks == 600
    assert decision.period_beats == 6
    assert decision.padding_ticks == 5
    assert decision.policy == "fallback_pad_phrase_to_whole_beat_without_meter"
    assert decision.supporting_difference_count == 0
    assert decision.fallback_meter_numerator is None
    assert "not measured recurrence evidence" in decision.fallback_assumption


@pytest.mark.parametrize(
    ("meter", "duration", "expected_ticks", "expected_beats"),
    (
        ((4, 4), 1_300, 1_600, 16),
        ((3, 4), 610, 900, 9),
        ((6, 8), 610, 900, 9),
    ),
)
def test_meter_aware_fallback_pads_to_complete_bars(
    meter: tuple[int, int],
    duration: int,
    expected_ticks: int,
    expected_beats: int,
) -> None:
    decision = infer_loop_period(
        _row(duration=duration, starts=[100], ppq=100), meter=meter
    )

    assert decision.period_ticks == expected_ticks
    assert decision.period_beats == expected_beats
    assert decision.policy == "fallback_pad_phrase_to_whole_bars_at_start_meter"
    assert decision.fallback_meter_numerator == meter[0]
    assert decision.fallback_meter_denominator == meter[1]
    assert decision.fallback_bar_ticks == (300 if meter != (4, 4) else 400)
    assert "not measured recurrence evidence" in decision.fallback_assumption


def test_fallback_uses_meter_at_phrase_start_across_later_meter_change() -> None:
    song = MidiSong(
        ticks_per_beat=100,
        parts=[],
        tempos=[(0, 500_000)],
        meters=[(0, 3, 4), (700, 4, 4)],
        warnings=[],
    )
    row = _row(duration=610, starts=[100], ppq=100)

    meter = active_meter(song, row["start_tick"])
    decision = infer_loop_period(row, meter=meter)

    assert meter == (3, 4)
    assert row["start_tick"] + decision.period_ticks > 700
    assert decision.period_beats == 9
    assert "later meter changes inside the cycle do not change" in (
        decision.fallback_assumption
    )


def test_supported_recurrence_period_overrides_bar_fallback() -> None:
    iris = infer_loop_period(
        _row(duration=595, starts=[100, 700, 1300], ppq=100), meter=(4, 4)
    )
    take_five = infer_loop_period(
        _row(duration=1450, starts=[0, 1500, 3000], ppq=100), meter=(5, 4)
    )

    assert iris.period_beats == 6
    assert take_five.period_beats == 15
    assert iris.policy == "frequent_nonoverlapping_occurrence_start_difference"
    assert take_five.policy == "frequent_nonoverlapping_occurrence_start_difference"
    assert iris.fallback_assumption is None
    assert take_five.fallback_assumption is None


def test_bar_fallback_includes_source_notes_from_the_added_bar_space() -> None:
    part = Part(
        index=0,
        track=0,
        channel=0,
        program=0,
        name="lead",
        is_drum=False,
        notes=[Note(100, 200, 60, 80), Note(750, 850, 67, 90)],
    )
    row = _row(duration=595, starts=[100], ppq=100)
    period = infer_loop_period(row, meter=(4, 4))

    assert period.period_ticks == 800
    assert source_cycle_notes(part, 100, period.period_ticks) == part.notes


def test_tempo_integration_uses_each_source_segment() -> None:
    song, _part = _song()

    # 200 ticks at 120 BPM, 250 at 60 BPM, then 50 at 240 BPM.
    assert seconds_between(song, 100, 600) == pytest.approx(1.0 + 2.5 + 0.125)


def test_loop_midi_preserves_source_notes_and_exact_end_of_track(tmp_path: Path) -> None:
    song, part = _song()
    notes = source_cycle_notes(part, 100, 500)
    destination = tmp_path / "loop.mid"

    export_phrase(song, part, notes, 100, 600, destination)
    midi = mido.MidiFile(destination, clip=False)
    note_messages = [
        (tick, message.type, message.note, getattr(message, "velocity", None))
        for tick, message in _absolute(midi.tracks[1])
        if message.type in {"note_on", "note_off"}
    ]

    assert notes == [
        Note(100, 220, 60, 80),
        Note(400, 600, 64, 90),
        Note(560, 600, 67, 70),
        Note(580, 600, 69, 60),
    ]
    assert note_messages == [
        (0, "note_on", 60, 80),
        (120, "note_off", 60, 0),
        (300, "note_on", 64, 90),
        (460, "note_on", 67, 70),
        (480, "note_on", 69, 60),
        (500, "note_off", 64, 0),
        (500, "note_off", 67, 0),
        (500, "note_off", 69, 0),
    ]
    assert all(_absolute(track)[-1][0] == 500 for track in midi.tracks)
    assert all(_absolute(track)[-1][1].type == "end_of_track" for track in midi.tracks)


def test_repeated_midi_repeats_notes_tempo_meter_and_end_tick(tmp_path: Path) -> None:
    song, part = _song()
    notes = source_cycle_notes(part, 100, 500)
    destination = tmp_path / "repeated.mid"

    write_repeated_midi(song, part, notes, 100, 500, 3, destination)
    midi = mido.MidiFile(destination, clip=False)
    note_ons = [
        (tick, message.note, message.velocity)
        for tick, message in _absolute(midi.tracks[1])
        if message.type == "note_on" and message.velocity
    ]
    tempos = [
        (tick, message.tempo)
        for tick, message in _absolute(midi.tracks[0])
        if message.type == "set_tempo"
    ]
    meters = [
        (tick, message.numerator, message.denominator)
        for tick, message in _absolute(midi.tracks[0])
        if message.type == "time_signature"
    ]

    assert note_ons == [
        (0, 60, 80), (300, 64, 90), (460, 67, 70), (480, 69, 60),
        (500, 60, 80), (800, 64, 90), (960, 67, 70), (980, 69, 60),
        (1000, 60, 80), (1300, 64, 90), (1460, 67, 70), (1480, 69, 60),
    ]
    assert tempos == [
        (0, 500_000), (200, 1_000_000), (450, 250_000),
        (500, 500_000), (700, 1_000_000), (950, 250_000),
        (1000, 500_000), (1200, 1_000_000), (1450, 250_000),
    ]
    assert meters == [
        (0, 4, 4), (400, 3, 4),
        (500, 4, 4), (900, 3, 4),
        (1000, 4, 4), (1400, 3, 4),
    ]
    assert all(_absolute(track)[-1][0] == 1500 for track in midi.tracks)


def test_audio_cycle_has_exact_frames_pcm24_and_no_clipping(tmp_path: Path) -> None:
    cycle_seconds = 0.1
    cycle_frames = round(cycle_seconds * SAMPLE_RATE)
    time = np.arange(cycle_frames * 5) / SAMPLE_RATE
    rendered = np.column_stack(
        (0.25 * np.sin(2 * np.pi * 220 * time), 0.2 * np.sin(2 * np.pi * 330 * time))
    )
    # Force a seam large enough to exercise the documented periodic correction.
    rendered[2 * cycle_frames, :] = 0.4
    rendered[3 * cycle_frames - 1, :] = -0.4

    loop, details = process_steady_cycle(
        rendered, SAMPLE_RATE, cycle_seconds, steady_repetition=2
    )
    destination = tmp_path / "loop.wav"
    write_pcm24_wave(destination, loop)

    with wave.open(str(destination), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 3
        assert handle.getnframes() == cycle_frames
    assert loop.shape == (cycle_frames, 2)
    assert np.max(np.abs(loop)) < 1.0
    assert details["clipped_sample_count"] == 0
    assert details["edge_conditioning_applied"] is True
    assert details["edge_discontinuity_after"] < details["edge_discontinuity_before"]


def test_phrase_id_json_accepts_ordered_list_or_candidate_objects(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text(json.dumps(["b", "a"]))
    assert load_phrase_ids(path) == ["b", "a"]

    path.write_text(json.dumps({"candidates": [{"phrase_id": "x"}, "y"]}))
    assert load_phrase_ids(path) == ["x", "y"]


def test_v2_renderer_provenance_binds_code_dependencies_and_tool_versions(
    tmp_path: Path,
) -> None:
    fluidsynth = tmp_path / "fluidsynth"
    ffmpeg = tmp_path / "ffmpeg"
    fluidsynth.write_text("#!/bin/sh\nprintf 'FluidSynth runtime version test-2.5.6\\n'\n")
    ffmpeg.write_text("#!/bin/sh\nprintf 'ffmpeg version test-8.0.1\\n'\n")
    fluidsynth.chmod(0o755)
    ffmpeg.chmod(0o755)

    provenance = _renderer_provenance(fluidsynth, ffmpeg)
    package_root = Path(__file__).parents[1] / "samuged"

    assert VERSION == "source-audio-loops-v2"
    assert provenance["code"] == {
        "samuged/audio_loops.py": sha256(
            (package_root / "audio_loops.py").read_bytes()
        ).hexdigest(),
        "samuged/midi.py": sha256((package_root / "midi.py").read_bytes()).hexdigest(),
    }
    assert provenance["python_dependencies"] == {
        "numpy": package_version("numpy"),
        "mido": package_version("mido"),
    }
    assert provenance["tools"] == {
        "fluidsynth": {
            "path": str(fluidsynth),
            "version": "FluidSynth runtime version test-2.5.6",
        },
        "ffmpeg": {
            "path": str(ffmpeg),
            "version": "ffmpeg version test-8.0.1",
        },
    }
