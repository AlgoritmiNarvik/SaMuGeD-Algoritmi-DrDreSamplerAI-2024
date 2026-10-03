from pathlib import Path
import sys

import pytest

from samuged.evaluate_aligned import (
    aggregate_real_rows,
    load_reference_module,
    paired_bootstrap_difference,
)


def scored(case_id, *, tp, fp, fn, occurrence_tp=None, occurrence_fp=0, occurrence_fn=None):
    occurrence_tp = tp if occurrence_tp is None else occurrence_tp
    occurrence_fn = fn if occurrence_fn is None else occurrence_fn
    return {
        "case_id": case_id,
        "split": "development",
        "kind": "exact",
        "positive": True,
        "limitation": None,
        "elapsed_seconds": 0.1,
        "candidate_tp": tp,
        "candidate_fp": fp,
        "candidate_fn": fn,
        "occurrence_tp": occurrence_tp,
        "occurrence_fp": occurrence_fp,
        "occurrence_fn": occurrence_fn,
        "recovered": bool(tp),
        "recovery_rank": 1 if tp else None,
        "false_positive_case": False,
        "candidates": [],
    }


def test_paired_bootstrap_is_deterministic_and_requires_same_cases():
    reference = [scored("a", tp=1, fp=1, fn=0), scored("b", tp=0, fp=0, fn=1)]
    aligned = [scored("a", tp=1, fp=0, fn=0), scored("b", tp=1, fp=0, fn=0)]
    first = paired_bootstrap_difference(reference, aligned, iterations=50, seed=17)
    second = paired_bootstrap_difference(reference, aligned, iterations=50, seed=17)
    assert first == second
    assert first["candidate_f1"]["aligned_minus_reference"] > 0
    with pytest.raises(ValueError, match="same case ids"):
        paired_bootstrap_difference(reference, aligned[:1], iterations=10, seed=1)


def test_detector_snapshot_loads_under_private_module_name(tmp_path):
    from samuged import phrases

    repository = Path(__file__).resolve().parents[1]
    snapshot = tmp_path / "phrases.py"
    snapshot.write_bytes((repository / "samuged" / "phrases.py").read_bytes())
    module_name = "samuged._reference_test_module"
    try:
        module = load_reference_module(snapshot, module_name)
        assert module.__name__ == module_name
        assert Path(module.__file__) == snapshot
        assert module.Config(mode="approximate", top_k=10).top_k == 10
        assert callable(module.extract)
        assert module is not phrases
        assert sys.modules["samuged.phrases"] is phrases
    finally:
        sys.modules.pop(module_name, None)


def test_real_aggregate_reports_limits_without_accuracy_metrics():
    rows = []
    for method, elapsed, limited in (
        ("reference_approximate", 0.2, False),
        ("aligned", 0.5, True),
    ):
        rows.append(
            {
                "source_path": "example.mid",
                "method": method,
                "status": "ok",
                "elapsed_seconds": elapsed,
                "phrase_count": 3,
                "candidate_count": 8,
                "search_limited": limited,
                "curation_truncated": False,
                "limit_parts": {"comparison_limit_reached": int(limited)},
                "profile_counters": {"comparisons": 4},
            }
        )
    aggregate = aggregate_real_rows(rows)
    assert "accuracy" not in aggregate
    assert aggregate["methods"]["aligned"]["search_limited_files"] == 1
    assert aggregate["paired_runtime_seconds"]["mean_aligned_minus_reference"] == pytest.approx(0.3)
