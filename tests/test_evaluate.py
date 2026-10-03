import json

from samuged.evaluate import (
    CASE_KINDS,
    aggregate_results,
    generate_cases,
    run_benchmark,
    score_case,
    select_legacy_cases,
    temporal_iou,
)


def test_case_generation_is_balanced_reproducible_and_seed_separated():
    first = generate_cases(100)
    second = generate_cases(100)
    assert [case.metadata() for case in first] == [case.metadata() for case in second]
    assert sum(case.split == "development" for case in first) == 50
    assert sum(case.split == "test" for case in first) == 50
    assert {case.rng_seed for case in first if case.split == "development"}.isdisjoint(
        {case.rng_seed for case in first if case.split == "test"}
    )
    assert set(CASE_KINDS) == {case.kind for case in first}
    assert all(len(case.truth_intervals) >= 2 for case in first if case.positive)
    assert all(not case.truth_intervals for case in first if not case.positive)


def test_temporal_iou_and_candidate_occurrence_scoring():
    case = generate_cases(1)[0]
    truth = case.truth_intervals
    assert len(truth) == 3
    assert truth[0][1] == truth[1][0]
    assert truth[1][1] == truth[2][0]
    assert temporal_iou(truth[0], truth[0]) == 1.0
    assert temporal_iou((0, 100), (100, 200)) == 0.0
    phrase = {
        "family_id": "true",
        "note_count": len(case.prototype),
        "recurrence_score": 0.9,
        "occurrences": [
            {"start_tick": start, "end_tick": end} for start, end in truth
        ],
    }
    result = score_case(case, [phrase], 0.01)
    assert result["candidate_tp"] == 1
    assert result["occurrence_tp"] == 3
    assert result["recovery_rank"] == 1
    aggregate = aggregate_results([result])
    assert aggregate["candidate"]["f1"] == 1.0
    assert aggregate["occurrence"]["f1"] == 1.0


def test_negative_predictions_are_counted_as_false_positive_cases():
    case = next(case for case in generate_cases(12) if not case.positive)
    phrase = {
        "family_id": "false",
        "note_count": 8,
        "recurrence_score": 0.4,
        "occurrences": [
            {"start_tick": 0, "end_tick": 480},
            {"start_tick": 960, "end_tick": 1440},
        ],
    }
    result = score_case(case, [phrase], 0.01)
    assert result["candidate_tp"] == 0
    assert result["candidate_fp"] == 1
    assert result["false_positive_case"]


def test_legacy_selection_round_robins_case_kinds_and_splits():
    selected = select_legacy_cases(generate_cases(100), 12)
    assert len({case.kind for case in selected}) == 12
    assert "legacy_contiguous_exact" in {case.kind for case in selected}
    assert {case.split for case in selected} == {"development", "test"}


def test_benchmark_writes_raw_aggregate_and_markdown(tmp_path):
    aggregate = run_benchmark(tmp_path / "evaluation", seeds=2, legacy_limit=0, bootstrap_iterations=20)
    assert aggregate["case_count"] == 2
    assert set(aggregate["methods"]) == {"exact", "transposed", "approximate"}
    assert set(aggregate["methods"]["exact"]["by_split"]) == {"development", "test"}
    raw = json.loads((tmp_path / "evaluation/raw_results.json").read_text())
    saved = json.loads((tmp_path / "evaluation/aggregate.json").read_text())
    report = (tmp_path / "evaluation/report.md").read_text()
    assert len(raw["cases"]) == 2
    assert raw["design_sha256"] == saved["design_sha256"]
    assert "Planted motif evaluation" in report
    assert "human memorability" in report
