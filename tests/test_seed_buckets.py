from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest

from samuged.dataset import file_digest
from samuged.evaluate import BenchmarkCase
from samuged.experiment import verify_completed_experiment
from samuged.midi import MidiSong, Note, Part
from scripts import compare_seed_buckets as study


def _phrase(family: str, part: int, start: int) -> dict:
    return {
        "family_id": family,
        "part_index": part,
        "start_tick": start,
        "end_tick": start + 800,
        "note_count": 8,
        "recurrence_score": 0.9,
        "occurrence_count": 2,
        "occurrences": [
            {"start_tick": start, "end_tick": start + 800, "note_index": 0, "note_count": 8},
            {"start_tick": start + 2000, "end_tick": start + 2800, "note_index": 8, "note_count": 8},
        ],
    }


def _result(phrases: list[dict], cap: int) -> dict:
    saturated = int(cap == 192)
    return {
        "phrases": phrases,
        "candidate_count": len(phrases),
        "raw_repeat_group_count": len(phrases),
        "search_limited": bool(saturated),
        "curation_truncated": False,
        "part_stats": [
            {
                "windows_considered": 20,
                "windows": 10,
                "comparisons": 2,
                "proposed_pairs": 5,
                "dp_calls": 2,
                "groups": 4,
                "repeat_groups": len(phrases),
                "seed_index_keys": 3,
                "seed_index_postings": cap,
                "posting_entries_visited": cap + 2,
                "saturated_seed_buckets": saturated,
                "saturated_seed_postings_dropped": 7 * saturated,
                "saturated_seed_key_types": {"interval": saturated} if saturated else {},
                "max_seed_bucket_size": cap,
                "candidates_truncated": 0,
                "note_limit_reached": False,
                "window_limit_reached": False,
                "comparison_limit_reached": False,
                "group_limit_reached": False,
            }
        ],
    }


def _song() -> MidiSong:
    notes = [Note(index * 240, index * 240 + 120, 60 + index % 5, 90) for index in range(16)]
    return MidiSong(480, [Part(0, 0, 0, 0, "", False, notes)], [(0, 500000)], [(0, 4, 4)], [])


def _write_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=240))
    midi.save(path)


def _manifest_row(path: Path, source_path: str, *, limited: bool) -> dict:
    sat = 2 if limited else 0
    return {
        "source_path": source_path,
        "source_sha256": file_digest(path),
        "source_bytes": path.stat().st_size,
        "status": "ok",
        "search_limited": limited,
        "part_stats": [
            {
                "saturated_seed_buckets": sat,
                "saturated_seed_postings_dropped": sat * 3,
                "note_limit_reached": False,
                "window_limit_reached": False,
                "comparison_limit_reached": False,
                "group_limit_reached": False,
            }
        ],
    }


def test_configs_change_only_the_seed_bucket_cap() -> None:
    variants = study.configs()
    assert variants[192].max_bucket == 192
    assert variants[768].max_bucket == 768
    left = vars(variants[192])
    right = vars(variants[768])
    assert [key for key in left if left[key] != right[key]] == ["max_bucket"]
    assert variants[192].max_candidates == variants[768].max_candidates == 80
    assert variants[192].max_comparisons == variants[768].max_comparisons == 2000


def test_real_cohort_requires_seed_saturation_only_and_hash_selects_controls(tmp_path) -> None:
    paths = []
    rows = []
    for index, limited in enumerate((True, True, False, False, False)):
        path = tmp_path / f"{index}.mid"
        _write_midi(path)
        paths.append(path)
        rows.append(_manifest_row(path, path.name, limited=limited))
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    cohort, cause = study.select_real_cohort(manifest, limited_count=2, control_count=2)
    assert sum(row["cohort"] == "fixed_real_limited" for row in cohort) == 2
    controls = [row for row in cohort if row["cohort"] == "fixed_real_control"]
    expected = sorted(rows[2:], key=lambda row: (study._hash_rank(row["source_path"]), row["source_path"]))[:2]
    assert [row["source_path"] for row in controls] == [row["source_path"] for row in expected]
    assert cause["limited_rows_with_other_limit_flags"] == 0
    rows[0]["part_stats"][0]["comparison_limit_reached"] = True
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="not seed saturation only"):
        study.select_real_cohort(manifest, limited_count=2, control_count=2)


