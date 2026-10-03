"""Frozen stress diagnostics for recurring symbolic drum patterns.

This cohort probes supported and deliberately unsupported conditions without
changing detector configuration. It measures symbolic target recovery, not
musical quality, salience or catchiness.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics
import time
from typing import Iterable

from .drums import DrumConfig, drum_part, extract_drums
from .evaluate_drums import one_to_one_matches, wilson_interval
from .experiment import complete_experiment, prepare_experiment, receipt_links
from .midi import MidiSong, Note, Part


STRESS_VERSION = "drum-stress-v1"
METHODS = ("exact", "tolerant")
IOU_THRESHOLD = 0.9
CONDITIONS = (
    "varied_exact",
    "timing_inside_tolerance",
    "timing_outside_tolerance",
    "missing_at_tolerance",
    "missing_beyond_tolerance",
    "extra_at_tolerance",
    "extra_beyond_tolerance",
    "syncopated_simultaneous",
    "multitrack_merged",
    "pickup_bar_origin_mismatch",
    "shuffled_instrument_rhythm_negative",
    "independent_patterns_negative",
)
NEGATIVE_CONDITIONS = frozenset(
    {"shuffled_instrument_rhythm_negative", "independent_patterns_negative"}
)
DIAGNOSTIC_FAILURE_CONDITIONS = frozenset(
    {
        "timing_outside_tolerance",
        "missing_beyond_tolerance",
        "extra_beyond_tolerance",
        "pickup_bar_origin_mismatch",
    }
)
EXACT_IDENTITY_CONTROL_CONDITIONS = frozenset(
    {"varied_exact", "syncopated_simultaneous", "multitrack_merged"}
)
TOLERANT_SUPPORTED_CONTROL_CONDITIONS = frozenset(
    EXACT_IDENTITY_CONTROL_CONDITIONS
    | {
        "timing_inside_tolerance",
        "missing_at_tolerance",
        "extra_at_tolerance",
    }
)
_NAMESPACES = {
    "development": "samuged-drum-stress-development-v1",
    "test": "samuged-drum-stress-test-v1",
}


@dataclass(frozen=True)
class StressCase:
    case_id: str
    split: str
    condition: str
    design_index: int
    attempt: int
    rng_seed: int
    song: MidiSong
    truth_intervals: tuple[tuple[int, int], ...]
    target_bar_count: int
    occurrence_count: int
    positive: bool
    diagnostic_expected_failure: bool
    intervention: dict
    phrase_design_sha256: str
    exact_arrangement_sha256: str
    beat_arrangement_sha256: str

    def metadata(self) -> dict:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "condition": self.condition,
            "design_index": self.design_index,
            "attempt": self.attempt,
            "rng_seed": self.rng_seed,
            "positive": self.positive,
            "diagnostic_expected_failure": self.diagnostic_expected_failure,
            "target_bar_count": self.target_bar_count,
            "occurrence_count": self.occurrence_count,
            "truth_intervals": [list(interval) for interval in self.truth_intervals],
            "ticks_per_beat": self.song.ticks_per_beat,
            "meters": [list(change) for change in self.song.meters],
            "part_count": len(self.song.parts),
            "note_count": sum(len(part.notes) for part in self.song.parts),
            "intervention": self.intervention,
            "phrase_design_sha256": self.phrase_design_sha256,
            "exact_arrangement_sha256": self.exact_arrangement_sha256,
            "beat_arrangement_sha256": self.beat_arrangement_sha256,
        }


def frozen_design(cases_per_condition: int) -> dict:
    return {
        "version": STRESS_VERSION,
        "conditions": list(CONDITIONS),
        "negative_conditions": sorted(NEGATIVE_CONDITIONS),
        "diagnostic_expected_failure_conditions": sorted(
            DIAGNOSTIC_FAILURE_CONDITIONS
        ),
        "expected_control_support": {
            "exact": sorted(EXACT_IDENTITY_CONTROL_CONDITIONS),
            "tolerant": sorted(TOLERANT_SUPPORTED_CONTROL_CONDITIONS),
        },
        "cases_per_condition": cases_per_condition,
        "minimum_distinct_phrase_designs_per_condition": 20,
        "splits": ["development", "test"],
        "seed_namespaces": dict(_NAMESPACES),
        "methods": list(METHODS),
        "detector_configs": {
            method: asdict(DrumConfig(mode=method)) for method in METHODS
        },
        "target_iou_threshold": IOU_THRESHOLD,
        "target_definition": (
            "whole intended phrase intervals computed from generator bar geometry, "
            "independent of detector output and note envelopes"
        ),
        "occurrences_per_positive_case": [3, 5],
        "target_bar_counts": [1, 2, 4],
        "timing_tolerance_beats": 1 / 12,
        "inside_timing_jitter_beats": [-1 / 20, 1 / 20],
        "outside_timing_jitter_absolute_beats": [0.105, 0.15],
        "edit_policy": (
            "at-tolerance edits use the greatest integer count accepted by the "
            "configured ten-percent rule; beyond-tolerance edits use one more"
        ),
        "pickup_policy": (
            "one-quarter-bar phase offset from the assumed bar origin; failure "
            "is an expected diagnostic of the documented unsupported pickup model"
        ),
        "split_policy": (
            "deterministic rejection of duplicate phrase designs and duplicate exact "
            "or 1/96-beat-normalized arrangements before detector execution"
        ),
        "metric_policy": (
            "target recovery and target occurrence metrics are primary; all returned "
            "occurrences are also reported, while contained shorter patterns are marked "
            "nested legitimate structure rather than musical false positives"
        ),
        "claim_boundary": (
            "synthetic stress diagnostics only; unsupported cases are not detector bugs "
            "and returned recurrence is not evidence of catchiness"
        ),
    }


def _seed(split: str, condition: str, design_index: int, attempt: int) -> int:
    value = f"{_NAMESPACES[split]}:{condition}:{design_index}:{attempt}".encode()
    return int.from_bytes(sha256(value).digest()[:8], "big")


def _canonical_hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _phrase_pattern(
    rng: random.Random,
    bar_count: int,
    bar_beats: float,
    *,
    strongly_syncopated: bool,
) -> tuple[list[tuple[float, int]], dict]:
    kick = rng.choice((35, 36))
    snare = rng.choice((38, 40))
    hat = rng.choice((42, 44))
    open_hat = rng.choice((46, 49))
    toms = rng.sample((41, 43, 45, 47, 48, 50), 3)
    swing = rng.uniform(-0.11, 0.11)
    phrase: list[tuple[float, int]] = []
    for bar_index in range(bar_count):
        base = bar_index * bar_beats
        step = bar_beats / 16
        for grid in range(16):
            shift = swing * step if grid % 2 else 0.0
            if strongly_syncopated and grid in {3, 7, 11, 15}:
                shift += rng.choice((-0.28, 0.28)) * step
            phrase.append((base + grid * step + shift, hat))
        kick_grid = (0, 7 + bar_index % 2, 11 + bar_index % 3)
        snare_grid = (4 + bar_index % 2, 12 - bar_index % 2)
        accent_grid = (2.5 + bar_index % 2, 9.5, 14 - bar_index % 2)
        phrase.extend((base + grid * step, kick) for grid in kick_grid)
        phrase.extend((base + grid * step, snare) for grid in snare_grid)
        phrase.extend(
            (base + grid * step, toms[index])
            for index, grid in enumerate(accent_grid)
        )
    phrase.sort(key=lambda item: (item[0], item[1]))
    kit = {
        "kick": kick,
        "snare": snare,
        "hat": hat,
        "open_hat": open_hat,
        "toms": toms,
        "swing": swing,
    }
    # Replace several hats with open hats while retaining 24 hits per bar.
    for bar_index in range(bar_count):
        target = bar_index * 24 + 15
        onset, _pitch = phrase[target]
        phrase[target] = (onset, open_hat)
    phrase.sort(key=lambda item: (item[0], item[1]))
    return phrase, kit


def _allowed_extra_count(note_count: int) -> int:
    count = 0
    while count + 1 <= math.floor((note_count + count + 1) * 0.10):
        count += 1
    return count


def _intervened_pattern(
    base: list[tuple[float, int]],
    condition: str,
    occurrence_index: int,
    rng: random.Random,
    phrase_beats: float,
) -> tuple[list[tuple[float, int]], dict]:
    pattern = list(base)
    details: dict = {"edited_hits": 0, "edit_fraction": 0.0}
    if occurrence_index == 0:
        return pattern, details
    if condition in {"timing_inside_tolerance", "timing_outside_tolerance"}:
        outside = condition == "timing_outside_tolerance"
        changed = []
        for onset, pitch in pattern:
            if outside:
                magnitude = rng.uniform(0.105, 0.15)
                offset = magnitude if rng.random() < 0.5 else -magnitude
            else:
                offset = rng.uniform(-0.05, 0.05)
            shifted = min(phrase_beats - 1e-6, max(0.0, onset + offset))
            changed.append((shifted, pitch))
        details = {
            "edited_hits": len(pattern),
            "edit_fraction": 1.0,
            "maximum_absolute_timing_edit_beats": 0.15 if outside else 0.05,
        }
        return sorted(changed), details
    if condition in {"missing_at_tolerance", "missing_beyond_tolerance"}:
        allowed = math.floor(len(pattern) * 0.10)
        count = allowed + (condition == "missing_beyond_tolerance")
        removed = set(rng.sample(range(len(pattern)), count))
        pattern = [hit for index, hit in enumerate(pattern) if index not in removed]
        details = {"edited_hits": count, "edit_fraction": count / len(base)}
    elif condition in {"extra_at_tolerance", "extra_beyond_tolerance"}:
        allowed = _allowed_extra_count(len(pattern))
        count = allowed + (condition == "extra_beyond_tolerance")
        pitches = [pitch for _onset, pitch in pattern]
        for index in range(count):
            onset = ((index + 1) / (count + 1) * phrase_beats + rng.uniform(0.011, 0.029)) % phrase_beats
            pattern.append((onset, rng.choice(pitches)))
        pattern.sort()
        details = {"edited_hits": count, "edit_fraction": count / len(pattern)}
    return pattern, details


def _context_pattern(
    rng: random.Random, bar_index: int, bar_beats: float
) -> list[tuple[float, int]]:
    pitches = (36, 38, 42, 45, 47, 50)
    hits = []
    for index in range(10):
        fraction = (index + 0.17 + rng.uniform(-0.07, 0.07)) / 10
        onset = bar_index * bar_beats + fraction * bar_beats
        pitch = pitches[(index * 3 + bar_index + rng.randrange(len(pitches))) % len(pitches)]
        hits.append((onset, pitch))
    return hits


def _to_notes(
    hits: Iterable[tuple[float, int]], ppq: int, rng: random.Random
) -> list[Note]:
    notes = []
    for onset, pitch in hits:
        start = round(onset * ppq)
        duration = max(1, round(rng.uniform(0.035, 0.11) * ppq))
        notes.append(Note(start, start + duration, pitch, rng.randint(58, 116)))
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.end, note.velocity))


def _arrangement_signatures(song: MidiSong) -> tuple[str, str]:
    exact = {
        "ppq": song.ticks_per_beat,
        "meters": song.meters,
        "parts": [
            {
                "index": part.index,
                "track": part.track,
                "program": part.program,
                "notes": [
                    (note.start, note.end, note.pitch, note.velocity)
                    for note in part.notes
                ],
            }
            for part in song.parts
        ],
    }
    ensemble = drum_part(song)
    normalized = {
        "meters": [
            (round(tick * 96 / song.ticks_per_beat), numerator, denominator)
            for tick, numerator, denominator in song.meters
        ],
        "notes": [
            (
                round(note.start * 96 / song.ticks_per_beat),
                round((note.end - note.start) * 96 / song.ticks_per_beat),
                note.pitch,
            )
            for note in ensemble.notes
        ],
    }
    return _canonical_hash(exact), _canonical_hash(normalized)


def _make_case(
    split: str,
    condition: str,
    design_index: int,
    attempt: int,
) -> StressCase:
    rng_seed = _seed(split, condition, design_index, attempt)
    rng = random.Random(rng_seed)
    ppq = (240, 480, 960)[(design_index + attempt) % 3]
    numerator = (3, 4, 5)[(design_index // 3 + attempt) % 3]
    denominator = 4
    bar_beats = float(numerator)
    bar_ticks = numerator * ppq
    target_bars = (1, 2, 4)[design_index % 3]
    occurrence_count = 3 + design_index % 3
    phrase_beats = target_bars * bar_beats
    syncopated = condition == "syncopated_simultaneous"
    base, kit = _phrase_pattern(
        rng, target_bars, bar_beats, strongly_syncopated=syncopated
    )
    phrase_design_sha256 = _canonical_hash(
        [(round(onset * 96), pitch) for onset, pitch in base]
    )
    positive = condition not in NEGATIVE_CONDITIONS
    pickup = bar_beats / 4 if condition == "pickup_bar_origin_mismatch" else 0.0
    cursor_bar = 3
    regions: list[tuple[float, float]] = []
    truth: list[tuple[int, int]] = []
    planted_hits: list[tuple[float, int]] = []
    intervention_observations = []
    for occurrence_index in range(occurrence_count):
        start_beat = cursor_bar * bar_beats + pickup
        if condition == "independent_patterns_negative":
            current, _kit = _phrase_pattern(
                rng, target_bars, bar_beats, strongly_syncopated=bool(occurrence_index % 2)
            )
            details = {"edited_hits": len(current), "edit_fraction": 1.0}
        elif condition == "shuffled_instrument_rhythm_negative":
            onsets = [onset for onset, _pitch in base]
            pitches = [pitch for _onset, pitch in base]
            rng.shuffle(pitches)
            current = sorted(zip(onsets, pitches))
            details = {"edited_hits": len(current), "edit_fraction": 1.0}
        else:
            current, details = _intervened_pattern(
                base, condition, occurrence_index, rng, phrase_beats
            )
        planted_hits.extend((start_beat + onset, pitch) for onset, pitch in current)
        regions.append((start_beat, start_beat + phrase_beats))
        if positive:
            start_tick = round(start_beat * ppq)
            truth.append((start_tick, start_tick + target_bars * bar_ticks))
        intervention_observations.append(details)
        cursor_bar += target_bars + 3 + occurrence_index % 2
    total_bars = cursor_bar + 3
    context_hits = []
    for bar_index in range(total_bars):
        bar_start = bar_index * bar_beats
        bar_end = bar_start + bar_beats
        if any(bar_start < end and bar_end > start for start, end in regions):
            continue
        context_hits.extend(_context_pattern(rng, bar_index, bar_beats))
    all_notes = _to_notes(planted_hits + context_hits, ppq, rng)

    if condition == "multitrack_merged":
        buckets = [[], [], []]
        for index, note in enumerate(all_notes):
            buckets[index % 3].append(note)
            if index % 17 == 0:
                buckets[(index + 1) % 3].append(
                    Note(note.start, note.end + 1, note.pitch, min(127, note.velocity + 3))
                )
        parts = [
            Part(index, index, 9, index * 8, f"kit {index}", True, sorted(notes, key=lambda note: (note.start, note.pitch)))
            for index, notes in enumerate(buckets)
        ]
    else:
        parts = [Part(0, 0, 9, 0, "stress kit", True, all_notes)]
    song = MidiSong(ppq, parts, [(0, 500_000)], [(0, numerator, denominator)], [])
    exact_signature, beat_signature = _arrangement_signatures(song)
    edited = [item for item in intervention_observations[1:] if item["edited_hits"]]
    intervention = {
        "name": condition,
        "base_phrase_hits": len(base),
        "edited_occurrences": len(edited),
        "edited_hits_min": min((item["edited_hits"] for item in edited), default=0),
        "edited_hits_max": max((item["edited_hits"] for item in edited), default=0),
        "edit_fraction_min": min((item["edit_fraction"] for item in edited), default=0.0),
        "edit_fraction_max": max((item["edit_fraction"] for item in edited), default=0.0),
        "configured_timing_tolerance_beats": 1 / 12,
        "timing_edit_bound_beats": (
            0.05
            if condition == "timing_inside_tolerance"
            else 0.15 if condition == "timing_outside_tolerance" else 0.0
        ),
        "pickup_offset_beats": pickup,
        "kit": kit,
    }
    return StressCase(
        case_id=f"{split}-{condition}-{design_index:03d}",
        split=split,
        condition=condition,
        design_index=design_index,
        attempt=attempt,
        rng_seed=rng_seed,
        song=song,
        truth_intervals=tuple(truth),
        target_bar_count=target_bars,
        occurrence_count=occurrence_count,
        positive=positive,
        diagnostic_expected_failure=condition in DIAGNOSTIC_FAILURE_CONDITIONS,
        intervention=intervention,
        phrase_design_sha256=phrase_design_sha256,
        exact_arrangement_sha256=exact_signature,
        beat_arrangement_sha256=beat_signature,
    )


def generate_cohort(cases_per_condition: int = 40) -> tuple[list[StressCase], dict]:
    if (
        isinstance(cases_per_condition, bool)
        or not isinstance(cases_per_condition, int)
        or cases_per_condition < 40
        or cases_per_condition % 2
    ):
        raise ValueError("cases_per_condition must be an even integer of at least 40")
    per_split = cases_per_condition // 2
    cases: list[StressCase] = []
    exact_seen: set[str] = set()
    beat_seen: set[str] = set()
    designs_seen: dict[str, set[str]] = {condition: set() for condition in CONDITIONS}
    rejected = {
        split: {
            condition: {"phrase_design": 0, "exact_arrangement": 0, "beat_arrangement": 0}
            for condition in CONDITIONS
        }
        for split in ("development", "test")
    }
    for split in ("development", "test"):
        for condition in CONDITIONS:
            for local_index in range(per_split):
                design_index = local_index + (0 if split == "development" else per_split)
                accepted = None
                for attempt in range(100):
                    candidate = _make_case(split, condition, design_index, attempt)
                    reasons = []
                    if candidate.phrase_design_sha256 in designs_seen[condition]:
                        reasons.append("phrase_design")
                    if candidate.exact_arrangement_sha256 in exact_seen:
                        reasons.append("exact_arrangement")
                    if candidate.beat_arrangement_sha256 in beat_seen:
                        reasons.append("beat_arrangement")
                    if not reasons:
                        accepted = candidate
                        break
                    for reason in reasons:
                        rejected[split][condition][reason] += 1
                if accepted is None:
                    raise RuntimeError(
                        f"could not generate unique {split} {condition} design {design_index}"
                    )
                cases.append(accepted)
                designs_seen[condition].add(accepted.phrase_design_sha256)
                exact_seen.add(accepted.exact_arrangement_sha256)
                beat_seen.add(accepted.beat_arrangement_sha256)
    development_exact = {
        case.exact_arrangement_sha256 for case in cases if case.split == "development"
    }
    test_exact = {
        case.exact_arrangement_sha256 for case in cases if case.split == "test"
    }
    development_beat = {
        case.beat_arrangement_sha256 for case in cases if case.split == "development"
    }
    test_beat = {
        case.beat_arrangement_sha256 for case in cases if case.split == "test"
    }
    audit = {
        "cases": len(cases),
        "exact_unique_arrangements": len(exact_seen),
        "beat_unique_arrangements": len(beat_seen),
        "distinct_phrase_designs_per_condition": {
            condition: len(designs_seen[condition]) for condition in CONDITIONS
        },
        "rejected_duplicates": rejected,
        "rejected_duplicate_attempts": sum(
            count
            for split in rejected.values()
            for condition in split.values()
            for count in condition.values()
        ),
        "rejected_duplicate_attempts_by_reason": {
            reason: sum(
                condition[reason]
                for split in rejected.values()
                for condition in split.values()
            )
            for reason in ("phrase_design", "exact_arrangement", "beat_arrangement")
        },
        "cross_split_exact_overlap": len(development_exact & test_exact),
        "cross_split_beat_overlap": len(development_beat & test_beat),
    }
    return cases, audit


def _nested_legitimate(case: StressCase, phrase: dict) -> bool:
    if not case.positive or phrase.get("bar_count", 0) >= case.target_bar_count:
        return False
    intervals = [
        (item["start_tick"], item["end_tick"])
        for item in phrase.get("occurrences", [])
    ]
    return bool(intervals) and all(
        any(start >= left and end <= right for left, right in case.truth_intervals)
        for start, end in intervals
    )


def score_case(case: StressCase, phrases: list[dict], stats: dict, elapsed: float) -> dict:
    candidates = []
    target_rank = None
    target_matches: list[tuple[int, int, float]] = []
    all_intervals = []
    for rank, phrase in enumerate(phrases, 1):
        intervals = [
            (item["start_tick"], item["end_tick"])
            for item in phrase["occurrences"]
        ]
        matches = one_to_one_matches(intervals, case.truth_intervals, IOU_THRESHOLD)
        target = bool(case.truth_intervals) and (
            phrase["bar_count"] == case.target_bar_count
            and len(matches) == len(case.truth_intervals)
            and len(intervals) == len(case.truth_intervals)
        )
        if target and target_rank is None:
            target_rank = rank
            target_matches = matches
        nested = _nested_legitimate(case, phrase)
        candidates.append(
            {
                "rank": rank,
                "family_id": phrase["family_id"],
                "bar_count": phrase["bar_count"],
                "occurrence_count": len(intervals),
                "intervals": [list(interval) for interval in intervals],
                "target_family": target,
                "nested_legitimate_pattern": nested,
            }
        )
        all_intervals.extend(intervals)
    all_matches = one_to_one_matches(all_intervals, case.truth_intervals, IOU_THRESHOLD)
    return {
        "case_id": case.case_id,
        "split": case.split,
        "condition": case.condition,
        "positive": case.positive,
        "diagnostic_expected_failure": case.diagnostic_expected_failure,
        "target_recovered": target_rank is not None,
        "target_rank": target_rank,
        "target_occurrence_tp": len(target_matches),
        "target_occurrence_fp": (
            candidates[target_rank - 1]["occurrence_count"] - len(target_matches)
            if target_rank is not None
            else 0
        ),
        "target_occurrence_fn": len(case.truth_intervals) - len(target_matches),
        "all_returned_occurrences": len(all_intervals),
        "all_output_truth_aligned_occurrences": len(all_matches),
        "non_target_returned_occurrences": len(all_intervals) - len(all_matches),
        "nested_legitimate_families": sum(
            candidate["nested_legitimate_pattern"] for candidate in candidates
        ),
        "negative_case_with_output": not case.positive and bool(candidates),
        "elapsed_seconds": round(elapsed, 8),
        "resource": {
            key: stats.get(key)
            for key in (
                "search_limited",
                "window_limit_reached",
                "comparison_limit_reached",
                "hit_limit_reached",
                "candidate_limit_reached",
                "saturated_seed_buckets",
                "oversized_windows",
                "window_attempts",
                "comparisons",
            )
        },
        "candidates": candidates,
    }


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
    }


def aggregate_results(rows: list[dict]) -> dict:
    positive = [row for row in rows if row["positive"]]
    negative = [row for row in rows if not row["positive"]]
    exact_controls = [
        row
        for row in positive
        if row["condition"] in EXACT_IDENTITY_CONTROL_CONDITIONS
    ]
    tolerant_controls = [
        row
        for row in positive
        if row["condition"] in TOLERANT_SUPPORTED_CONTROL_CONDITIONS
    ]
    diagnostic = [row for row in positive if row["diagnostic_expected_failure"]]
    negative_outputs = sum(row["negative_case_with_output"] for row in negative)
    target_occurrence = _prf(
        sum(row["target_occurrence_tp"] for row in rows),
        sum(row["target_occurrence_fp"] for row in rows),
        sum(row["target_occurrence_fn"] for row in rows),
    )
    all_output_tp = sum(row["all_output_truth_aligned_occurrences"] for row in rows)
    all_output_count = sum(row["all_returned_occurrences"] for row in rows)
    by_condition = {}
    for condition in CONDITIONS:
        selected = [row for row in rows if row["condition"] == condition]
        if selected:
            by_condition[condition] = {
                "cases": len(selected),
                "positive_cases": sum(row["positive"] for row in selected),
                "negative_cases": sum(not row["positive"] for row in selected),
                "target_recovered_cases": sum(row["target_recovered"] for row in selected),
                "top1_target_cases": sum(row["target_rank"] == 1 for row in selected),
                "negative_cases_with_output": sum(
                    row["negative_case_with_output"] for row in selected
                ),
                "nested_legitimate_families": sum(
                    row["nested_legitimate_families"] for row in selected
                ),
                "non_target_returned_occurrences": sum(
                    row["non_target_returned_occurrences"] for row in selected
                ),
            }
    wilson = wilson_interval(negative_outputs, len(negative))
    elapsed = [row["elapsed_seconds"] for row in rows]
    return {
        "cases": len(rows),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "target_recovered_cases": sum(row["target_recovered"] for row in positive),
        "target_recovery_rate": _ratio(
            sum(row["target_recovered"] for row in positive), len(positive)
        ),
        "exact_identity_control_cases": len(exact_controls),
        "exact_identity_control_recovered": sum(
            row["target_recovered"] for row in exact_controls
        ),
        "exact_identity_control_recovery_rate": _ratio(
            sum(row["target_recovered"] for row in exact_controls),
            len(exact_controls),
        ),
        "tolerant_supported_control_cases": len(tolerant_controls),
        "tolerant_supported_control_recovered": sum(
            row["target_recovered"] for row in tolerant_controls
        ),
        "tolerant_supported_control_recovery_rate": _ratio(
            sum(row["target_recovered"] for row in tolerant_controls),
            len(tolerant_controls),
        ),
        "out_of_range_or_pickup_diagnostic_cases": len(diagnostic),
        "out_of_range_or_pickup_diagnostic_recovered": sum(
            row["target_recovered"] for row in diagnostic
        ),
        "top1_target_rate": _ratio(
            sum(row["target_rank"] == 1 for row in positive), len(positive)
        ),
        "target_occurrence": target_occurrence,
        "all_output_occurrence_alignment_precision": _ratio(
            all_output_tp, all_output_count
        ),
        "all_returned_occurrences": all_output_count,
        "non_target_returned_occurrences": sum(
            row["non_target_returned_occurrences"] for row in rows
        ),
        "nested_legitimate_families": sum(
            row["nested_legitimate_families"] for row in rows
        ),
        "non_target_interpretation": (
            "not automatically false musical repetitions; includes nested legitimate "
            "patterns and any recurrence outside the planted target annotation"
        ),
        "negative_cases_with_output": negative_outputs,
        "negative_case_denominator": len(negative),
        "negative_case_output_rate": _ratio(negative_outputs, len(negative)),
        "negative_case_output_wilson_95": wilson,
        "zero_negative_output_upper_95": (
            wilson[1] if wilson and negative_outputs == 0 else None
        ),
        "search_limited_cases": sum(bool(row["resource"]["search_limited"]) for row in rows),
        "resource_maximums": {
            "window_attempts": max(
                (row["resource"]["window_attempts"] or 0 for row in rows), default=0
            ),
            "comparisons": max(
                (row["resource"]["comparisons"] or 0 for row in rows), default=0
            ),
        },
        "runtime_seconds": {
            "total": sum(elapsed),
            "mean": statistics.mean(elapsed) if elapsed else 0.0,
            "maximum": max(elapsed, default=0.0),
        },
        "by_condition": by_condition,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_stress(
    output: Path,
    *,
    cases_per_condition: int = 40,
) -> dict:
    cases, uniqueness = generate_cohort(cases_per_condition)
    design = frozen_design(cases_per_condition)
    case_manifest = [case.metadata() for case in cases]
    frozen = {
        "design": design,
        "design_sha256": _canonical_hash(design),
        "cohort_sha256": _canonical_hash(case_manifest),
        "uniqueness_audit": uniqueness,
        "cases": case_manifest,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config={
            "cases_per_condition": cases_per_condition,
            "methods": list(METHODS),
            "detector_configs": design["detector_configs"],
        },
        cases=case_manifest,
        required_files=(
            "samuged/drum_stress.py",
            "samuged/drums.py",
            "samuged/evaluate_drums.py",
            "samuged/experiment.py",
            "samuged/__init__.py",
            "samuged/metadata_recovery.py",
            "samuged/midi.py",
            "pyproject.toml",
            "requirements-research.lock",
        ),
    )
    output = output.resolve()
    links = receipt_links(receipt)
    frozen.update(links)
    # Written before detector execution so detector outcomes cannot alter cohort design.
    _write_json(output / "design.json", frozen)

    rows_by_method = {}
    for method in METHODS:
        config = DrumConfig(mode=method)
        rows = []
        for case in cases:
            started = time.monotonic()
            result = extract_drums(case.song, config)
            rows.append(
                score_case(
                    case,
                    result["phrases"],
                    result["stats"],
                    time.monotonic() - started,
                )
            )
        rows_by_method[method] = rows

    methods = {}
    for method in METHODS:
        combined = aggregate_results(rows_by_method[method])
        combined["by_split"] = {
            split: aggregate_results(
                [row for row in rows_by_method[method] if row["split"] == split]
            )
            for split in ("development", "test")
        }
        methods[method] = combined
    aggregate = {
        "stress_version": STRESS_VERSION,
        **links,
        "design_sha256": frozen["design_sha256"],
        "cohort_sha256": frozen["cohort_sha256"],
        "case_count": len(cases),
        "uniqueness_audit": uniqueness,
        "methods": methods,
        "claim_boundary": design["claim_boundary"],
    }
    raw = {
        "stress_version": STRESS_VERSION,
        **links,
        "design_sha256": frozen["design_sha256"],
        "cohort_sha256": frozen["cohort_sha256"],
        "cases": [
            {
                **case.metadata(),
                "methods": {
                    method: rows_by_method[method][index] for method in METHODS
                },
            }
            for index, case in enumerate(cases)
        ],
    }
    _write_json(output / "raw_results.json", raw)
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases-per-condition", type=int, default=40)
    args = parser.parse_args(argv)
    result = run_stress(
        args.output,
        cases_per_condition=args.cases_per_condition,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
