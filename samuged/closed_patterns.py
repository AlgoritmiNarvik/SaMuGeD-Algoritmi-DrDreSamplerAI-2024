"""Optional closed exact-pattern selection for aligned candidate lists.

The selector preserves the frozen aligned ordering, redundancy and boundary
extension behavior. It adds one narrow replacement rule for a longer exact
family supported by at least three source-verified occurrences.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from . import aligned as _aligned
from .aligned_indexed import detect_indexed_part
from .midi import MidiSong


CLOSED_PATTERN_VERSION = "closed-exact-extension-v1"
MIN_EXACT_SUPPORT = 3
SCORE_MARGIN = 0.02
ALGORITHMS = ("aligned", "aligned_indexed")


def _zero(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == 0.0


def has_exact_occurrence_evidence(candidate: dict) -> bool:
    """Return whether every occurrence is a complete zero-residual alignment."""
    flags = candidate.get("matcher_flags", {})
    if not (
        flags.get("source_verified") is True
        and flags.get("fixed_transposition") is True
        and flags.get("tempo_warp") is False
        and flags.get("terminal_gaps_allowed") is False
    ):
        return False
    note_count = candidate.get("note_count")
    occurrences = candidate.get("occurrences")
    if (
        not isinstance(note_count, int)
        or note_count < 1
        or not isinstance(occurrences, list)
        or candidate.get("occurrence_count") != len(occurrences)
        or len(occurrences) < MIN_EXACT_SUPPORT
    ):
        return False
    expected_pairs = [[index, index] for index in range(note_count)]
    for occurrence in occurrences:
        if occurrence.get("source_verified") is not True:
            return False
        if occurrence.get("note_count") != note_count:
            return False
        if occurrence.get("edit_count") != 0:
            return False
        if occurrence.get("inserted_note_indices") != []:
            return False
        if occurrence.get("deleted_prototype_note_indices") != []:
            return False
        if occurrence.get("substituted_note_pairs") != []:
            return False
        if occurrence.get("matched_note_pairs") != expected_pairs:
            return False
        if not _zero(occurrence.get("max_timing_error_beats")):
            return False
        if not _zero(occurrence.get("max_duration_error_beats")):
            return False
        if occurrence.get("similarity") != 1.0:
            return False
        if not isinstance(occurrence.get("transpose_semitones"), int):
            return False
    return True


def _endpoint_contains(outer: dict, inner: dict) -> bool:
    return (
        outer["start_tick"] <= inner["start_tick"]
        and outer["end_tick"] >= inner["end_tick"]
        and (
            outer["start_tick"] == inner["start_tick"]
            or outer["end_tick"] == inner["end_tick"]
        )
    )


def _one_to_one_endpoint_containment(outer: list[dict], inner: list[dict]) -> bool:
    edges = [
        [index for index, candidate in enumerate(outer) if _endpoint_contains(candidate, item)]
        for item in inner
    ]
    if any(not candidates for candidates in edges):
        return False
    matched: dict[int, int] = {}

    def augment(inner_index: int, seen: set[int]) -> bool:
        for outer_index in edges[inner_index]:
            if outer_index in seen:
                continue
            seen.add(outer_index)
            if outer_index not in matched or augment(matched[outer_index], seen):
                matched[outer_index] = inner_index
                return True
        return False

    return all(augment(index, set()) for index in range(len(inner)))


def prefer_closed_exact_extension(candidate: dict, selected: dict) -> bool:
    """Return whether a longer exact family should replace a nested sibling."""
    if candidate.get("part_index") != selected.get("part_index"):
        return False
    if candidate.get("note_count", 0) <= selected.get("note_count", 0):
        return False
    support = candidate.get("occurrence_count")
    if support != selected.get("occurrence_count") or not isinstance(support, int):
        return False
    if support < MIN_EXACT_SUPPORT:
        return False
    candidate_score = candidate.get("recurrence_score")
    selected_score = selected.get("recurrence_score")
    if not isinstance(candidate_score, (int, float)) or not isinstance(
        selected_score, (int, float)
    ):
        return False
    if candidate_score + SCORE_MARGIN < selected_score:
        return False
    if not has_exact_occurrence_evidence(candidate):
        return False
    if not has_exact_occurrence_evidence(selected):
        return False
    return _one_to_one_endpoint_containment(
        candidate["occurrences"], selected["occurrences"]
    )


def _ordered(candidates: Iterable[dict]) -> list[dict]:
    return sorted(
        candidates,
        key=lambda item: (
            -item["recurrence_score"],
            -item["note_count"],
            item["part_index"],
            item["start_tick"],
            item["family_id"],
        ),
    )


def select_original_candidates(candidates: Iterable[dict], top_k: int) -> list[dict]:
    """Reproduce the frozen aligned selector for an existing candidate list."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    selected: list[dict] = []
    for candidate in _ordered(candidates):
        redundant_index = next(
            (
                index
                for index, prior in enumerate(selected)
                if _aligned._redundant(candidate, prior)
            ),
            None,
        )
        if redundant_index is None:
            selected.append(candidate)
        elif _aligned._prefer_boundary_extension(candidate, selected[redundant_index]):
            selected[redundant_index] = candidate
        if len(selected) == top_k:
            break
    return selected


