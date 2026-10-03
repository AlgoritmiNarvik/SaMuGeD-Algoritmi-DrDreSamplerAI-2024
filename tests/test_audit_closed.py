from copy import deepcopy

import pytest

from samuged.audit_closed import verify_closed_trace


def _record():
    return {
        "shortlisted_candidate_count": 8,
        "selection_trace": [{
            "raw_rank": 2, "selected_index": 0,
            "replaced_note_count": 6, "replacement_note_count": 8,
            "replaced_family_id": "1" * 64, "replacement_family_id": "2" * 64,
            "replaced_score": .82, "replacement_score": .81,
            "support": 3,
            "replaced_intervals": [[200, 800], [1200, 1800], [2200, 2800]],
            "replacement_intervals": [[0, 800], [1000, 1800], [2000, 2800]],
        }],
    }


CONFIG = {"top_k": 3, "min_notes": 6, "max_notes": 32}


def test_closed_trace_checks_geometry_and_allows_chained_per_step_margin():
    record = _record()
    first = record["selection_trace"][0]
    second = deepcopy(first)
    second.update(raw_rank=5, replaced_note_count=8, replacement_note_count=10,
                  replaced_family_id="2" * 64, replacement_family_id="3" * 64,
                  replaced_score=.81, replacement_score=.79,
                  replaced_intervals=first["replacement_intervals"],
                  replacement_intervals=[[0, 900], [1000, 1900], [2000, 2900]])
    record["selection_trace"].append(second)
    assert verify_closed_trace(record, CONFIG, 3000) == []


@pytest.mark.parametrize(("field", "value", "message"), [
    ("raw_rank", 9, "raw rank"),
    ("selected_index", True, "selection index"),
    ("support", 2, "exact support"),
    ("replacement_note_count", 6, "note count"),
    ("replacement_family_id", "1" * 64, "distinct family"),
    ("replacement_score", .79, "score margin"),
    ("replacement_score", float("nan"), "score margin"),
    ("replacement_intervals", [[0, 799], [1000, 1800], [2000, 2800]], "containment"),
    ("replacement_intervals", [[0, 800], [700, 1800], [2000, 2800]], "nonoverlapping"),
    ("replacement_intervals", [[0, 800], [1000, 1800], [2000, 3100]], "nonoverlapping"),
])
def test_closed_trace_rejects_invalid_replacement_evidence(field, value, message):
    record = _record()
    record["selection_trace"][0][field] = value
    assert any(message in issue for issue in verify_closed_trace(record, CONFIG, 3000))
