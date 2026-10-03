from __future__ import annotations

import json
from pathlib import Path

import pytest

from samuged.experiment import verify_completed_experiment
from scripts.compare_builds import compare_builds, semantic_phrase


def _phrase(family: str, phrase_id: str, midi_path: str, midi_sha: str) -> dict:
    return {
        "kind": "melodic",
        "family_id": family,
        "phrase_id": phrase_id,
        "midi_path": midi_path,
        "midi_sha256": midi_sha,
        "part_index": 0,
        "start_tick": 0,
        "end_tick": 960,
        "note_count": 2,
        "pitches": [60, 62],
        "onsets_beats": [0.0, 1.0],
        "durations_beats": [0.5, 0.5],
        "velocities": [90, 91],
        "occurrence_count": 2,
        "raw_occurrence_count": 2,
        "occurrences": [
            {"start_tick": 0, "end_tick": 960, "similarity": 1.0, "transpose_semitones": 0},
            {"start_tick": 1920, "end_tick": 2880, "similarity": 1.0, "transpose_semitones": 0},
        ],
        "recurrence_score": 0.8,
        "score_components": {"support": 0.5},
        "rank_in_file": 1,
    }


def _record(source_id: str, phrase: dict | None, *, status: str = "ok", outcome: str = "matched") -> dict:
    row = {
        "source_id": source_id,
        "source_path": f"artist/{source_id}.mid",
        "source_sha256": source_id * 16,
        "source_bytes": 100,
        "artist_from_path": "artist",
        "artist_key": "artist",
        "title_from_path": source_id,
        "song_key": f"song-{source_id}",
        "status": status,
        "outcome": outcome,
        "elapsed_seconds": 0.1,
        "run_key": "build-key",
        "phrases": [phrase] if phrase else [],
    }
    if status == "ok":
        row.update({
            "musical_sha256": f"music-{source_id}",
            "ticks_per_beat": 480,
            "part_count": 1,
            "note_count": 10,
            "warnings": [],
            "search_limited": False,
            "part_stats": [{"comparisons": 4, "candidate_limit_reached": False}],
            "drum_stats": {"selected_count": 0},
        })
    else:
        row.update({"error": "bad key", "error_type": "KeySignatureError"})
    return row


def _write_build(path: Path, records: list[tuple[dict, str, str]]) -> None:
    path.mkdir()
    (path / "records").mkdir()
    sources = []
    phrases = []
    for record, split, group in records:
        source_id = record["source_id"]
        (path / "records" / f"{source_id}.json").write_text(
            json.dumps(record, sort_keys=True) + "\n", encoding="utf-8"
        )
        source = {**record, "split": split, "split_group": group}
        sources.append(source)
        for phrase in record["phrases"]:
            phrases.append({**phrase, "source_id": source_id, "split": split, "split_group": group})
    (path / "sources.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in sources), encoding="utf-8"
    )
    (path / "phrases.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in phrases), encoding="utf-8"
    )
    (path / "summary.json").write_text(json.dumps({"source_files": len(records)}) + "\n")
    (path / "build_config.json").write_text(json.dumps({"version": "fixture"}) + "\n")


def test_semantic_phrase_excludes_only_build_artifact_identifiers() -> None:
    first = _phrase("family", "old", "midi/old.mid", "a" * 64)
    second = _phrase("family", "new", "midi/new.mid", "a" * 64)
    first.update({"split": "train", "split_group": "old-group"})
    second.update({"split": "test", "split_group": "new-group"})

    assert semantic_phrase(first) == semantic_phrase(second)
    second["midi_sha256"] = "b" * 64
    assert semantic_phrase(first) != semantic_phrase(second)
    assert set(first) - set(semantic_phrase(first)) == {
        "phrase_id", "midi_path", "split", "split_group"
    }


def test_complete_comparison_tracks_recovery_semantics_and_splits(tmp_path: Path) -> None:
    stable_left = _record("a1", _phrase("stable", "old-a", "midi/old-a.mid", "1" * 64))
    stable_right = _record("a1", _phrase("stable", "new-a", "midi/new-a.mid", "1" * 64))
    stable_right["part_stats"][0].update({"comparisons": 2, "exact_cache_hits": 2})
    changed_left = _record("b2", _phrase("changed", "old-b", "midi/old-b.mid", "2" * 64))
    changed_right = _record("b2", _phrase("changed", "new-b", "midi/new-b.mid", "3" * 64))
    error = _record("c3", None, status="error", outcome="parse_error")
    recovered = _record("c3", _phrase("recovered", "new-c", "midi/new-c.mid", "4" * 64))
    recovered["metadata_repairs"] = [{"tick": 0, "original_payload_hex": "08ff"}]
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_build(left, [(stable_left, "train", "g1"), (changed_left, "test", "g2"), (error, "test", "g3")])
    _write_build(right, [(stable_right, "train", "g1"), (changed_right, "validation", "g2"), (recovered, "train", "g4")])

    output = tmp_path / "comparison"
    aggregate = compare_builds(left, right, output)

    assert aggregate["source_outcome_transitions"]["error:parse_error->ok:matched"] == 1
    assert aggregate["metadata_recovery"] == {
        "repaired_sources": 1,
        "repair_events": 1,
        "repaired_source_ids": ["c3"],
    }
    melodic = aggregate["semantic_phrase_changes"]["melodic"]
    assert melodic["changed_sources"] == 2
    assert melodic["changed_without_recovery"] == 1
    assert melodic["changed_without_recovery_and_without_baseline_search_limit"] == 1
    assert aggregate["split_changes"] == 2
    assert aggregate["split_group_changes"] == 1
    assert aggregate["nontelemetry_part_stat_changes"] == 1  # recovered source only
    assert aggregate["family_comparison"]["melodic"]["right_only_family_ids"] == ["recovered"]
    verify_completed_experiment(output)
    raw = json.loads((output / "raw_results.json").read_text())
    changed = {row["source_id"]: row for row in raw["changed_sources"]}
    assert "a1" not in changed
    assert changed["b2"]["cause_class"] == "cache_change_without_baseline_search_limit"
    assert changed["c3"]["cause_class"] == "invalid_key_metadata_recovery"
    assert "[0].midi_sha256" in changed["b2"]["kinds"]["melodic"]["difference_paths"]


def test_record_must_match_frozen_source_manifest(tmp_path: Path) -> None:
    record = _record("a1", _phrase("stable", "one", "midi/one.mid", "1" * 64))
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_build(left, [(record, "train", "g1")])
    _write_build(right, [(record, "train", "g1")])
    stored = json.loads((right / "records" / "a1.json").read_text())
    stored["note_count"] = 99
    (right / "records" / "a1.json").write_text(json.dumps(stored, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="record differs from frozen source manifest"):
        compare_builds(left, right, tmp_path / "comparison")


def test_record_filename_sets_must_match(tmp_path: Path) -> None:
    first = _record("a1", None, status="error", outcome="parse_error")
    second = _record("b2", None, status="error", outcome="parse_error")
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_build(left, [(first, "test", "g1")])
    _write_build(right, [(second, "test", "g2")])

    with pytest.raises(ValueError, match="record filename sets differ"):
        compare_builds(left, right, tmp_path / "comparison")