def select_closed_candidates_with_trace(
    candidates: Iterable[dict], top_k: int
) -> tuple[list[dict], list[dict]]:
    """Apply the optional exact-extension rule and return replacement evidence."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    selected: list[dict] = []
    trace: list[dict] = []
    for raw_rank, candidate in enumerate(_ordered(candidates), 1):
        redundant_index = next(
            (
                index
                for index, prior in enumerate(selected)
                if _aligned._redundant(candidate, prior)
            ),
            None,
        )
        if redundant_index is None:
            selected.append(candidate)
        else:
            prior = selected[redundant_index]
            original_extension = _aligned._prefer_boundary_extension(candidate, prior)
            closed_extension = prefer_closed_exact_extension(candidate, prior)
            if original_extension or closed_extension:
                selected[redundant_index] = candidate
                if closed_extension and not original_extension:
                    trace.append(
                        {
                            "raw_rank": raw_rank,
                            "selected_index": redundant_index,
                            "replaced_family_id": prior["family_id"],
                            "replacement_family_id": candidate["family_id"],
                            "replaced_note_count": prior["note_count"],
                            "replacement_note_count": candidate["note_count"],
                            "support": candidate["occurrence_count"],
                            "replaced_score": prior["recurrence_score"],
                            "replacement_score": candidate["recurrence_score"],
                            "replaced_intervals": [
                                [row["start_tick"], row["end_tick"]]
                                for row in prior["occurrences"]
                            ],
                            "replacement_intervals": [
                                [row["start_tick"], row["end_tick"]]
                                for row in candidate["occurrences"]
                            ],
                        }
                    )
        if len(selected) == top_k:
            break
    return selected, trace


def select_closed_candidates(candidates: Iterable[dict], top_k: int) -> list[dict]:
    """Select candidates with the optional closed exact-pattern rule."""
    selected, _ = select_closed_candidates_with_trace(candidates, top_k)
    return selected


def extract_closed_patterns(
    song: MidiSong,
    cfg: _aligned.AlignedConfig | None = None,
    *,
    algorithm: str = "aligned",
) -> dict:
    """Detect with an existing aligned index and apply optional selection."""
    cfg = cfg or _aligned.AlignedConfig()
    if not isinstance(cfg, _aligned.AlignedConfig):
        raise TypeError("cfg must be an AlignedConfig")
    if algorithm not in ALGORITHMS:
        raise ValueError(f"algorithm must be one of {ALGORITHMS}")
    detector = (
        _aligned.detect_aligned_part
        if algorithm == "aligned"
        else detect_indexed_part
    )
    candidates, stats = [], []
    for part in song.parts:
        found, audit = detector(song, part, cfg)
        candidates.extend(found)
        stats.append(audit)
    phrases, trace = select_closed_candidates_with_trace(candidates, cfg.top_k)
    limit_keys = (
        "note_limit_reached",
        "window_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
    )
    return {
        "config": asdict(cfg),
        "algorithm": algorithm,
        "selection": CLOSED_PATTERN_VERSION,
        "phrases": phrases,
        "selection_trace": trace,
        "closed_extension_count": len(trace),
        "candidate_count": len(candidates),
        "raw_repeat_group_count": sum(part["repeat_groups"] for part in stats),
        "shortlisted_candidate_count": len(candidates),
        "curation_truncated": any(part["candidate_limit_reached"] for part in stats),
        "search_limited": any(
            any(part[key] for key in limit_keys) or part["saturated_seed_buckets"]
            for part in stats
        ),
        "part_stats": stats,
    }
