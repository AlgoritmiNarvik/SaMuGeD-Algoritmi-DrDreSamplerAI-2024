from __future__ import annotations

import json
from pathlib import Path
import random

import mido

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.dataset import file_digest
from samuged.midi import load_midi
from scripts import compare_vote_iteration as study


def _write_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for index in range(24):
        track.append(mido.Message("note_on", note=60 + index % 5, velocity=80, time=0 if index == 0 else 120))
        track.append(mido.Message("note_off", note=60 + index % 5, velocity=0, time=120))
    midi.save(path)


def _manifest_row(path: Path, name: str, saturation: int) -> dict:
    return {
        "status": "ok",
        "source_path": name,
        "source_sha256": file_digest(path),
        "source_bytes": path.stat().st_size,
        "part_stats": [
            {
                "saturated_seed_buckets": saturation,
                "saturated_seed_postings_dropped": saturation * 2,
            }
        ],
    }


def test_candidate_source_is_exact_one_expression_change() -> None:
    baseline = Path("samuged/aligned_indexed.py").read_text()
    candidate = study.candidate_source(baseline)
    assert candidate.count(study.BASELINE_LINE) == 0
    assert candidate.count(study.CANDIDATE_LINE) == 1
    assert candidate.count("from itertools import chain") == 1
    restored = candidate.replace("from itertools import chain\n", "").replace(
        study.CANDIDATE_LINE, study.BASELINE_LINE
    )
    assert restored == baseline


def test_chain_and_generator_vote_multisets_are_equal() -> None:
    rng = random.Random(20261003)
    for _ in range(100):
        postings = [
            [rng.randrange(20) for _ in range(rng.randrange(0, 40))]
            for _ in range(rng.randrange(0, 20))
        ]
        assert study.generator_votes(postings) == study.chain_votes(postings)


def test_copied_candidate_loads_and_matches_baseline(tmp_path) -> None:
    source = tmp_path / "phrase.mid"
    _write_midi(source)
    candidate_path = study.write_candidate(tmp_path / "candidate-root", Path("samuged/aligned_indexed.py"))
    candidate = study.load_candidate(candidate_path)
    song = load_midi(source)
    baseline = extract_indexed(song, AlignedConfig())
    alternative = candidate.extract_indexed(song, AlignedConfig())
    comparison = study.compare_results(baseline, alternative)
    assert comparison["complete_equal"]
    assert comparison["phrases_equal"]
    assert comparison["telemetry_equal"]


def test_real_cohort_and_benchmark_are_deterministic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(study, "BENCHMARK_SATURATED", 2)
    monkeypatch.setattr(study, "BENCHMARK_UNLIMITED", 2)
    rows = []
    for index, saturation in enumerate((2, 1, 0, 0, 0)):
        path = tmp_path / f"{index}.mid"
        _write_midi(path)
        rows.append(_manifest_row(path, path.name, saturation))
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in reversed(rows)))
    cohort, selected = study.select_real_cohort(manifest, expected=5)
    assert len(cohort) == 5
    expected_saturated = sorted(
        (row for row in cohort if row["pilot_saturated_seed_buckets"]),
        key=lambda row: (row["hash_rank"], row["source_path"]),
    )[:2]
    expected_unlimited = sorted(
        (row for row in cohort if not row["pilot_saturated_seed_buckets"]),
        key=lambda row: (row["hash_rank"], row["source_path"]),
    )[:2]
    assert selected == [row["case_id"] for row in [*expected_saturated, *expected_unlimited]]


def test_result_comparison_requires_all_telemetry_to_match() -> None:
    baseline = {"phrases": [], "part_stats": [{"comparisons": 4}], "candidate_count": 0}
    candidate = {"phrases": [], "part_stats": [{"comparisons": 5}], "candidate_count": 0}
    comparison = study.compare_results(baseline, candidate)
    assert comparison["phrases_equal"]
    assert not comparison["telemetry_equal"]
    assert not comparison["complete_equal"]


def test_alternating_order_balances_three_repetitions() -> None:
    orders = [study._alternating_order(repetition + case) for repetition in range(3) for case in range(16)]
    assert orders.count(("baseline", "chain")) == 24
    assert orders.count(("chain", "baseline")) == 24


def test_cli_fails_when_a_correctness_difference_is_recorded(monkeypatch) -> None:
    monkeypatch.setattr(study, "run", lambda *args: {"correctness_failures": 1})
    assert study.main(["--source", "s", "--manifest", "m", "--output", "o"]) == 1
