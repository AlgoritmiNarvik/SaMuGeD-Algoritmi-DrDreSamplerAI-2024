"""Independent checks for saved optional part-ranking evidence."""
from __future__ import annotations

from dataclasses import asdict
import math
import re

from .midi import MidiSong
from .part_ranking import (
    FEATURE_VERSION,
    MELODY_PRIOR_CONFIG,
    PART_PRIOR_VERSION,
    song_part_scores,
)
from .closed_patterns import CLOSED_PATTERN_VERSION


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def verify_part_ranking(record: dict, song: MidiSong, top_k: object) -> list[str]:
    """Recompute source features and validate saved score and order evidence."""
    problems: list[str] = []
    evidence = record.get("part_ranking")
    if not isinstance(evidence, dict):
        return ["part ranking evidence is missing"]
    if evidence.get("version") != PART_PRIOR_VERSION:
        problems.append("part ranking version differs")
    if evidence.get("feature_version") != FEATURE_VERSION:
        problems.append("part feature version differs")
    if evidence.get("closed_selection") != CLOSED_PATTERN_VERSION:
        problems.append("part ranking closed selection differs")
    if evidence.get("config") != asdict(MELODY_PRIOR_CONFIG):
        problems.append("part ranking config differs from the fixed optional rule")
    if evidence.get("reranks_full_shortlist") is not True:
        problems.append("part ranking shortlist scope differs")
    valid_top_k = type(top_k) is int and top_k > 0
    if type(evidence.get("top_k")) is not int or evidence.get("top_k") != top_k:
        problems.append("part ranking phrase budget differs from build config")
    candidate_count = evidence.get("candidate_count")
    if (
        type(candidate_count) is not int
        or candidate_count < 0
        or candidate_count != record.get("candidate_count")
        or candidate_count != record.get("shortlisted_candidate_count")
    ):
        problems.append("part ranking candidate count differs")
    order_hash = evidence.get("candidate_order_sha256")
    if not isinstance(order_hash, str) or _HEX64.fullmatch(order_hash) is None:
        problems.append("part ranking candidate order hash is invalid")

    expected_scores, expected_features = song_part_scores(song, MELODY_PRIOR_CONFIG)
    saved_scores = evidence.get("part_scores")
    saved_features = evidence.get("part_features")
    expected_score_rows = {str(key): value for key, value in sorted(expected_scores.items())}
    expected_feature_rows = {str(key): value for key, value in sorted(expected_features.items())}
    if saved_scores != expected_score_rows:
        problems.append("part scores differ from source note structure")
    if saved_features != expected_feature_rows:
        problems.append("part features differ from source note structure")

    melodic = [phrase for phrase in record.get("phrases", []) if phrase.get("kind") == "melodic"]
    selected = evidence.get("selected")
    if not isinstance(selected, list) or len(selected) != len(melodic):
        problems.append("part ranking selected evidence differs from melodic output")
        selected = []
    family_ids = evidence.get("selected_family_ids")
    if family_ids != [phrase.get("family_id") for phrase in melodic]:
        problems.append("part ranking selected family order differs")
    seen_ranks: set[int] = set()
    for index, (saved, phrase) in enumerate(zip(selected, melodic)):
        if not isinstance(saved, dict):
            problems.append("part ranking selected row is invalid")
            continue
        rank = saved.get("candidate_rank")
        if (
            type(rank) is not int
            or rank < 1
            or not isinstance(candidate_count, int)
            or rank > candidate_count
            or rank in seen_ranks
        ):
            problems.append("part ranking selected candidate rank is invalid")
        else:
            seen_ranks.add(rank)
        if saved.get("selected_index") != index:
            problems.append("part ranking selected output order differs")
        for key in (
            "family_id",
            "part_index",
            "start_tick",
            "end_tick",
            "note_count",
            "recurrence_score",
        ):
            if saved.get(key) != phrase.get(key):
                problems.append(f"part ranking selected {key} differs from phrase")
        part_index = phrase.get("part_index")
        part_score = expected_scores.get(part_index)
        if saved.get("part_score") != part_score:
            problems.append("part ranking selected part score differs")
        recurrence = phrase.get("recurrence_score")
        if _finite(recurrence) and part_score is not None:
            adjusted = round(
                float(recurrence)
                + MELODY_PRIOR_CONFIG.strength * (part_score - 0.5),
                8,
            )
            if saved.get("adjusted_score") != adjusted:
                problems.append("part ranking selected adjusted score differs")
        else:
            problems.append("part ranking selected score inputs are invalid")

    replacements = evidence.get("replacements")
    if not isinstance(replacements, list):
        problems.append("part ranking replacement evidence is invalid")
    else:
        for replacement in replacements:
            candidate_upper = candidate_count if type(candidate_count) is int and candidate_count >= 0 else 0
            valid = isinstance(replacement, dict)
            valid = valid and type(replacement.get("rank")) is int
            valid = valid and 1 <= replacement.get("rank", 0) <= max(candidate_upper, 1)
            valid = valid and type(replacement.get("selected_index")) is int
            valid = valid and valid_top_k and 0 <= replacement.get("selected_index", -1) < top_k
            valid = valid and type(replacement.get("boundary_extension")) is bool
            valid = valid and type(replacement.get("closed_extension")) is bool
            valid = valid and (
                replacement.get("boundary_extension") is True
                or replacement.get("closed_extension") is True
            )
            valid = valid and all(
                isinstance(replacement.get(key), str)
                and _HEX64.fullmatch(replacement[key]) is not None
                for key in ("replaced_family_id", "replacement_family_id")
            )
            if not valid:
                problems.append("part ranking replacement evidence is invalid")
                break
    return problems
