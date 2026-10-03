import json

from samuged.drums import DrumConfig, extract_drums
from samuged.evaluate_drums import (
    CASE_KINDS,
    METHODS,
    aggregate_results,
    arrangement_overlap_audit,
    audit_saved_run,
    benchmark_design,
    generate_cases,
    one_to_one_matches,
    run_benchmark,
    score_case,
    temporal_iou,
    wilson_interval,
)


def _score(case, mode):
    result = extract_drums(case.song, DrumConfig(mode=mode))
    return score_case(case, result["phrases"], result["stats"], 0.001)


def test_generation_is_reproducible_balanced_and_seed_separated() -> None:
    first = generate_cases(120)
    second = generate_cases(120)

    assert [case.metadata() for case in first] == [case.metadata() for case in second]
    assert sum(case.split == "development" for case in first) == 60
    assert sum(case.split == "test" for case in first) == 60
    assert {case.rng_seed for case in first if case.split == "development"}.isdisjoint(
        {case.rng_seed for case in first if case.split == "test"}
    )
    assert set(CASE_KINDS) == {case.kind for case in first}
    assert all(len(case.truth_intervals) == 2 for case in first if case.positive)
    assert all(not case.truth_intervals for case in first if not case.positive)
    symbolic_hashes = {case.metadata()["symbolic_sha256"] for case in first}
    assert len(symbolic_hashes) > 100
    assert {
        case.song.ticks_per_beat for case in first if case.kind == "ppq_variation"
    } == {96, 240, 480, 960}
    assert benchmark_design()["claim_boundary"].endswith("not evaluated")


def test_truth_uses_whole_bars_and_preserves_simultaneous_hits() -> None:
    cases = {case.kind: case for case in generate_cases(24) if case.split == "development"}

    four = cases["exact_4bar"]
    assert four.truth_intervals == ((0, 7680), (7680, 15360))
    assert four.target_bar_count == 4

    meter = cases["meter_change"]
    assert meter.song.meters == [(0, 3, 4), (2880, 5, 4)]
    assert meter.truth_intervals == ((2880, 5280), (5280, 7680))

    simultaneous = cases["simultaneous_hits"]
    starts = [note.start for note in simultaneous.song.parts[0].notes]
    assert len(starts) > len(set(starts))

    ppq = cases["ppq_variation"].song.ticks_per_beat
    assert ppq in {96, 240, 480, 960}


def test_interval_matching_is_one_to_one_and_maximum_cardinality() -> None:
    truth = [(0, 100), (100, 200)]
    predicted = [(0, 100), (0, 100), (100, 200)]

    matches = one_to_one_matches(predicted, truth)

    assert temporal_iou((0, 100), (100, 200)) == 0
    assert len(matches) == 2
    assert len({truth_index for _prediction, truth_index, _iou in matches}) == 2


def test_exact_and_tolerant_modes_have_expected_control_behavior() -> None:
    cases = {case.kind: case for case in generate_cases(24) if case.split == "development"}

    for kind in ("exact_1bar", "exact_2bar", "exact_4bar", "simultaneous_hits", "meter_change", "ppq_variation"):
        assert _score(cases[kind], "exact")["recovered"]
        assert _score(cases[kind], "tolerant")["recovered"]

    for kind in ("timing_jitter", "missing_strike", "extra_strike"):
        assert not _score(cases[kind], "exact")["recovered"]
        assert _score(cases[kind], "tolerant")["recovered"]

    for kind in (
        "changed_instrument_negative",
        "shuffled_rhythm_negative",
        "independent_rhythm_negative",
    ):
        assert not _score(cases[kind], "exact")["false_positive_case"]
        assert not _score(cases[kind], "tolerant")["false_positive_case"]

    four_bar = _score(cases["exact_4bar"], "exact")
    assert four_bar["recovery_rank"] == 1
    assert four_bar["primitive_subpattern_count"] >= 1


def test_aggregate_has_negative_denominator_wilson_and_resource_counts() -> None:
    cases = generate_cases(24)
    rows = [_score(case, "tolerant") for case in cases]
    aggregate = aggregate_results(rows)

    assert aggregate["negative_cases"] == 6
    assert aggregate["false_positive_case_denominator"] == 6
    assert aggregate["false_positive_case_count"] == 0
    assert 0 < aggregate["zero_false_positive_upper_95"] < 1
    assert wilson_interval(0, 6) == aggregate["false_positive_rate_wilson_95"]
    assert aggregate["search_limited_cases"] == 0
    assert set(aggregate["resource_limit_counts"]) == {
        "window_limit_reached",
        "comparison_limit_reached",
        "hit_limit_reached",
        "candidate_limit_reached",
    }


def test_arrangement_overlap_audit_distinguishes_seed_and_content_overlap() -> None:
    rows = [
        {
            "case_id": "development-a",
            "split": "development",
            "kind": "exact_1bar",
            "rng_seed": 1,
            "symbolic_sha256": "a" * 64,
        },
        {
            "case_id": "development-b",
            "split": "development",
            "kind": "exact_1bar",
            "rng_seed": 2,
            "symbolic_sha256": "b" * 64,
        },
        {
            "case_id": "test-a",
            "split": "test",
            "kind": "exact_1bar",
            "rng_seed": 3,
            "symbolic_sha256": "a" * 64,
        },
        {
            "case_id": "test-c",
            "split": "test",
            "kind": "timing_jitter",
            "rng_seed": 4,
            "symbolic_sha256": "c" * 64,
        },
    ]

    audit = arrangement_overlap_audit(rows)

    assert audit["rng_seed_overlap_count"] == 0
    assert audit["unique_arrangements"] == 3
    assert audit["cross_split_shared_arrangements"] == 1
    assert audit["cross_split_overlap_cases"] == 2
    assert audit["split"]["test"]["cross_split_overlap_case_rate"] == 0.5
    assert audit["per_condition"]["exact_1bar"]["cross_split_shared_arrangements"] == 1
    assert audit["cross_split_evidence"][0]["symbolic_sha256"] == "a" * 64


def test_benchmark_writes_machine_readable_raw_and_aggregate(tmp_path) -> None:
    aggregate = run_benchmark(
        tmp_path / "drums",
        case_count=24,
        bootstrap_iterations=30,
    )
    raw = json.loads((tmp_path / "drums/raw_results.json").read_text())
    saved = json.loads((tmp_path / "drums/aggregate.json").read_text())

    assert aggregate == saved
    assert aggregate["case_count"] == 24
    assert set(aggregate["methods"]) == set(METHODS)
    assert set(aggregate["methods"]["tolerant"]["by_split"]) == {
        "development",
        "test",
    }
    assert raw["design_sha256"] == aggregate["design_sha256"]
    assert len(raw["cases"]) == 24
    assert all("resource" in case["methods"]["exact"] for case in raw["cases"])
    assert set(aggregate["methods"]["tolerant"]["bootstrap_ci95"]) == {
        "candidate_f1",
        "occurrence_f1",
        "positive_recovery_rate",
        "false_positive_case_rate",
    }
    audit = aggregate["supplementary_arrangement_overlap_audit"]
    assert audit["cases"] == 24
    assert audit_saved_run(tmp_path / "drums") == audit
