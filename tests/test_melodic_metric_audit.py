from __future__ import annotations

from fractions import Fraction

import pytest

from scripts import audit_melodic_metrics as audit


def test_exact_iou_threshold_includes_four_fifths() -> None:
    assert audit.temporal_iou_fraction((0, 80), (0, 100)) == Fraction(4, 5)
    assert audit.eligible_edges([(0, 80)], [(0, 100)]) == [[(0, Fraction(4, 5))]]
    assert audit.eligible_edges([(0, 79)], [(0, 100)]) == [[]]


@pytest.mark.parametrize(
    "interval",
    [(-1, 2), (2, 2), (3, 2), (False, 2), (0, 1.5), (0,), "0,1"],
)
def test_invalid_intervals_fail_closed(interval) -> None:
    with pytest.raises(ValueError):
        audit.temporal_iou_fraction(interval, (0, 10))


def test_maximum_cardinality_handles_graph_where_greedy_loses() -> None:
    # Highest IoU is p0-t0. Taking it greedily leaves p1 unmatched, while the
    # augmenting path assigns p0-t1 and p1-t0 for cardinality two.
    predicted = [(10, 115), (0, 100)]
    truth = [(10, 110), (20, 120)]

    edges = audit.eligible_edges(predicted, truth)
    assert [[index for index, _score in row] for row in edges] == [[0, 1], [0]]
    matches = audit.maximum_cardinality_matches(predicted, truth)

    assert len(matches) == 2
    assert {(prediction, truth_index) for prediction, truth_index, _iou in matches} == {
        (0, 1),
        (1, 0),
    }


def test_disjoint_truth_has_at_most_one_edge_at_threshold() -> None:
    truth = [(0, 100), (100, 200), (200, 300)]
    predicted = [(0, 80), (10, 110), (95, 205), (200, 300), (0, 300)]
    assert all(len(row) <= 1 for row in audit.eligible_edges(predicted, truth))


def test_row_audit_reconstructs_saved_candidate_and_occurrence_metrics() -> None:
    case = {
        "case_id": "test-case",
        "split": "test",
        "kind": "exact",
        "positive": True,
        "truth_intervals": [(0, 100), (200, 300)],
    }
    row = {
        "case_id": "test-case",
        "split": "test",
        "kind": "exact",
        "positive": True,
        "candidate_tp": 1,
        "candidate_fp": 1,
        "candidate_fn": 0,
        "occurrence_tp": 2,
        "occurrence_fp": 1,
        "occurrence_fn": 0,
        "recovered": True,
        "recovery_rank": 1,
        "false_positive_case": False,
        "candidates": [
            {
                "rank": 1,
                "correct_family": True,
                "intervals": [[0, 100], [200, 300]],
                "truth_matches": [[1, 1, 1.0], [0, 0, 1.0]],
            },
            {
                "rank": 2,
                "correct_family": False,
                "intervals": [[400, 500]],
                "truth_matches": [],
            },
        ],
    }

    mismatches, stats = audit._audit_score_row(
        row, case, {"study": "fixture", "stream": "method"}
    )

    assert mismatches == []
    assert stats["candidate_tp"] == 1
    assert stats["occurrence_tp"] == 2
    assert stats["occurrence_fp"] == 1
    assert stats["predictions_with_multiple_truth_edges"] == 0


def test_row_audit_reports_saved_coordinate_and_metric_corruption() -> None:
    case = {
        "case_id": "test-case",
        "split": "test",
        "kind": "exact",
        "positive": True,
        "truth_intervals": [(0, 100)],
    }
    row = {
        "case_id": "test-case",
        "split": "test",
        "kind": "exact",
        "positive": True,
        "candidate_tp": 0,
        "candidate_fp": 1,
        "candidate_fn": 1,
        "occurrence_tp": 0,
        "occurrence_fp": 1,
        "occurrence_fn": 1,
        "recovered": False,
        "recovery_rank": None,
        "false_positive_case": False,
        "candidates": [
            {
                "rank": 1,
                "correct_family": False,
                "intervals": [[0, 100]],
                "truth_matches": [[0, 0, 0.99]],
            }
        ],
    }

    mismatches, _stats = audit._audit_score_row(
        row, case, {"study": "fixture", "stream": "method"}
    )
    fields = {item["field"] for item in mismatches}

    assert "candidate.truth_matches" in fields
    assert "candidate.correct_family" in fields
    assert "candidate_tp" in fields
    assert "occurrence_tp" in fields
    assert "recovery_rank" in fields
