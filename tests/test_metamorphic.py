from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import mido
import pytest

from samuged.dataset import file_digest
from samuged.experiment import verify_completed_experiment
from samuged.midi import MidiSong, Note, Part
from scripts import evaluate_metamorphic as study


def _song(*, high_pitch: bool = False) -> MidiSong:
    melody = [
        Note(0, 240, 123 if high_pitch else 60, 91),
        Note(480, 720, 64, 83),
    ]
    drums = [Note(0, 60, 36, 100), Note(0, 60, 42, 70), Note(480, 540, 38, 95)]
    return MidiSong(
        ticks_per_beat=480,
        parts=[
            Part(0, 0, 0, 5, "melody", False, melody),
            Part(1, 1, 9, 0, "drums", True, drums),
        ],
        tempos=[(0, 500_000), (960, 400_000)],
        meters=[(0, 4, 4), (1920, 3, 4)],
        warnings=["fixture"],
        metadata_repairs=[{"kind": "fixture"}],
    )


def _phrase(*, pitches: list[int], tick_factor: int = 1, family: str = "family") -> dict:
    return {
        "family_id": family,
        "kind": "melodic",
        "part_index": 0,
        "start_tick": 0,
        "end_tick": 960 * tick_factor,
        "note_count": len(pitches),
        "duration_beats": 2.0,
        "recurrence_score": 0.75,
        "score_components": {"support": 2, "similarity": 1.0},
        "occurrence_count": 2,
        "occurrences": [
            {
                "start_tick": 0,
                "end_tick": 960 * tick_factor,
                "similarity": 1.0,
                "transpose_semitones": 0,
            },
            {
                "start_tick": 1920 * tick_factor,
                "end_tick": 2880 * tick_factor,
                "similarity": 1.0,
                "transpose_semitones": 0,
            },
        ],
        "pitches": pitches,
        "onsets_beats": [0.0, 1.0],
        "durations_beats": [0.5, 0.5],
        "velocities": [90, 80],
    }


def _result(phrase: dict, *, drums: bool = False) -> dict:
    if drums:
        return {"phrases": [phrase], "stats": {"search_limited": False, "comparisons": 3}}
    return {"phrases": [phrase], "search_limited": False, "comparisons": 3}


def _write_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    tempo = mido.MidiTrack()
    melody = mido.MidiTrack()
    drums = mido.MidiTrack()
    midi.tracks.extend((tempo, melody, drums))
    tempo.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    tempo.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    melody.append(mido.Message("note_on", channel=0, note=60, velocity=90, time=0))
    melody.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=240))
    melody.append(mido.Message("note_on", channel=0, note=64, velocity=80, time=240))
    melody.append(mido.Message("note_off", channel=0, note=64, velocity=0, time=240))
    drums.append(mido.Message("note_on", channel=9, note=36, velocity=100, time=0))
    drums.append(mido.Message("note_off", channel=9, note=36, velocity=0, time=60))
    midi.save(path)


def test_transforms_change_only_the_declared_symbolic_dimensions() -> None:
    song = _song()

    tempo = study.tempo_changed(song)
    assert tempo.ticks_per_beat == song.ticks_per_beat
    assert tempo.parts == song.parts
    assert tempo.meters == song.meters
    assert [tick for tick, _ in tempo.tempos] == [tick for tick, _ in song.tempos]
    assert [value for _, value in tempo.tempos] != [value for _, value in song.tempos]

    scaled = study.ppq_doubled(song)
    assert scaled.ticks_per_beat == 960
    assert scaled.tempos == [(0, 500_000), (1920, 400_000)]
    assert scaled.meters == [(0, 4, 4), (3840, 3, 4)]
    assert [note.start for note in scaled.parts[0].notes] == [0, 960]
    assert [note.end for note in scaled.parts[0].notes] == [480, 1440]
    assert [note.pitch for note in scaled.parts[0].notes] == [60, 64]

    transposed = study.melodic_transposed_plus5(song)
    assert [note.pitch for note in transposed.parts[0].notes] == [65, 69]
    assert [note.pitch for note in transposed.parts[1].notes] == [36, 42, 38]
    assert [note.pitch for note in song.parts[0].notes] == [60, 64]
    assert transposed.tempos == song.tempos


