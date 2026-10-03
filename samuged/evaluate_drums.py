"""Controlled evaluation of symbolic recurring drum pattern extraction.

The benchmark measures planted recurrence and rejection of controlled symbolic
negatives. It does not measure musical quality, listener response or catchiness.
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

from .drums import DrumConfig, extract_drums
from .experiment import complete_experiment, prepare_experiment, receipt_links
from .midi import MidiSong, Note, Part


BENCHMARK_VERSION = "planted-drums-v1"
IOU_THRESHOLD = 0.9
METHODS = ("exact", "tolerant")
CASE_KINDS = (
    "exact_1bar",
    "exact_2bar",
    "exact_4bar",
    "timing_jitter",
    "missing_strike",
    "extra_strike",
    "changed_instrument_negative",
    "shuffled_rhythm_negative",
    "independent_rhythm_negative",
    "simultaneous_hits",
    "meter_change",
    "ppq_variation",
)
NEGATIVE_KINDS = frozenset(
    {
        "changed_instrument_negative",
        "shuffled_rhythm_negative",
        "independent_rhythm_negative",
    }
)
_SEED_NAMESPACES = {
    "development": "samuged-drums-development-v1",
    "test": "samuged-drums-test-v1",
}


@dataclass(frozen=True)
class DrumBenchmarkCase:
    case_id: str
    split: str
    kind: str
    rng_seed: int
    song: MidiSong
    truth_intervals: tuple[tuple[int, int], ...]
    target_bar_count: int
    positive: bool

    def metadata(self) -> dict:
        symbolic_payload = {
            "ticks_per_beat": self.song.ticks_per_beat,
            "meters": self.song.meters,
            "notes": [
                (note.start, note.end, note.pitch, note.velocity)
                for part in self.song.parts
                for note in part.notes
            ],
        }
        return {
            "case_id": self.case_id,
            "split": self.split,
            "kind": self.kind,
            "rng_seed": self.rng_seed,
            "positive": self.positive,
            "target_bar_count": self.target_bar_count,
            "ticks_per_beat": self.song.ticks_per_beat,
            "meters": [list(change) for change in self.song.meters],
            "symbolic_sha256": sha256(
                json.dumps(symbolic_payload, separators=(",", ":")).encode()
            ).hexdigest(),
            "truth_intervals": [list(interval) for interval in self.truth_intervals],
            "note_count": sum(len(part.notes) for part in self.song.parts),
        }


def benchmark_design() -> dict:
    """Return the frozen benchmark contract stored with every run."""

    return {
        "version": BENCHMARK_VERSION,
        "case_kinds": list(CASE_KINDS),
        "negative_kinds": sorted(NEGATIVE_KINDS),
        "methods": list(METHODS),
        "seed_namespaces": dict(_SEED_NAMESPACES),
        "iou_threshold": IOU_THRESHOLD,
        "truth_definition": (
            "whole planted bar intervals computed from generator meter and PPQ, "
            "independently of detector notes or output"
        ),
        "candidate_definition": (
            "a recovered family has the planted bar count and exactly one predicted "
            "occurrence matched to each truth interval at temporal IoU >= 0.9"
        ),
        "occurrence_definition": (
            "maximum-cardinality one-to-one interval assignment at temporal IoU >= 0.9"
        ),
        "primitive_policy": (
            "shorter recurring bars inside planted two- or four-bar phrases are reported "
            "as primitive subpatterns, not target recovery; strict precision still counts "
            "all non-target returned families"
        ),
        "detector_configs": {
            "exact": asdict(DrumConfig(mode="exact")),
            "tolerant": asdict(DrumConfig(mode="tolerant")),
        },
        "case_schedule": (
            "half development and half test; each split round-robins frozen case kinds"
        ),
        "generator_parameters": {
            "planted_copies": 2,
            "bar_counts": [1, 2, 4],
            "base_hits_per_bar": 12,
            "ppq_values": [96, 240, 480, 960],
            "meters": [[4, 4], [3, 4], [5, 4]],
            "timing_jitter_beats": [-1 / 24, 1 / 24],
            "swing_fraction_of_eighth_step": [-0.12, 0.12],
            "kit_choices": {
                "kick": [35, 36],
                "snare": [38, 40],
                "closed_hat": [42, 44],
                "open_hat": [46, 49],
            },
            "edited_strikes": 1,
            "changed_instrument_strikes": 3,
        },
        "uncertainty": (
            "95 percent percentile bootstrap stratified by positive and negative cases; "
            "Wilson score interval for negative-case false-positive rate"
        ),
        "claim_boundary": (
            "controlled symbolic recurrence only; real-corpus quality and musical "
            "catchiness are not evaluated"
        ),
    }


def _seed(split: str, local_index: int) -> int:
    payload = f"{_SEED_NAMESPACES[split]}:{local_index}".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def _bar_pattern(
    bar_beats: float,
    variant: int,
    kit: tuple[int, int, int, int],
    swing: float,
    simultaneous: bool = False,
) -> list[tuple[float, int]]:
    fractions = [0, 0, 1, 2, 2, 3, 4, 4, 5, 6, 6, 7]
    kick, snare, closed_hat, open_hat = kit
    pitches = [
        kick,
        closed_hat,
        closed_hat,
        snare,
        closed_hat,
        closed_hat,
        kick,
        closed_hat,
        open_hat,
        snare,
        closed_hat,
        closed_hat,
    ]
    scale = bar_beats / 8
    hits = [
        (fraction * scale + (swing * scale if fraction % 2 else 0), pitch)
        for fraction, pitch in zip(fractions, pitches)
    ]
    if variant == 1:
        hits[6] = (4.5 * scale, hits[6][1])
        hits[8] = (hits[8][0], 45)
    elif variant == 2:
        hits[2] = (1.5 * scale, hits[2][1])
        hits[5] = (3.5 * scale, hits[5][1])
        hits[8] = (hits[8][0], 47)
    elif variant == 3:
        hits[3] = (2.5 * scale, hits[3][1])
        hits[6] = (5 * scale, hits[6][1])
        hits[8] = (hits[8][0], 50)
    if simultaneous:
        hits[2] = (0, 49)
        hits[5] = (2 * scale, 51)
        hits[8] = (4 * scale, 45)
    return hits


def _notes(
    pattern: Iterable[tuple[float, int]],
    *,
    origin_tick: int,
    ppq: int,
    rng: random.Random,
    jitter: bool = False,
) -> list[Note]:
    notes = []
    for onset, pitch in pattern:
        offset = rng.uniform(-1 / 24, 1 / 24) if jitter and onset > 0 else 0.0
        start = origin_tick + round((onset + offset) * ppq)
        duration = max(1, round((0.06 + (pitch % 3) * 0.01) * ppq))
        notes.append(Note(start, start + duration, pitch, 76 + pitch % 35))
    return notes


def _build_case(kind: str, split: str, local_index: int) -> DrumBenchmarkCase:
    rng_seed = _seed(split, local_index)
    rng = random.Random(rng_seed)
    if kind == "ppq_variation":
        occurrence_index = local_index // len(CASE_KINDS)
        ppq = (96, 240, 480, 960)[occurrence_index % 4]
    else:
        ppq = 480
    positive = kind not in NEGATIVE_KINDS
    target_bars = {"exact_2bar": 2, "exact_4bar": 4}.get(kind, 1)
    meter = (4, 4)
    origin = 0
    meters = [(0, *meter)]
    if kind == "meter_change":
        origin = 6 * ppq
        meter = (5, 4)
        meters = [(0, 3, 4), (origin, *meter)]
    bar_beats = meter[0] * 4 / meter[1]
    bar_ticks = round(bar_beats * ppq)

    simultaneous = kind == "simultaneous_hits"
    kit = (
        rng.choice((35, 36)),
        rng.choice((38, 40)),
        rng.choice((42, 44)),
        rng.choice((46, 49)),
    )
    swing = rng.uniform(-0.12, 0.12)
    first_patterns = [
        _bar_pattern(bar_beats, bar_index, kit, swing, simultaneous)
        for bar_index in range(target_bars)
    ]
    second_patterns = [list(pattern) for pattern in first_patterns]

    if kind == "timing_jitter":
        second_jitter = True
    else:
        second_jitter = False
    if kind == "missing_strike":
        del second_patterns[0][5]
    elif kind == "extra_strike":
        second_patterns[0].append((bar_beats * 0.81, 42))
        second_patterns[0].sort()
    elif kind == "changed_instrument_negative":
        for index in (0, 3, 6):
            onset, pitch = second_patterns[0][index]
            second_patterns[0][index] = (onset, pitch + 1)
    elif kind == "shuffled_rhythm_negative":
        onsets = [onset for onset, _pitch in second_patterns[0]]
        pitches = [pitch for _onset, pitch in second_patterns[0]]
        rotated_onsets = onsets[4:] + onsets[:4]
        second_patterns[0] = sorted(zip(rotated_onsets, pitches))
    elif kind == "independent_rhythm_negative":
        pitches = [pitch for _onset, pitch in second_patterns[0]]
        fractions = (0, 0.08, 0.19, 0.31, 0.37, 0.49, 0.58, 0.66, 0.73, 0.84, 0.91, 0.96)
        second_patterns[0] = [(fraction * bar_beats, pitch) for fraction, pitch in zip(fractions, pitches)]

    all_notes: list[Note] = []
    copy_starts = (origin, origin + target_bars * bar_ticks)
    for copy_index, copy_start in enumerate(copy_starts):
        patterns = first_patterns if copy_index == 0 else second_patterns
        for bar_index, pattern in enumerate(patterns):
            all_notes.extend(
                _notes(
                    pattern,
                    origin_tick=copy_start + bar_index * bar_ticks,
                    ppq=ppq,
                    rng=rng,
                    jitter=copy_index == 1 and second_jitter,
                )
            )
    all_notes.sort(key=lambda note: (note.start, note.pitch, note.end, note.velocity))
    song = MidiSong(
        ppq,
        [Part(0, 0, 9, 0, "planted kit", True, all_notes)],
        [(0, 500_000)],
        meters,
        [],
    )
    truth = (
        tuple((start, start + target_bars * bar_ticks) for start in copy_starts)
        if positive
        else ()
    )
    return DrumBenchmarkCase(
        case_id=f"{split}-{local_index:05d}-{kind}",
        split=split,
        kind=kind,
        rng_seed=rng_seed,
        song=song,
        truth_intervals=truth,
        target_bar_count=target_bars,
        positive=positive,
    )


def generate_cases(count: int = 1000) -> list[DrumBenchmarkCase]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("case count must be a positive integer")
    development_count = (count + 1) // 2
    split_counts = {
        "development": development_count,
        "test": count - development_count,
    }
    cases = []
    for split in ("development", "test"):
        for local_index in range(split_counts[split]):
            kind = CASE_KINDS[local_index % len(CASE_KINDS)]
            cases.append(_build_case(kind, split, local_index))
    return cases


def arrangement_overlap_audit(case_rows: Iterable[dict]) -> dict:
    """Audit exact generated-arrangement overlap without rerunning detection.

    ``symbolic_sha256`` includes PPQ, meter events and exact note timing, pitch,
    duration and velocity. It is stricter than perceptual musical equivalence,
    so this audit can undercount near-duplicate grooves.
    """

    rows = list(case_rows)
    required = ("case_id", "split", "kind", "rng_seed", "symbolic_sha256")
    for row in rows:
        if any(key not in row for key in required):
            raise ValueError("case rows lack arrangement audit metadata")
        if row["split"] not in {"development", "test"}:
            raise ValueError("arrangement audit supports development and test splits")

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["symbolic_sha256"], []).append(row)
    cross_groups = {
        signature: group
        for signature, group in groups.items()
        if {row["split"] for row in group} == {"development", "test"}
    }

    split_summary = {}
    for split in ("development", "test"):
        selected = [row for row in rows if row["split"] == split]
        signatures = [row["symbolic_sha256"] for row in selected]
        unique = set(signatures)
        cross_cases = [row for row in selected if row["symbolic_sha256"] in cross_groups]
        split_summary[split] = {
            "cases": len(selected),
            "unique_arrangements": len(unique),
            "duplicate_case_excess": len(selected) - len(unique),
            "cross_split_overlap_cases": len(cross_cases),
            "cross_split_overlap_case_rate": _ratio(len(cross_cases), len(selected)),
            "cases_with_signature_absent_from_other_split": len(selected) - len(cross_cases),
            "unique_signatures_absent_from_other_split": len(
                unique - {
                    row["symbolic_sha256"]
                    for row in rows
                    if row["split"] != split
                }
            ),
        }

    per_condition = {}
    for kind in sorted({row["kind"] for row in rows}):
        selected = [row for row in rows if row["kind"] == kind]
        development = {
            row["symbolic_sha256"]
            for row in selected
            if row["split"] == "development"
        }
        test = {
            row["symbolic_sha256"]
            for row in selected
            if row["split"] == "test"
        }
        per_condition[kind] = {
            "cases": len(selected),
            "unique_arrangements": len({row["symbolic_sha256"] for row in selected}),
            "development_cases": sum(row["split"] == "development" for row in selected),
            "development_unique_arrangements": len(development),
            "test_cases": sum(row["split"] == "test" for row in selected),
            "test_unique_arrangements": len(test),
            "cross_split_shared_arrangements": len(development & test),
        }

    evidence = []
    for signature, group in sorted(cross_groups.items()):
        evidence.append(
            {
                "symbolic_sha256": signature,
                "cases": [
                    {
                        "case_id": row["case_id"],
                        "split": row["split"],
                        "kind": row["kind"],
                        "rng_seed": row["rng_seed"],
                    }
                    for row in sorted(group, key=lambda item: item["case_id"])
                ],
            }
        )

    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    development_seeds = {
        row["rng_seed"] for row in rows if row["split"] == "development"
    }
    test_seeds = {row["rng_seed"] for row in rows if row["split"] == "test"}
    return {
        "audit_version": "exact-symbolic-arrangement-overlap-v1",
        "signature_field": "symbolic_sha256",
        "signature_definition": (
            "SHA-256 over PPQ, meter events and exact note start, end, pitch and velocity"
        ),
        "signature_limit": (
            "exact symbolic equality only; perceptually equivalent or near-duplicate "
            "grooves can remain uncounted"
        ),
        "cases": len(rows),
        "unique_arrangements": len(groups),
        "duplicate_case_excess": len(rows) - len(groups),
        "duplicate_arrangement_groups": len(duplicate_groups),
        "maximum_group_size": max((len(group) for group in groups.values()), default=0),
        "rng_seed_overlap_count": len(development_seeds & test_seeds),
        "cross_split_shared_arrangements": len(cross_groups),
        "cross_split_overlap_cases": sum(len(group) for group in cross_groups.values()),
        "split": split_summary,
        "per_condition": per_condition,
        "cross_split_evidence": evidence,
        "interpretation": (
            "the RNG seed namespaces are disjoint, but finite generated kit and timing "
            "choices do not guarantee disjoint arrangements. The detector has no fitted "
            "parameters and the benchmark configurations were frozen, which limits model "
            "leakage, but the test split is not fully arrangement-independent. Duplicate "
            "cases reduce effective sample diversity and case bootstrap intervals treat "
            "repeated arrangements as independent observations."
        ),
    }


def temporal_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0 else 0.0


def one_to_one_matches(
    predicted: Iterable[tuple[int, int]],
    truth: Iterable[tuple[int, int]],
    threshold: float = IOU_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """Return a deterministic maximum-cardinality bipartite interval matching."""

    predicted = list(predicted)
    truth = list(truth)
    adjacency = []
    for interval in predicted:
        choices = [
            (temporal_iou(interval, target), target_index)
            for target_index, target in enumerate(truth)
            if temporal_iou(interval, target) >= threshold
        ]
        adjacency.append([index for _iou, index in sorted(choices, reverse=True)])
    truth_to_prediction: dict[int, int] = {}

    def assign(prediction_index: int, visited: set[int]) -> bool:
        for truth_index in adjacency[prediction_index]:
            if truth_index in visited:
                continue
            visited.add(truth_index)
            previous = truth_to_prediction.get(truth_index)
            if previous is None or assign(previous, visited):
                truth_to_prediction[truth_index] = prediction_index
                return True
        return False

    prediction_order = sorted(
        range(len(predicted)),
        key=lambda index: (-max((temporal_iou(predicted[index], item) for item in truth), default=0), index),
    )
    for prediction_index in prediction_order:
        assign(prediction_index, set())
    return sorted(
        (
            prediction_index,
            truth_index,
            temporal_iou(predicted[prediction_index], truth[truth_index]),
        )
        for truth_index, prediction_index in truth_to_prediction.items()
    )


def _is_primitive_subpattern(case: DrumBenchmarkCase, phrase: dict) -> bool:
    if not case.positive or phrase.get("bar_count", 0) >= case.target_bar_count:
        return False
    intervals = [
        (occurrence["start_tick"], occurrence["end_tick"])
        for occurrence in phrase.get("occurrences", [])
    ]
    return bool(intervals) and all(
        any(start >= left and end <= right for left, right in case.truth_intervals)
        for start, end in intervals
    )


def score_case(
    case: DrumBenchmarkCase,
    phrases: list[dict],
    stats: dict,
    elapsed_seconds: float,
) -> dict:
    candidates = []
    recovered_rank = None
    for rank, phrase in enumerate(phrases, 1):
        intervals = [
            (occurrence["start_tick"], occurrence["end_tick"])
            for occurrence in phrase["occurrences"]
        ]
        matches = one_to_one_matches(intervals, case.truth_intervals)
        correct = bool(case.truth_intervals) and (
            phrase.get("bar_count") == case.target_bar_count
            and len(matches) == len(case.truth_intervals)
            and len(intervals) == len(case.truth_intervals)
        )
        if correct and recovered_rank is None:
            recovered_rank = rank
        candidates.append(
            {
                "rank": rank,
                "family_id": phrase["family_id"],
                "bar_count": phrase["bar_count"],
                "recurrence_score": phrase["recurrence_score"],
                "intervals": [list(interval) for interval in intervals],
                "correct_family": correct,
                "primitive_subpattern": _is_primitive_subpattern(case, phrase),
                "truth_matches": [
                    [prediction, target, round(iou, 8)]
                    for prediction, target, iou in matches
                ],
            }
        )
    flattened = [
        tuple(interval)
        for candidate in candidates
        for interval in candidate["intervals"]
    ]
    occurrence_matches = one_to_one_matches(flattened, case.truth_intervals)
    candidate_tp = int(recovered_rank is not None)
    return {
        "case_id": case.case_id,
        "split": case.split,
        "kind": case.kind,
        "positive": case.positive,
        "target_bar_count": case.target_bar_count,
        "elapsed_seconds": round(elapsed_seconds, 8),
        "candidate_tp": candidate_tp,
        "candidate_fp": len(candidates) - candidate_tp,
        "candidate_fn": int(case.positive and not candidate_tp),
        "occurrence_tp": len(occurrence_matches),
        "occurrence_fp": len(flattened) - len(occurrence_matches),
        "occurrence_fn": len(case.truth_intervals) - len(occurrence_matches),
        "recovered": bool(candidate_tp),
        "recovery_rank": recovered_rank,
        "false_positive_case": not case.positive and bool(candidates),
        "primitive_subpattern_count": sum(
            candidate["primitive_subpattern"] for candidate in candidates
        ),
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
                "raw_candidate_count",
                "selected_count",
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


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> list[float] | None:
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    rate = successes / trials
    denominator = 1 + z * z / trials
    centre = (rate + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials)) / denominator
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    if abs(lower) < 1e-15:
        lower = 0.0
    if abs(1 - upper) < 1e-15:
        upper = 1.0
    return [lower, upper]


def aggregate_results(rows: list[dict]) -> dict:
    positive = [row for row in rows if row["positive"]]
    negative = [row for row in rows if not row["positive"]]
    false_positive_count = sum(row["false_positive_case"] for row in negative)
    elapsed = [row["elapsed_seconds"] for row in rows]
    by_kind = {}
    for kind in CASE_KINDS:
        selected = [row for row in rows if row["kind"] == kind]
        if selected:
            by_kind[kind] = {
                "cases": len(selected),
                "positive_cases": sum(row["positive"] for row in selected),
                "negative_cases": sum(not row["positive"] for row in selected),
                "recovered_cases": sum(row["recovered"] for row in selected),
                "false_positive_cases": sum(row["false_positive_case"] for row in selected),
                "primitive_subpattern_predictions": sum(
                    row["primitive_subpattern_count"] for row in selected
                ),
            }
    candidate = _prf(
        sum(row["candidate_tp"] for row in rows),
        sum(row["candidate_fp"] for row in rows),
        sum(row["candidate_fn"] for row in rows),
    )
    occurrence = _prf(
        sum(row["occurrence_tp"] for row in rows),
        sum(row["occurrence_fp"] for row in rows),
        sum(row["occurrence_fn"] for row in rows),
    )
    interval = wilson_interval(false_positive_count, len(negative))
    return {
        "cases": len(rows),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "candidate": candidate,
        "occurrence": occurrence,
        "recovered_positive_cases": sum(row["recovered"] for row in positive),
        "positive_recovery_rate": _ratio(sum(row["recovered"] for row in positive), len(positive)),
        "top1_recovery_rate": _ratio(sum(row["recovery_rank"] == 1 for row in positive), len(positive)),
        "false_positive_case_count": false_positive_count,
        "false_positive_case_denominator": len(negative),
        "false_positive_case_rate": _ratio(false_positive_count, len(negative)),
        "false_positive_rate_wilson_95": interval,
        "zero_false_positive_upper_95": interval[1] if interval and false_positive_count == 0 else None,
        "search_limited_cases": sum(bool(row["resource"]["search_limited"]) for row in rows),
        "resource_limit_counts": {
            key: sum(bool(row["resource"][key]) for row in rows)
            for key in (
                "window_limit_reached",
                "comparison_limit_reached",
                "hit_limit_reached",
                "candidate_limit_reached",
            )
        },
        "resource_diagnostics": {
            "saturated_seed_cases": sum(
                bool(row["resource"]["saturated_seed_buckets"]) for row in rows
            ),
            "saturated_seed_buckets": sum(
                row["resource"]["saturated_seed_buckets"] or 0 for row in rows
            ),
            "oversized_window_cases": sum(
                bool(row["resource"]["oversized_windows"]) for row in rows
            ),
            "oversized_windows": sum(
                row["resource"]["oversized_windows"] or 0 for row in rows
            ),
            "maximum_window_attempts": max(
                (row["resource"]["window_attempts"] or 0 for row in rows),
                default=0,
            ),
            "maximum_comparisons": max(
                (row["resource"]["comparisons"] or 0 for row in rows),
                default=0,
            ),
        },
        "primitive_subpattern_predictions": sum(row["primitive_subpattern_count"] for row in rows),
        "runtime_seconds": {
            "total": sum(elapsed),
            "mean": statistics.mean(elapsed) if elapsed else 0.0,
            "median": statistics.median(elapsed) if elapsed else 0.0,
            "maximum": max(elapsed, default=0.0),
        },
        "by_kind": by_kind,
    }


def bootstrap_intervals(rows: list[dict], iterations: int, seed: int) -> dict:
    if not rows or iterations < 1:
        return {}
    positive = [row for row in rows if row["positive"]]
    negative = [row for row in rows if not row["positive"]]
    rng = random.Random(seed)
    values = {
        name: []
        for name in (
            "candidate_f1",
            "occurrence_f1",
            "positive_recovery_rate",
            "false_positive_case_rate",
        )
    }
    for _ in range(iterations):
        sample = []
        if positive:
            sample.extend(positive[rng.randrange(len(positive))] for _ in positive)
        if negative:
            sample.extend(negative[rng.randrange(len(negative))] for _ in negative)
        aggregate = aggregate_results(sample)
        values["candidate_f1"].append(aggregate["candidate"]["f1"])
        values["occurrence_f1"].append(aggregate["occurrence"]["f1"])
        values["positive_recovery_rate"].append(aggregate["positive_recovery_rate"])
        values["false_positive_case_rate"].append(aggregate["false_positive_case_rate"])
    result = {}
    for name, samples in values.items():
        samples.sort()
        low = samples[math.floor(0.025 * (len(samples) - 1))]
        high = samples[math.ceil(0.975 * (len(samples) - 1))]
        result[name] = [low, high]
    return result


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_benchmark(
    output: Path,
    *,
    case_count: int = 1000,
    bootstrap_iterations: int = 1000,
) -> dict:
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    cases = generate_cases(case_count)
    design = benchmark_design()
    design_hash = sha256(
        json.dumps(design, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    run_parameters = {
        "case_count": case_count,
        "bootstrap_iterations": bootstrap_iterations,
    }
    detector_configs = {
        method: asdict(DrumConfig(mode=method)) for method in METHODS
    }
    output = output.resolve()
    receipt = prepare_experiment(
        output,
        design=design,
        config={"run_parameters": run_parameters, "detectors": detector_configs},
        cases=cases,
    )
    links = receipt_links(receipt)
    rows_by_method: dict[str, list[dict]] = {}
    for method in METHODS:
        config = DrumConfig(**detector_configs[method])
        method_rows = []
        for case in cases:
            started = time.monotonic()
            result = extract_drums(case.song, config)
            method_rows.append(
                score_case(case, result["phrases"], result["stats"], time.monotonic() - started)
            )
        rows_by_method[method] = method_rows

    methods = {}
    for method_index, method in enumerate(METHODS):
        rows = rows_by_method[method]
        combined = aggregate_results(rows)
        combined["bootstrap_ci95"] = bootstrap_intervals(
            rows, bootstrap_iterations, 91_000 + method_index
        )
        combined["by_split"] = {}
        for split_index, split in enumerate(("development", "test")):
            split_rows = [row for row in rows if row["split"] == split]
            split_aggregate = aggregate_results(split_rows)
            split_aggregate["bootstrap_ci95"] = bootstrap_intervals(
                split_rows,
                bootstrap_iterations,
                92_000 + method_index * 10 + split_index,
            )
            combined["by_split"][split] = split_aggregate
        methods[method] = combined

    raw = {
        "benchmark_version": BENCHMARK_VERSION,
        "design_sha256": design_hash,
        **links,
        "design": design,
        "run_parameters": run_parameters,
        "cases": [
            {
                **case.metadata(),
                "methods": {
                    method: rows_by_method[method][index]
                    for method in METHODS
                },
            }
            for index, case in enumerate(cases)
        ],
    }
    aggregate = {
        "benchmark_version": BENCHMARK_VERSION,
        "design_sha256": design_hash,
        **links,
        "case_count": len(cases),
        "split_counts": {
            split: sum(case.split == split for case in cases)
            for split in ("development", "test")
        },
        "run_parameters": run_parameters,
        "methods": methods,
        "claim_boundary": design["claim_boundary"],
        "supplementary_arrangement_overlap_audit": arrangement_overlap_audit(
            case.metadata() for case in cases
        ),
    }
    _write_json(output / "raw_results.json", raw)
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def audit_saved_run(output: Path) -> dict:
    """Append overlap evidence to an existing aggregate without rerunning cases."""

    output = output.resolve(strict=True)
    raw_path = output / "raw_results.json"
    aggregate_path = output / "aggregate.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    if raw.get("design_sha256") != aggregate.get("design_sha256"):
        raise ValueError("raw and aggregate design hashes disagree")
    audit = arrangement_overlap_audit(raw.get("cases", []))
    if (output / "completion_receipt.json").exists():
        from .experiment import verify_completed_experiment
        verify_completed_experiment(output)
        if aggregate.get("supplementary_arrangement_overlap_audit") != audit:
            raise ValueError("completed experiment is immutable; save a separate overlap audit")
        return audit
    aggregate["supplementary_arrangement_overlap_audit"] = audit
    _write_json(aggregate_path, aggregate)
    return audit


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=1000)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(argv)
    result = run_benchmark(
        args.output,
        case_count=args.cases,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
