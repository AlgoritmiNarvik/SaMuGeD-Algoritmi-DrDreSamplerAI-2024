from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest

from samuged.dataset import file_digest
from samuged.evaluate import BenchmarkCase
from samuged.experiment import verify_completed_experiment
from samuged.midi import MidiSong, Note, Part
from scripts import compare_shortlist as study


def _phrase(family: str, start: int, end: int, *, part: int = 0, notes: int = 8) -> dict:
    return {
        "family_id": family,
        "part_index": part,
        "note_count": notes,
        "recurrence_score": 0.9,
        "occurrences": [
            {"start_tick": start, "end_tick": end},
            {"start_tick": start + 2000, "end_tick": end + 2000},
        ],
    }


def _result(phrases: list[dict], *, truncated: bool = False) -> dict:
    return {
        "phrases": phrases,
        "candidate_count": 80 if truncated else len(phrases),
        "raw_repeat_group_count": 82 if truncated else len(phrases),
        "curation_truncated": truncated,
        "search_limited": False,
        "part_stats": [
            {
                "candidate_limit_reached": truncated,
                "candidates_truncated": 2 if truncated else 0,
                "comparison_limit_reached": False,
                "group_limit_reached": False,
                "note_limit_reached": False,
                "window_limit_reached": False,
                "comparisons": 20,
                "windows_considered": 30,
                "saturated_seed_buckets": 0,
            }
        ],
    }


def _song() -> MidiSong:
    notes = [Note(i * 240, i * 240 + 120, 60 + i % 5, 90) for i in range(16)]
    return MidiSong(480, [Part(0, 0, 0, 0, "piano", False, notes)], [(0, 500000)], [(0, 4, 4)], [])


def _write_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=240))
    midi.save(path)


def test_diversity_distinguishes_nested_disjoint_and_other_part_families() -> None:
    base = _phrase("a", 0, 800)
    nested = _phrase("b", 100, 700)
    disjoint = _phrase("c", 900, 1500)
    other_part = _phrase("d", 100, 700, part=1)

    nested_summary = study.diversity_summary([base, nested])
    disjoint_summary = study.diversity_summary([base, disjoint, other_part])

    assert nested_summary["overlapping_family_pairs"] == 1
    assert nested_summary["maximum_pair_overlap_coverage"] == 1.0
    assert disjoint_summary["overlapping_family_pairs"] == 0
    assert disjoint_summary["same_part_family_pairs"] == 1
    assert disjoint_summary["unique_part_count"] == 2


def test_output_comparison_separates_telemetry_from_selected_output() -> None:
    phrase = _phrase("same", 0, 800)
    low = _result([phrase], truncated=True)
    high = _result([phrase], truncated=False)

    comparison = study.compare_outputs(low, high)

    assert comparison["phrases_equal"] is True
    assert comparison["top1_equal"] is True
    assert study._telemetry(low)["parts_at_candidate_cap"] == 1
    assert study._telemetry(high)["parts_at_candidate_cap"] == 0


def test_changed_selection_reports_rank_and_family_change() -> None:
    first = _phrase("first", 0, 800)
    replacement = _phrase("replacement", 400, 1200)

    comparison = study.compare_outputs(_result([first]), _result([replacement]))

    assert comparison["phrases_equal"] is False
    assert comparison["top1_equal"] is False
    assert comparison["low_only_family_ids"] == ["first"]
    assert comparison["high_only_family_ids"] == ["replacement"]


def test_small_run_freezes_before_detection_and_completes_receipt(tmp_path, monkeypatch) -> None:
    case = BenchmarkCase(
        case_id="dev-one",
        split="development",
        kind="exact",
        rng_seed=1,
        song=_song(),
        truth_intervals=[(0, 800), (2000, 2800)],
        prototype=_song().parts[0].notes[:8],
        positive=True,
    )
    monkeypatch.setattr(study, "generate_cases", lambda count: [case])

    source = tmp_path / "source"
    source.mkdir()
    midi_path = source / "one.mid"
    _write_midi(midi_path)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(json.dumps({
        "source_path": "one.mid",
        "source_sha256": file_digest(midi_path),
        "status": "ok",
    }) + "\n")
    output = tmp_path / "experiment"
    calls = []

    def detector(song, config):
        assert (output / "experiment_receipt.json").is_file()
        assert not (output / "raw_results.json").exists()
        calls.append(config.max_candidates)
        return _result([_phrase("truth", 0, 800)], truncated=config.max_candidates == 80)

    result = study.run(
        source,
        manifest,
        output,
        case_count=2,
        expected_real_sources=1,
        detectors={"reference_approximate": detector, "aligned_indexed": detector},
    )

    assert calls.count(80) == calls.count(400) == 4
    assert result["groups"]["reference_approximate"]["development"]["changed_phrase_outputs"] == 0
    assert result["groups"]["reference_approximate"]["development"]["variants"]["80"]["curation_truncated_cases"] == 1
    verify_completed_experiment(output)
    raw = json.loads((output / "raw_results.json").read_text())
    assert len(raw["rows"]) == 4
    assert {tuple(row["execution_order"]) for row in raw["rows"]} == {(80, 400), (400, 80)}


def test_run_rejects_changed_real_source_before_freezing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(study, "generate_cases", lambda count: [])
    source = tmp_path / "source"
    source.mkdir()
    midi_path = source / "one.mid"
    _write_midi(midi_path)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(json.dumps({
        "source_path": "one.mid",
        "source_sha256": "0" * 64,
        "status": "ok",
    }) + "\n")
    output = tmp_path / "experiment"

    with pytest.raises(ValueError, match="pilot source changed"):
        study.run(source, manifest, output, case_count=2, expected_real_sources=1)

    assert not output.exists()
