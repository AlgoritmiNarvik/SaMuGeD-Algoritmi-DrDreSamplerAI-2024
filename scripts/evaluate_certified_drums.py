"""Evaluate drum extraction on oracle certified symbolic controls.

This study constructs a separate synthetic cohort. Negative cases are accepted
only after the independent drum oracle has exhausted every eligible one, two
and four bar pair without finding an admissible pair. Positive cases contain a
known repeated bar region and are retained only when the oracle confirms every
labelled target edge. The certification rule is deliberately symbolic and
does not establish real world specificity or musical quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import time

import mido

from samuged.drum_oracle import (
    BAR_COUNTS,
    HIT_ERROR_FRACTION,
    MIN_HITS,
    MIN_PITCHES,
    TIMING_TOLERANCE_BEATS,
    enumerate_admissible_pairs,
    enumerate_windows,
)
from samuged.drums import DrumConfig, extract_drums
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
)
from samuged.midi import MidiSong, Note, Part, load_midi


VERSION = "certified-drum-controls-v1"
NAMESPACE = "samuged-certified-drums-v1"
SPLITS = ("development", "test")
METERS = ((4, 4), (3, 4), (6, 8), (7, 8))
PPQS = (96, 480, 960)
MIN_BARS = 16
MAX_BARS = 32
NEGATIVE_CASES_PER_SPLIT = 120
POSITIVE_CASES_PER_SPLIT = 60
MAX_GENERATION_ATTEMPTS = 10_000
KIT_PITCHES = (35, 36, 38, 40, 41, 42, 43, 45, 46, 48, 49, 51)
SUBDIVISIONS_PER_BEAT = 4
DEFAULT_VELOCITY = 96


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _bar_ticks(ppq: int, numerator: int, denominator: int) -> int:
    value = Fraction(ppq * numerator * 4, denominator)
    if value.denominator != 1:
        raise ValueError("selected PPQ and meter must produce integral bar ticks")
    return value.numerator


def _slots(numerator: int, denominator: int) -> int:
    value = Fraction(numerator * 4 * SUBDIVISIONS_PER_BEAT, denominator)
    if value.denominator != 1:
        raise ValueError("meter does not produce integral generator slots")
    return value.numerator


def _make_bar(
    rng: random.Random,
    *,
    ppq: int,
    numerator: int,
    denominator: int,
    bar_index: int,
    pitch_bias: int = 0,
) -> list[tuple[int, int, int]]:
    """Create one deliberately varied kit bar as (slot, pitch, velocity)."""
    slots = _slots(numerator, denominator)
    # Keeping nearly every slot populated gives the oracle at least eight hits
    # while making one changed bar visible in two and four bar windows.
    count = slots - (rng.randrange(0, 3) if slots >= 10 else 0)
    selected = sorted(rng.sample(range(slots), count))
    pitches = [rng.choice(KIT_PITCHES) for _ in selected]
    if len(set(pitches)) < 3:
        pitches[:3] = [KIT_PITCHES[(bar_index + pitch_bias + i) % len(KIT_PITCHES)] for i in range(3)]
    return [(slot, pitch, rng.randrange(72, 121)) for slot, pitch in zip(selected, pitches)]


def _notes_from_bars(
    bars: list[list[tuple[int, int, int]]],
    *,
    ppq: int,
    numerator: int,
    denominator: int,
) -> list[Note]:
    bar_ticks = _bar_ticks(ppq, numerator, denominator)
    slot_ticks = Fraction(bar_ticks, _slots(numerator, denominator))
    notes: list[Note] = []
    for bar_index, bar in enumerate(bars):
        bar_start = bar_index * bar_ticks
        for slot, pitch, velocity in bar:
            start = bar_start + int(slot_ticks * slot)
            end = min(bar_start + bar_ticks, start + max(1, int(slot_ticks // 2)))
            if end <= start:
                end = start + 1
            notes.append(Note(start, end, pitch, velocity))
    return notes


def _song_from_bars(
    bars: list[list[tuple[int, int, int]]],
    *,
    ppq: int,
    numerator: int,
    denominator: int,
) -> MidiSong:
    notes = _notes_from_bars(
        bars, ppq=ppq, numerator=numerator, denominator=denominator
    )
    return MidiSong(
        ppq,
        [Part(0, 0, 9, 0, "certified control kit", True, notes)],
        [(0, 500_000)],
        [(0, numerator, denominator)],
        [],
    )


def _arrangement_hashes(song: MidiSong, bars: int) -> tuple[str, str]:
    exact = [
        (note.start, note.end, note.pitch, note.velocity)
        for note in song.parts[0].notes
    ]
    beat = [
        (
            round(note.start / song.ticks_per_beat, 8),
            round(note.end / song.ticks_per_beat, 8),
            note.pitch,
        )
        for note in song.parts[0].notes
    ]
    exact_payload = {
        "bars": bars,
        "ppq": song.ticks_per_beat,
        "meters": song.meters,
        "notes": exact,
    }
    beat_payload = {"bars": bars, "meters": song.meters, "notes": beat}
    return sha256_json(exact_payload), sha256_json(beat_payload)


def _midi_bytes(song: MidiSong) -> bytes:
    """Serialize one generated song without using a detector or parser."""
    midi = mido.MidiFile(type=1, ticks_per_beat=song.ticks_per_beat)
    meter_track = mido.MidiTrack()
    numerator, denominator = song.meters[0][1:]
    meter_track.append(mido.MetaMessage("track_name", name="certified controls", time=0))
    meter_track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    meter_track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=numerator,
            denominator=denominator,
            clocks_per_click=24,
            notated_32nd_notes_per_beat=8,
            time=0,
        )
    )
    meter_track.append(mido.MetaMessage("end_of_track", time=0))
    midi.tracks.append(meter_track)

    events: list[tuple[int, int, int, mido.Message]] = []
    sequence = 0
    for note in song.parts[0].notes:
        events.append(
            (note.start, 2, sequence, mido.Message(
                "note_on", channel=9, note=note.pitch, velocity=note.velocity, time=0
            ))
        )
        sequence += 1
        events.append(
            (note.end, 1, sequence, mido.Message(
                "note_off", channel=9, note=note.pitch, velocity=0, time=0
            ))
        )
        sequence += 1
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name="certified control kit", time=0))
    previous = 0
    for tick, _priority, _sequence, message in sorted(events, key=lambda item: item[:3]):
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    midi.tracks.append(track)
    from io import BytesIO

    buffer = BytesIO()
    midi.save(file=buffer)
    return buffer.getvalue()


def _oracle_certificate(song: MidiSong) -> dict:
    windows = enumerate_windows(
        song,
        bar_counts=BAR_COUNTS,
        min_hits=MIN_HITS,
        min_pitches=MIN_PITCHES,
    )
    # The existing oracle exposes a comparison limit for large real inputs.
    # Controls are small enough to derive the exact number of bucket pairs, so
    # use that finite count as the limit and exhaust every eligible pair. This
    # keeps the negative certification independent of an arbitrary truncation.
    buckets: Counter[tuple[int, int, int]] = Counter(
        (window.bar_count, window.numerator, window.denominator)
        for window in windows
    )
    exhaustive_budget = max(
        1, sum(count * (count - 1) // 2 for count in buckets.values())
    )
    pairs, stats = enumerate_admissible_pairs(
        windows,
        song.ticks_per_beat,
        max_pair_comparisons=exhaustive_budget,
    )
    return {
        "eligible_window_count": len(windows),
        "oracle_pair_count": len(pairs),
        "pair_comparisons": stats["pair_comparisons"],
        "pair_budget": stats["pair_budget"],
        "pair_budget_reached": stats["pair_budget_reached"],
        "exhaustive_pair_enumeration": not stats["pair_budget_reached"],
        "pairs": pairs,
    }


def _target_pair_key(
    first: tuple[int, int],
    second: tuple[int, int],
    *,
    bar_count: int,
    numerator: int,
    denominator: int,
) -> tuple[int, ...]:
    left, right = sorted((first, second))
    return (bar_count, numerator, denominator, left[0], left[1], right[0], right[1])


@dataclass(frozen=True)
class CertifiedCase:
    case_id: str
    split: str
    kind: str
    design_index: int
    attempt: int
    rng_seed: int
    bars: int
    ppq: int
    numerator: int
    denominator: int
    song: MidiSong
    midi_path: str
    midi_payload: bytes
    exact_arrangement_sha256: str
    beat_arrangement_sha256: str
    oracle: dict
    target_intervals: tuple[tuple[int, int], ...] = ()
    target_pair_keys: tuple[tuple[int, ...], ...] = ()

    def metadata(self) -> dict:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "kind": self.kind,
            "design_index": self.design_index,
            "attempt": self.attempt,
            "rng_seed": self.rng_seed,
            "bars": self.bars,
            "ticks_per_beat": self.ppq,
            "meter": [self.numerator, self.denominator],
            "midi_path": self.midi_path,
            "midi_bytes": len(self.midi_payload),
            "midi_sha256": _hash_bytes(self.midi_payload),
            "exact_arrangement_sha256": self.exact_arrangement_sha256,
            "beat_arrangement_sha256": self.beat_arrangement_sha256,
            "oracle": {
                key: value for key, value in self.oracle.items() if key != "pairs"
            },
            "target_intervals": [list(interval) for interval in self.target_intervals],
            "target_pair_keys": [list(pair) for pair in self.target_pair_keys],
        }


def _candidate_negative(split: str, index: int, attempt: int) -> CertifiedCase:
    seed = int.from_bytes(
        sha256(f"{NAMESPACE}:negative:{split}:{index}:{attempt}".encode()).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    numerator, denominator = METERS[index % len(METERS)]
    ppq = PPQS[(index // len(METERS) + attempt) % len(PPQS)]
    bars = MIN_BARS + ((index * 7 + attempt * 3) % (MAX_BARS - MIN_BARS + 1))
    generated = [
        _make_bar(
            rng,
            ppq=ppq,
            numerator=numerator,
            denominator=denominator,
            bar_index=bar,
            pitch_bias=index,
        )
        for bar in range(bars)
    ]
    song = _song_from_bars(
        generated, ppq=ppq, numerator=numerator, denominator=denominator
    )
    oracle = _oracle_certificate(song)
    exact_hash, beat_hash = _arrangement_hashes(song, bars)
    payload = _midi_bytes(song)
    return CertifiedCase(
        case_id=f"{split}-negative-{index:03d}",
        split=split,
        kind="certified_negative",
        design_index=index,
        attempt=attempt,
        rng_seed=seed,
        bars=bars,
        ppq=ppq,
        numerator=numerator,
        denominator=denominator,
        song=song,
        midi_path=f"midi/{split}/negative-{index:03d}.mid",
        midi_payload=payload,
        exact_arrangement_sha256=exact_hash,
        beat_arrangement_sha256=beat_hash,
        oracle=oracle,
    )


def _candidate_positive(split: str, index: int, attempt: int) -> CertifiedCase:
    seed = int.from_bytes(
        sha256(f"{NAMESPACE}:positive:{split}:{index}:{attempt}".encode()).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    numerator, denominator = METERS[(index + 1) % len(METERS)]
    ppq = PPQS[(index // len(METERS) + attempt + 1) % len(PPQS)]
    target_bars = (1, 2, 4)[index % 3]
    bars = max(MIN_BARS, 3 * target_bars + 7) + ((index * 5 + attempt) % 8)
    target_start_bars = (1, 1 + target_bars + 2, 1 + 2 * (target_bars + 2))
    target_end = target_start_bars[-1] + target_bars
    if target_end >= bars:
        bars = target_end + 2
    target_pattern = [
        _make_bar(
            rng,
            ppq=ppq,
            numerator=numerator,
            denominator=denominator,
            bar_index=100 + bar,
            pitch_bias=index + 17,
        )
        for bar in range(target_bars)
    ]
    generated: list[list[tuple[int, int, int]]] = []
    targets = set()
    for start in target_start_bars:
        targets.update(range(start, start + target_bars))
    for bar in range(bars):
        if bar in targets:
            first = next(start for start in target_start_bars if start <= bar < start + target_bars)
            generated.append(target_pattern[bar - first])
        else:
            generated.append(
                _make_bar(
                    rng,
                    ppq=ppq,
                    numerator=numerator,
                    denominator=denominator,
                    bar_index=bar + 200,
                    pitch_bias=index,
                )
            )
    song = _song_from_bars(
        generated, ppq=ppq, numerator=numerator, denominator=denominator
    )
    oracle = _oracle_certificate(song)
    bar_ticks = _bar_ticks(ppq, numerator, denominator)
    intervals = tuple(
        (start * bar_ticks, (start + target_bars) * bar_ticks)
        for start in target_start_bars
    )
    target_pairs = tuple(
        _target_pair_key(
            intervals[left], intervals[right],
            bar_count=target_bars,
            numerator=numerator,
            denominator=denominator,
        )
        for left in range(len(intervals))
        for right in range(left + 1, len(intervals))
    )
    if oracle["pair_budget_reached"] or not set(target_pairs).issubset(oracle["pairs"]):
        raise ValueError("positive candidate did not receive oracle target certification")
    exact_hash, beat_hash = _arrangement_hashes(song, bars)
    payload = _midi_bytes(song)
    return CertifiedCase(
        case_id=f"{split}-positive-{index:03d}",
        split=split,
        kind="planted_positive",
        design_index=index,
        attempt=attempt,
        rng_seed=seed,
        bars=bars,
        ppq=ppq,
        numerator=numerator,
        denominator=denominator,
        song=song,
        midi_path=f"midi/{split}/positive-{index:03d}.mid",
        midi_payload=payload,
        exact_arrangement_sha256=exact_hash,
        beat_arrangement_sha256=beat_hash,
        oracle=oracle,
        target_intervals=intervals,
        target_pair_keys=target_pairs,
    )


def _accept_unique(
    candidate: CertifiedCase,
    *,
    exact_seen: set[str],
    beat_seen: set[str],
) -> tuple[bool, list[str]]:
    reasons = []
    if candidate.exact_arrangement_sha256 in exact_seen:
        reasons.append("exact_arrangement")
    if candidate.beat_arrangement_sha256 in beat_seen:
        reasons.append("beat_arrangement")
    if candidate.kind == "certified_negative":
        if candidate.oracle["pair_budget_reached"]:
            reasons.append("oracle_pair_budget")
        elif candidate.oracle["oracle_pair_count"]:
            reasons.append("oracle_admissible_pair")
    return not reasons, reasons


def generate_certified_cohort(
    *,
    negative_cases_per_split: int = NEGATIVE_CASES_PER_SPLIT,
    positive_cases_per_split: int = POSITIVE_CASES_PER_SPLIT,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> tuple[list[CertifiedCase], dict]:
    """Generate, certify and de-duplicate the complete control cohort."""
    if negative_cases_per_split < 1 or positive_cases_per_split < 1:
        raise ValueError("case counts must be positive")
    if max_attempts < negative_cases_per_split * 2 + positive_cases_per_split * 2:
        raise ValueError("max_attempts is too small for the requested cohort")
    cases: list[CertifiedCase] = []
    exact_seen: set[str] = set()
    beat_seen: set[str] = set()
    rejected = Counter()
    attempts = 0
    for split in SPLITS:
        for kind, count in (
            ("negative", negative_cases_per_split),
            ("positive", positive_cases_per_split),
        ):
            index = 0
            while index < count:
                if attempts >= max_attempts:
                    raise RuntimeError(
                        f"certified cohort exceeded max generation attempts {max_attempts}"
                    )
                attempt = attempts
                attempts += 1
                try:
                    candidate = (
                        _candidate_negative(split, index, attempt)
                        if kind == "negative"
                        else _candidate_positive(split, index, attempt)
                    )
                except ValueError as exc:
                    rejected[f"generation_error:{type(exc).__name__}"] += 1
                    continue
                accepted, reasons = _accept_unique(
                    candidate, exact_seen=exact_seen, beat_seen=beat_seen
                )
                if not accepted:
                    for reason in reasons:
                        rejected[reason] += 1
                    continue
                cases.append(candidate)
                exact_seen.add(candidate.exact_arrangement_sha256)
                beat_seen.add(candidate.beat_arrangement_sha256)
                index += 1
    negative = [case for case in cases if case.kind == "certified_negative"]
    positive = [case for case in cases if case.kind == "planted_positive"]
    if len({case.exact_arrangement_sha256 for case in negative}) != len(negative):
        raise AssertionError("negative exact arrangement collision")
    if len({case.beat_arrangement_sha256 for case in negative}) != len(negative):
        raise AssertionError("negative beat arrangement collision")
    audit = {
        "requested": {
            "negative_cases": len(negative),
            "positive_cases": len(positive),
            "development_negative": sum(
                case.split == "development" for case in negative
            ),
            "test_negative": sum(case.split == "test" for case in negative),
            "development_positive": sum(
                case.split == "development" for case in positive
            ),
            "test_positive": sum(case.split == "test" for case in positive),
        },
        "attempts": attempts,
        "max_attempts": max_attempts,
        "rejected": dict(sorted(rejected.items())),
        "exact_unique_arrangements": len(exact_seen),
        "beat_unique_arrangements": len(beat_seen),
        "negative_oracle_pair_budget_reached": sum(
            case.oracle["pair_budget_reached"] for case in negative
        ),
        "negative_oracle_pair_count_total": sum(
            case.oracle["oracle_pair_count"] for case in negative
        ),
        "positive_target_pair_count": sum(len(case.target_pair_keys) for case in positive),
        "positive_target_pairs_oracle_confirmed": sum(
            set(case.target_pair_keys).issubset(case.oracle["pairs"])
            for case in positive
        ),
    }
    return cases, audit


def _direct_edges(phrases: list[dict]) -> set[tuple[int, ...]]:
    edges: set[tuple[int, ...]] = set()
    for phrase in phrases:
        geometry = (
            phrase["bar_count"], phrase["meter_numerator"], phrase["meter_denominator"]
        )
        prototype = (phrase["start_tick"], phrase["end_tick"])
        for occurrence in phrase.get("occurrences", []):
            other = (occurrence["start_tick"], occurrence["end_tick"])
            if other == prototype:
                continue
            first, second = sorted((prototype, other))
            edges.add((*geometry, first[0], first[1], second[0], second[1]))
    return edges


def _wilson(successes: int, total: int) -> list[float] | None:
    if total < 1:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _score_case(case: CertifiedCase, result: dict, elapsed: float) -> dict:
    phrases = result["phrases"]
    direct_edges = _direct_edges(phrases)
    targets = set(case.target_pair_keys)
    covered = len(targets & direct_edges)
    return {
        "case_id": case.case_id,
        "split": case.split,
        "kind": case.kind,
        "oracle_pair_count": case.oracle["oracle_pair_count"],
        "oracle_pair_budget_reached": case.oracle["pair_budget_reached"],
        "target_pair_count": len(targets),
        "target_pairs_covered_by_direct_detector_edges": covered,
        "detector_runtime_seconds": elapsed,
        "detector_phrase_count": len(phrases),
        "negative_case_with_output": case.kind == "certified_negative" and bool(phrases),
        "detector_stats": result["stats"],
    }


def _aggregate_method(rows: list[dict]) -> dict:
    negatives = [row for row in rows if row["kind"] == "certified_negative"]
    positives = [row for row in rows if row["kind"] == "planted_positive"]
    negative_outputs = sum(row["negative_case_with_output"] for row in negatives)
    target_pairs = sum(row["target_pair_count"] for row in positives)
    covered_pairs = sum(
        row["target_pairs_covered_by_direct_detector_edges"] for row in positives
    )
    return {
        "cases": len(rows),
        "negative_cases": len(negatives),
        "negative_cases_with_output": negative_outputs,
        "negative_output_rate": negative_outputs / len(negatives) if negatives else None,
        "negative_output_wilson_95": _wilson(negative_outputs, len(negatives)),
        "positive_cases": len(positives),
        "positive_target_pairs": target_pairs,
        "positive_target_pairs_covered_by_direct_detector_edges": covered_pairs,
        "positive_oracle_edge_coverage": covered_pairs / target_pairs if target_pairs else None,
        "oracle_pair_budget_reached_cases": sum(row["oracle_pair_budget_reached"] for row in rows),
        "detector_search_limited_cases": sum(
            bool(row["detector_stats"].get("search_limited")) for row in rows
        ),
        "detector_candidate_limit_cases": sum(
            bool(row["detector_stats"].get("candidate_limit_reached")) for row in rows
        ),
        "detector_runtime_seconds": sum(row["detector_runtime_seconds"] for row in rows),
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _result_artifacts(
    negative_cases_per_split: int,
    positive_cases_per_split: int,
) -> list[str]:
    """Return the deterministic artifact list before candidate generation."""
    artifacts = ["design.json", "labels.json", "raw_results.json", "aggregate.json"]
    for split in SPLITS:
        artifacts.extend(
            f"midi/{split}/negative-{index:03d}.mid"
            for index in range(negative_cases_per_split)
        )
        artifacts.extend(
            f"midi/{split}/positive-{index:03d}.mid"
            for index in range(positive_cases_per_split)
        )
    return artifacts


def frozen_design(
    *,
    negative_cases_per_split: int = NEGATIVE_CASES_PER_SPLIT,
    positive_cases_per_split: int = POSITIVE_CASES_PER_SPLIT,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> dict:
    """Return the design object before any candidate generation starts."""
    return {
        "version": VERSION,
        "namespace": NAMESPACE,
        "case_counts": {
            "negative_total": negative_cases_per_split * 2,
            "positive_total": positive_cases_per_split * 2,
            "negative_per_split": negative_cases_per_split,
            "positive_per_split": positive_cases_per_split,
        },
        "splits": list(SPLITS),
        "bars": [MIN_BARS, MAX_BARS],
        "meters": [list(meter) for meter in METERS],
        "ticks_per_beat": list(PPQS),
        "negative_acceptance": {
            "oracle_pair_count": 0,
            "pair_budget_reached": False,
            "exhaustive_pair_enumeration": True,
            "all_eligible_pairs_compared_under_budget": True,
            "bar_counts": list(BAR_COUNTS),
            "timing_tolerance_beats": [TIMING_TOLERANCE_BEATS.numerator, TIMING_TOLERANCE_BEATS.denominator],
            "hit_error_fraction": [HIT_ERROR_FRACTION.numerator, HIT_ERROR_FRACTION.denominator],
            "min_hits": MIN_HITS,
            "min_pitches": MIN_PITCHES,
            "pair_comparison_limit": "exact bucket-pair count per generated song",
        },
        "positive_acceptance": {
            "known_repeated_bar_regions": True,
            "target_pairs_must_be_oracle_admissible": True,
            "coverage_definition": "fraction of labelled target oracle edges reproduced as direct prototype to occurrence detector edges",
        },
        "uniqueness": {
            "reject_exact_arrangement_sha256_collision": True,
            "reject_beat_normalized_arrangement_sha256_collision": True,
            "scope": "all accepted controls",
        },
        "generation": {
            "max_attempts": max_attempts,
            "pattern_generator": "standard-library random.Random seeded by namespace, split, kind, index and attempt",
            "conditional_negative_bias": "negative cases are conditioned on zero admissible pairs under the stated symbolic oracle",
        },
        "claim_boundary": "algorithm-independent symbolic controls only; no human specificity, musical quality or real corpus accuracy claim",
        "result_artifacts": _result_artifacts(
            negative_cases_per_split, positive_cases_per_split
        ),
    }


def run(
    output: Path,
    *,
    negative_cases_per_split: int = NEGATIVE_CASES_PER_SPLIT,
    positive_cases_per_split: int = POSITIVE_CASES_PER_SPLIT,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> dict:
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"experiment output must be new or empty: {output}")
    started_at = time.monotonic()
    design = frozen_design(
        negative_cases_per_split=negative_cases_per_split,
        positive_cases_per_split=positive_cases_per_split,
        max_attempts=max_attempts,
    )
    cases, generation_audit = generate_certified_cohort(
        negative_cases_per_split=negative_cases_per_split,
        positive_cases_per_split=positive_cases_per_split,
        max_attempts=max_attempts,
    )
    config = {
        "generator": {
            "version": VERSION,
            "namespace": NAMESPACE,
            "meters": [list(meter) for meter in METERS],
            "ticks_per_beat": list(PPQS),
            "bar_range": [MIN_BARS, MAX_BARS],
            "max_generation_attempts": max_attempts,
        },
        "oracle": {
            "bar_counts": list(BAR_COUNTS),
            "timing_tolerance_beats": [TIMING_TOLERANCE_BEATS.numerator, TIMING_TOLERANCE_BEATS.denominator],
            "hit_error_fraction": [HIT_ERROR_FRACTION.numerator, HIT_ERROR_FRACTION.denominator],
            "min_hits": MIN_HITS,
            "min_pitches": MIN_PITCHES,
            "pair_comparison_limit": "exact bucket-pair count per generated song",
            "pair_comparison_cap": None,
        },
        "detector_modes": ["exact", "tolerant"],
    }
    cohort = [case.metadata() for case in cases]
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=cohort,
        required_files=(
            "scripts/evaluate_certified_drums.py",
            "samuged/drum_oracle.py",
            "samuged/drums.py",
            "samuged/evaluate_drums.py",
            "samuged/experiment.py",
            "samuged/midi.py",
            "samuged/__init__.py",
            "samuged/metadata_recovery.py",
            "pyproject.toml",
            "requirements-research.lock",
        ),
    )
    links = receipt_links(receipt)
    output = output.resolve()

    for case in cases:
        path = output / case.midi_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(case.midi_payload)
        parsed = load_midi(path)
        if parsed.ticks_per_beat != case.ppq or len(parsed.parts[0].notes) != len(case.song.parts[0].notes):
            raise ValueError(f"serialized control did not round-trip: {case.case_id}")

    labels = {
        "version": VERSION,
        **links,
        "generation_audit": generation_audit,
        "labels": [
            {
                "case_id": case.case_id,
                "split": case.split,
                "kind": case.kind,
                "midi_path": case.midi_path,
                "midi_sha256": _hash_bytes(case.midi_payload),
                "oracle_pair_count": case.oracle["oracle_pair_count"],
                "oracle_pair_budget_reached": case.oracle["pair_budget_reached"],
                "target_intervals": [list(interval) for interval in case.target_intervals],
                "target_pair_keys": [list(pair) for pair in case.target_pair_keys],
                "negative_certified": case.kind == "certified_negative" and case.oracle["oracle_pair_count"] == 0 and not case.oracle["pair_budget_reached"],
                "positive_oracle_confirmed": case.kind == "planted_positive" and set(case.target_pair_keys).issubset(case.oracle["pairs"]),
            }
            for case in cases
        ],
    }
    frozen_design_artifact = {
        "version": VERSION,
        **links,
        "design": design,
        "config": config,
        "design_sha256": sha256_json(design),
        "config_sha256": sha256_json(config),
        "case_cohort_sha256": receipt["case_cohort_sha256"],
        "generation_audit": generation_audit,
        "case_count": len(cases),
    }
    _write_json(output / "design.json", frozen_design_artifact)
    _write_json(output / "labels.json", labels)

    methods: dict[str, list[dict]] = {}
    for mode in ("exact", "tolerant"):
        detector_config = DrumConfig(mode=mode, top_k=3)
        rows = []
        for case in cases:
            detector_started = time.monotonic()
            result = extract_drums(case.song, detector_config)
            rows.append(_score_case(case, result, time.monotonic() - detector_started))
        methods[mode] = rows

    aggregate = {
        "version": VERSION,
        **links,
        "design_sha256": sha256_json(design),
        "config_sha256": sha256_json(config),
        "case_cohort_sha256": receipt["case_cohort_sha256"],
        "case_count": len(cases),
        "generation_audit": generation_audit,
        "methods": {
            mode: {
                "overall": _aggregate_method(rows),
                "by_split": {
                    split: _aggregate_method([row for row in rows if row["split"] == split])
                    for split in SPLITS
                },
            }
            for mode, rows in methods.items()
        },
        "claim_boundary": design["claim_boundary"],
        "runtime_seconds": time.monotonic() - started_at,
    }
    raw = {
        "version": VERSION,
        **links,
        "design_sha256": sha256_json(design),
        "config_sha256": sha256_json(config),
        "case_cohort_sha256": receipt["case_cohort_sha256"],
        "case_count": len(cases),
        "cases": cohort,
        "methods": methods,
        "claim_boundary": design["claim_boundary"],
    }
    _write_json(output / "raw_results.json", raw)
    _write_json(output / "aggregate.json", aggregate)
    complete = complete_experiment(output)
    return {**aggregate, "completion": complete}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