def test_unsafe_transposition_fails_closed() -> None:
    song = _song(high_pitch=True)
    assert study.can_transpose_plus5(song) is False
    assert study.transform_song(song, "melodic_transpose_plus5") is None
    with pytest.raises(ValueError, match="exceed MIDI pitch 127"):
        study.melodic_transposed_plus5(song)


def test_comparison_normalizes_ticks_and_melodic_pitch_but_checks_rank_and_family() -> None:
    baseline = _result(_phrase(pitches=[60, 64]))
    ppq = _result(_phrase(pitches=[60, 64], tick_factor=2))
    transpose = _result(_phrase(pitches=[65, 69]))

    assert study.compare_result(baseline, ppq, "ppq_x2", "reference_approximate")["invariant"]
    assert study.compare_result(
        baseline, transpose, "melodic_transpose_plus5", "aligned_indexed"
    )["invariant"]

    changed_score = deepcopy(ppq)
    changed_score["phrases"][0]["recurrence_score"] = 0.7
    comparison = study.compare_result(baseline, changed_score, "ppq_x2", "reference_approximate")
    assert comparison["invariant"] is False
    assert "[0].recurrence_score" in comparison["difference_paths"]

    changed_family = deepcopy(ppq)
    changed_family["phrases"][0]["family_id"] = "different"
    comparison = study.compare_result(baseline, changed_family, "ppq_x2", "reference_approximate")
    assert comparison["musical_payload_equal"] is True
    assert comparison["family_id_order_equal"] is False
    assert comparison["invariant"] is False


def test_drum_pitch_ids_are_not_inverse_transposed() -> None:
    baseline = _result(_phrase(pitches=[36, 42]), drums=True)
    variant = deepcopy(baseline)
    assert study.compare_result(
        baseline, variant, "melodic_transpose_plus5", "drums_tolerant"
    )["invariant"]
    variant["phrases"][0]["pitches"][0] += 5
    assert not study.compare_result(
        baseline, variant, "melodic_transpose_plus5", "drums_tolerant"
    )["musical_payload_equal"]


def test_small_run_freezes_before_detection_and_completes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    midi_path = source / "one.mid"
    _write_midi(midi_path)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "source_id": "one",
                "source_path": "one.mid",
                "source_sha256": file_digest(midi_path),
                "status": "ok",
                "metadata_repairs": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "experiment"
    calls = []

    def melodic(song: MidiSong) -> dict:
        assert (output / "experiment_receipt.json").is_file()
        calls.append(("melodic", song.ticks_per_beat, song.parts[0].notes[0].pitch))
        tick_factor = song.ticks_per_beat // 480
        return _result(_phrase(pitches=[note.pitch for note in song.parts[0].notes], tick_factor=tick_factor))

    def drums(song: MidiSong) -> dict:
        assert (output / "experiment_receipt.json").is_file()
        calls.append(("drums", song.ticks_per_beat, song.parts[-1].notes[0].pitch))
        tick_factor = song.ticks_per_beat // 480
        return _result(_phrase(pitches=[song.parts[-1].notes[0].pitch], tick_factor=tick_factor), drums=True)

    aggregate = study.run(
        source,
        manifest,
        output,
        expected_sources=1,
        detector_functions={
            "reference_approximate": melodic,
            "aligned_indexed": melodic,
            "drums_tolerant": drums,
        },
    )

    assert len(calls) == 12
    assert aggregate["evaluated_rows"] == 9
    assert aggregate["total_failures"] == 0
    verify_completed_experiment(output)
    raw = json.loads((output / "raw_results.json").read_text())
    assert len(raw["rows"]) == 9
    assert all(row["comparison"]["invariant"] for row in raw["rows"])


def test_changed_source_is_rejected_before_freeze(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    midi_path = source / "one.mid"
    _write_midi(midi_path)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "source_id": "one",
                "source_path": "one.mid",
                "source_sha256": "0" * 64,
                "status": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "experiment"

    with pytest.raises(ValueError, match="unavailable or changed"):
        study.run(source, manifest, output, expected_sources=1)
    assert not output.exists()
