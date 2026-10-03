"""Check saved closed-extension trace geometry without running the selector.

These checks cover the recorded replacement rule. Exact note evidence for the
selected phrases is checked by the alignment audit; complete selection replay
still requires the main audit's explicit re-extraction option.
"""
from __future__ import annotations

import math
import re


def _integer(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _intervals(value: object, support: int, last_tick: int) -> bool:
    if not isinstance(value, list) or len(value) != support:
        return False
    previous_end = -1
    for interval in value:
        if not isinstance(interval, list) or len(interval) != 2:
            return False
        start, end = interval
        if not (_integer(start, 0, last_tick) and _integer(end, 1, last_tick)):
            return False
        if start < previous_end or end <= start:
            return False
        previous_end = end
    return True


def verify_closed_trace(record: dict, config: dict, last_tick: int) -> list[str]:
    """Return violations of the saved exact-extension trace contract."""
    trace = record.get("selection_trace")
    if not isinstance(trace, list):
        return ["closed selection trace is missing"]
    problems = []
    previous_rank = 0
    for index, step in enumerate(trace):
        prefix = f"closed selection trace step {index}"
        if not isinstance(step, dict):
            problems.append(f"{prefix} is not an object")
            continue
        rank = step.get("raw_rank")
        if not _integer(rank, previous_rank + 1, record.get("shortlisted_candidate_count", 0)):
            problems.append(f"{prefix} has invalid raw rank")
        elif type(rank) is int:
            previous_rank = rank
        if not _integer(step.get("selected_index"), 0, config["top_k"] - 1):
            problems.append(f"{prefix} has invalid selection index")
        left_count, right_count = step.get("replaced_note_count"), step.get("replacement_note_count")
        if not (_integer(left_count, config["min_notes"], config["max_notes"])
                and _integer(right_count, config["min_notes"], config["max_notes"])
                and right_count > left_count):
            problems.append(f"{prefix} does not extend note count")
        for field in ("replaced_family_id", "replacement_family_id"):
            value = step.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                problems.append(f"{prefix} has invalid {field}")
        if step.get("replaced_family_id") == step.get("replacement_family_id"):
            problems.append(f"{prefix} does not replace a distinct family")
        left_score, right_score = step.get("replaced_score"), step.get("replacement_score")
        scores_valid = all(type(value) in (int, float) and math.isfinite(value)
                           and 0 <= value <= 1 for value in (left_score, right_score))
        if not scores_valid or right_score + 0.02 + 1e-12 < left_score:
            problems.append(f"{prefix} exceeds the per-step score margin")
        support = step.get("support")
        if not _integer(support, 3, max(3, last_tick)):
            problems.append(f"{prefix} has invalid exact support")
            continue
        inner, outer = step.get("replaced_intervals"), step.get("replacement_intervals")
        if not (_intervals(inner, support, last_tick) and _intervals(outer, support, last_tick)):
            problems.append(f"{prefix} has invalid nonoverlapping intervals")
            continue
        # Both lists are sorted and internally disjoint, so any one-to-one
        # containment matching must preserve their order.
        if any(not (new[0] <= old[0] and new[1] >= old[1]
                    and (new[0] == old[0] or new[1] == old[1]))
               for old, new in zip(inner, outer)):
            problems.append(f"{prefix} lacks one-to-one endpoint containment")
    return problems