def test_output_comparison_reports_set_rank_and_top1_changes() -> None:
    first = _phrase("a", 0, 0)
    second = _phrase("b", 1, 100)
    third = _phrase("c", 2, 200)
    low = _result([first, second], 192)
    high = _result([second, third], 768)
    comparison = study.compare_outputs(low, high)
    assert comparison["top1_equal"] is False
    assert comparison["semantic_set_equal"] is False
    assert comparison["shared_rank_changes"][0]["baseline_rank"] == 2
    assert comparison["shared_rank_changes"][0]["wide_rank"] == 1
    assert comparison["baseline_only"][0]["family_id"] == "a"
    assert comparison["wide_only"][0]["family_id"] == "c"


def test_telemetry_keeps_seed_saturation_separate_from_other_caps() -> None:
    row = study.telemetry(_result([_phrase("a", 0, 0)], 192))
    assert row["saturated_seed_buckets"] == 1
    assert row["saturated_seed_postings_dropped"] == 7
    assert row["comparisons"] == 2
    assert row["limit_part_counts"]["comparison_limit_reached"] == 0


def test_small_run_freezes_before_detection_and_completes(tmp_path, monkeypatch) -> None:
    case = BenchmarkCase(
        case_id="development-0000-exact",
        split="development",
        kind="exact",
        rng_seed=10_000_000,
        song=_song(),
        truth_intervals=[(0, 800), (2000, 2800)],
        prototype=_song().parts[0].notes[:8],
        positive=True,
    )
    monkeypatch.setattr(study, "development_cases", lambda count: [case])
    monkeypatch.setattr(study, "PILOT_LIMITED_CASES", 1)
    monkeypatch.setattr(study, "PILOT_CONTROL_CASES", 1)
    monkeypatch.setattr(study, "PILOT_SYNTHETIC_CASES", 1)
    monkeypatch.setattr(study, "FALLBACK_LIMITED_CASES", 1)
    monkeypatch.setattr(study, "FALLBACK_CONTROL_CASES", 1)

    source = tmp_path / "source"
    source.mkdir()
    rows = []
    for name, limited in (("limited.mid", True), ("control.mid", False)):
        path = source / name
        _write_midi(path)
        rows.append(_manifest_row(path, name, limited=limited))
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "experiment"
    calls = []

    def detector(song, config):
        assert (output / "experiment_receipt.json").is_file()
        calls.append(config.max_bucket)
        return _result([_phrase("truth", 0, 0)], config.max_bucket)

    aggregate = study.run(
        source,
        manifest,
        output,
        synthetic_count=1,
        limited_count=1,
        control_count=1,
        detector=detector,
    )
    assert calls.count(192) == calls.count(768) == 6
    assert aggregate["groups"]["development"]["cases"] == 1
    assert aggregate["groups"]["fixed_real_limited"]["cases"] == 1
    assert aggregate["groups"]["fixed_real_control"]["cases"] == 1
    verify_completed_experiment(output)
    receipt = json.loads((output / "experiment_receipt.json").read_text())
    assert receipt["design"]["synthetic_scope"].endswith("no test cases")


def test_changed_source_is_rejected_before_receipt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(study, "development_cases", lambda count: [])
    source = tmp_path / "source"
    source.mkdir()
    path = source / "limited.mid"
    _write_midi(path)
    row = _manifest_row(path, path.name, limited=True)
    row["source_sha256"] = "0" * 64
    control = source / "control.mid"
    _write_midi(control)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(json.dumps(row) + "\n" + json.dumps(_manifest_row(control, control.name, limited=False)) + "\n")
    output = tmp_path / "experiment"
    with pytest.raises(ValueError, match="pilot source changed"):
        study.run(source, manifest, output, synthetic_count=0, limited_count=1, control_count=1)
    assert not output.exists()
