"""Independent pairwise coverage audit for recurring drum discovery.

The oracle enumerates meter aligned windows and verifies pairs without using the
detector's window generation, seeding, grouping or matching helpers. It measures
coverage of a fixed symbolic admissibility rule. It does not measure musical
quality, human relevance or false positives against human annotations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import time
from typing import Iterable

from .drum_stress import CONDITIONS, generate_cohort
from .drums import DrumConfig, drum_part, extract_drums
from .experiment import complete_experiment, prepare_experiment, receipt_links
from .midi import MidiSong, Note, Part, load_midi


ORACLE_VERSION = "drum-pair-oracle-v1"
BAR_COUNTS = (1, 2, 4)
TIMING_TOLERANCE_BEATS = Fraction(1, 12)
HIT_ERROR_FRACTION = Fraction(1, 10)
MIN_HITS = 8
MIN_PITCHES = 2
MAX_PAIR_COMPARISONS = 250_000
REAL_CLIP_BARS = 32
REAL_CASES = 16
REAL_MANIFEST = Path("research_local/pilot_both_v03/sources.jsonl")
REAL_ROOT = Path("datasets/Lakh MIDI Clean")


@dataclass(frozen=True)
class OracleWindow:
    start: int
    end: int
    bar_count: int
    numerator: int
    denominator: int
    notes: tuple[Note, ...]

    @property
    def identity(self) -> tuple[int, int, int, int, int]:
        return (
            self.bar_count,
            self.numerator,
            self.denominator,
            self.start,
            self.end,
        )


@dataclass(frozen=True)
class PairMatch:
    admissible: bool
    matched_hits: int
    total_edits: int
    allowed_edits: int
    reason: str


def _round_fraction(value: Fraction) -> int:
    if value < 0:
        raise ValueError("tick positions must be nonnegative")
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def normalized_meters(song: MidiSong) -> list[tuple[int, int, int]]:
    """Validate and canonicalize source meter changes for oracle geometry."""
    by_tick: dict[int, tuple[int, int]] = {}
    for change in song.meters:
        if not isinstance(change, tuple) or len(change) != 3:
            raise ValueError("meter changes must be (tick, numerator, denominator)")
        tick, numerator, denominator = change
        if any(isinstance(value, bool) or not isinstance(value, int) for value in change):
            raise TypeError("meter fields must be integers")
        if tick < 0 or numerator <= 0 or denominator <= 0:
            raise ValueError("invalid meter change")
        if denominator & (denominator - 1):
            raise ValueError("meter denominator must be a power of two")
        by_tick[tick] = (numerator, denominator)
    if 0 not in by_tick:
        by_tick[0] = (4, 4)
    return [(tick, *by_tick[tick]) for tick in sorted(by_tick)]


def _bar_cells(song: MidiSong, count: int) -> list[tuple[int, int, int, int]]:
    """Return the first complete bars, resetting the origin at meter changes."""
    if count < 1:
        raise ValueError("bar count must be positive")
    meters = normalized_meters(song)
    cells: list[tuple[int, int, int, int]] = []
    for index, (origin, numerator, denominator) in enumerate(meters):
        next_change = meters[index + 1][0] if index + 1 < len(meters) else None
        bar_ticks = Fraction(song.ticks_per_beat * numerator * 4, denominator)
        available = count - len(cells)
        if next_change is not None:
            available = min(
                available,
                int(Fraction(next_change - origin, 1) // bar_ticks),
            )
        for offset in range(max(0, available)):
            start = _round_fraction(Fraction(origin) + offset * bar_ticks)
            end = _round_fraction(Fraction(origin) + (offset + 1) * bar_ticks)
            if end > start:
                cells.append((start, end, numerator, denominator))
            if len(cells) == count:
                return cells
    return cells


def clip_to_first_bars(song: MidiSong, count: int = REAL_CLIP_BARS) -> MidiSong:
    """Clip notes and metadata at the end of the requested complete source bars."""
    cells = _bar_cells(song, count)
    if not cells:
        return MidiSong(
            song.ticks_per_beat,
            [],
            list(song.tempos),
            list(song.meters),
            list(song.warnings),
            list(song.metadata_repairs),
        )
    clip_end = cells[-1][1]
    parts = []
    for part in song.parts:
        notes = [
            Note(note.start, min(note.end, clip_end), note.pitch, note.velocity)
            for note in part.notes
            if note.start < clip_end and min(note.end, clip_end) > note.start
        ]
        parts.append(Part(
            part.index, part.track, part.channel, part.program, part.name,
            part.is_drum, notes,
        ))
    tempos = [change for change in song.tempos if change[0] < clip_end]
    meters = [change for change in song.meters if change[0] < clip_end]
    return MidiSong(
        song.ticks_per_beat,
        parts,
        tempos,
        meters,
        list(song.warnings),
        list(song.metadata_repairs),
    )


def enumerate_windows(
    song: MidiSong,
    *,
    bar_counts: tuple[int, ...] = BAR_COUNTS,
    min_hits: int = MIN_HITS,
    min_pitches: int = MIN_PITCHES,
) -> list[OracleWindow]:
    """Enumerate eligible windows independently from the detector implementation."""
    ensemble = drum_part(song)
    notes = sorted(ensemble.notes, key=lambda note: (note.start, note.pitch, note.end))
    if not notes:
        return []
    meters = normalized_meters(song)
    final_end = max(note.end for note in notes)
    windows = []
    for meter_index, (origin, numerator, denominator) in enumerate(meters):
        next_change = meters[meter_index + 1][0] if meter_index + 1 < len(meters) else None
        bar_ticks = Fraction(song.ticks_per_beat * numerator * 4, denominator)
        if next_change is None:
            extent = max(Fraction(), Fraction(final_end - origin, 1))
            available_bars = _ceil_fraction(extent / bar_ticks)
        else:
            available_bars = int(Fraction(next_change - origin, 1) // bar_ticks)
        for offset in range(max(0, available_bars)):
            for bar_count in bar_counts:
                if offset + bar_count > available_bars:
                    continue
                start = _round_fraction(Fraction(origin) + offset * bar_ticks)
                end = _round_fraction(Fraction(origin) + (offset + bar_count) * bar_ticks)
                selected = tuple(note for note in notes if start <= note.start < end)
                if len(selected) < min_hits:
                    continue
                if len({note.pitch for note in selected}) < min_pitches:
                    continue
                windows.append(OracleWindow(
                    start, end, bar_count, numerator, denominator, selected
                ))
    return sorted(windows, key=lambda item: item.identity)


def maximum_pitch_matches(
    left: Iterable[Note],
    right: Iterable[Note],
    *,
    left_start: int,
    right_start: int,
    ppq: int,
    tolerance_beats: Fraction = TIMING_TOLERANCE_BEATS,
) -> int:
    """Return maximum cardinality equal pitch matches within onset tolerance.

    For each pitch this is the standard ordered interval matching algorithm. It
    matches the earliest compatible strikes, which is maximum cardinality for
    two sorted one dimensional point sets. It does not choose the locally
    closest strike, a rule that can consume a strike needed by a later note.
    """
    tolerance_ticks = tolerance_beats * ppq
    by_pitch_left: dict[int, list[int]] = defaultdict(list)
    by_pitch_right: dict[int, list[int]] = defaultdict(list)
    for note in left:
        by_pitch_left[note.pitch].append(note.start - left_start)
    for note in right:
        by_pitch_right[note.pitch].append(note.start - right_start)
    matched = 0
    for pitch in sorted(set(by_pitch_left) | set(by_pitch_right)):
        first = sorted(by_pitch_left.get(pitch, ()))
        second = sorted(by_pitch_right.get(pitch, ()))
        i = j = 0
        while i < len(first) and j < len(second):
            difference = first[i] - second[j]
            if abs(difference) <= tolerance_ticks:
                matched += 1
                i += 1
                j += 1
            elif difference < -tolerance_ticks:
                i += 1
            else:
                j += 1
    return matched


def verify_pair(
    left: OracleWindow,
    right: OracleWindow,
    ppq: int,
    *,
    timing_tolerance_beats: Fraction = TIMING_TOLERANCE_BEATS,
    hit_error_fraction: Fraction = HIT_ERROR_FRACTION,
) -> PairMatch:
    if left.bar_count != right.bar_count:
        return PairMatch(False, 0, 0, 0, "different_bar_count")
    if (left.numerator, left.denominator) != (right.numerator, right.denominator):
        return PairMatch(False, 0, 0, 0, "different_meter")
    if left.start < right.end and right.start < left.end:
        return PairMatch(False, 0, 0, 0, "overlap")
    maximum_hits = max(len(left.notes), len(right.notes))
    allowed = (maximum_hits * hit_error_fraction.numerator) // hit_error_fraction.denominator
    if abs(len(left.notes) - len(right.notes)) > allowed:
        return PairMatch(False, 0, abs(len(left.notes) - len(right.notes)), allowed,
                         "hit_count_difference")
    matched = maximum_pitch_matches(
        left.notes,
        right.notes,
        left_start=left.start,
        right_start=right.start,
        ppq=ppq,
        tolerance_beats=timing_tolerance_beats,
    )
    edits = len(left.notes) + len(right.notes) - 2 * matched
    return PairMatch(
        edits <= allowed,
        matched,
        edits,
        allowed,
        "admissible" if edits <= allowed else "too_many_edits",
    )


def _pair_key(left: OracleWindow, right: OracleWindow) -> tuple[int, ...]:
    if (left.start, left.end) > (right.start, right.end):
        left, right = right, left
    return (
        left.bar_count, left.numerator, left.denominator,
        left.start, left.end, right.start, right.end,
    )


def enumerate_admissible_pairs(
    windows: list[OracleWindow],
    ppq: int,
    *,
    max_pair_comparisons: int = MAX_PAIR_COMPARISONS,
) -> tuple[set[tuple[int, ...]], dict]:
    """Exhaustively compare eligible pairs until the explicit safety budget."""
    if max_pair_comparisons < 1:
        raise ValueError("max_pair_comparisons must be positive")
    buckets: dict[tuple[int, int, int], list[OracleWindow]] = defaultdict(list)
    for window in windows:
        buckets[(window.bar_count, window.numerator, window.denominator)].append(window)
    admissible: set[tuple[int, ...]] = set()
    comparisons = 0
    for bucket in buckets.values():
        for left, right in combinations(bucket, 2):
            if left.start < right.end and right.start < left.end:
                continue
            if comparisons == max_pair_comparisons:
                return admissible, {
                    "pair_comparisons": comparisons,
                    "pair_budget": max_pair_comparisons,
                    "pair_budget_reached": True,
                }
            comparisons += 1
            if verify_pair(left, right, ppq).admissible:
                admissible.add(_pair_key(left, right))
    return admissible, {
        "pair_comparisons": comparisons,
        "pair_budget": max_pair_comparisons,
        "pair_budget_reached": False,
    }


def _reported_pairs(phrases: list[dict]) -> tuple[set[tuple[int, ...]], set[tuple[int, ...]], int]:
    family_pairs: set[tuple[int, ...]] = set()
    verified_edges: set[tuple[int, ...]] = set()
    instances = 0
    for phrase in phrases:
        occurrences = phrase.get("occurrences", [])
        for left, right in combinations(occurrences, 2):
            instances += 1
            first = (left["start_tick"], left["end_tick"])
            second = (right["start_tick"], right["end_tick"])
            if first > second:
                first, second = second, first
            family_pairs.add((
                phrase["bar_count"],
                phrase["meter_numerator"],
                phrase["meter_denominator"],
                first[0], first[1], second[0], second[1],
            ))
        prototype = (phrase["start_tick"], phrase["end_tick"])
        for occurrence in occurrences:
            other = (occurrence["start_tick"], occurrence["end_tick"])
            if other == prototype:
                continue
            first, second = sorted((prototype, other))
            verified_edges.add((
                phrase["bar_count"],
                phrase["meter_numerator"],
                phrase["meter_denominator"],
                first[0], first[1], second[0], second[1],
            ))
    return family_pairs, verified_edges, instances


def evaluate_song(
    song: MidiSong,
    *,
    detector_config: DrumConfig,
    max_pair_comparisons: int = MAX_PAIR_COMPARISONS,
) -> dict:
    oracle_started = time.monotonic()
    windows = enumerate_windows(song)
    oracle_pairs, oracle_stats = enumerate_admissible_pairs(
        windows, song.ticks_per_beat,
        max_pair_comparisons=max_pair_comparisons,
    )
    oracle_elapsed = time.monotonic() - oracle_started
    detector_started = time.monotonic()
    detector = extract_drums(song, detector_config)
    detector_elapsed = time.monotonic() - detector_started
    reported, verified_edges, reported_instances = _reported_pairs(detector["phrases"])
    valid = reported & oracle_pairs
    invalid = reported - oracle_pairs
    valid_verified_edges = verified_edges & oracle_pairs
    invalid_verified_edges = verified_edges - oracle_pairs

    by_identity = {window.identity: window for window in windows}
    invalid_diagnostics = []
    for pair in sorted(invalid):
        bar_count, numerator, denominator, ls, le, rs, re = pair
        left = by_identity.get((bar_count, numerator, denominator, ls, le))
        right = by_identity.get((bar_count, numerator, denominator, rs, re))
        if left is None or right is None:
            reason = "reported_interval_not_oracle_eligible"
            detail = None
        else:
            checked = verify_pair(left, right, song.ticks_per_beat)
            reason = checked.reason
            detail = asdict(checked)
        invalid_diagnostics.append({
            "pair": list(pair),
            "reason": reason,
            "match": detail,
            "detector_relation": (
                "direct_prototype_edge" if pair in verified_edges
                else "cross_occurrence_pair_not_directly_matched"
            ),
        })

    missed = oracle_pairs - reported
    memberships: dict[tuple[int, int, int, int, int], set[int]] = defaultdict(set)
    for family_index, phrase in enumerate(detector["phrases"]):
        geometry = (
            phrase["bar_count"], phrase["meter_numerator"],
            phrase["meter_denominator"],
        )
        for occurrence in phrase["occurrences"]:
            memberships[(*geometry, occurrence["start_tick"], occurrence["end_tick"])].add(
                family_index
            )
    missed_endpoint_status = Counter()
    for pair in missed:
        bar_count, numerator, denominator, ls, le, rs, re = pair
        left_membership = memberships.get((bar_count, numerator, denominator, ls, le), set())
        right_membership = memberships.get((bar_count, numerator, denominator, rs, re), set())
        if left_membership & right_membership:
            status = "same_selected_family_but_pair_missing"
        elif left_membership and right_membership:
            status = "endpoints_partitioned_across_selected_families"
        elif left_membership or right_membership:
            status = "one_endpoint_absent_from_selected_families"
        else:
            status = "both_endpoints_absent_from_selected_families"
        missed_endpoint_status[status] += 1
    stats = detector["stats"]
    if stats["search_limited"]:
        miss_boundary = "detector_search_or_candidate_limit"
    elif stats["raw_candidate_count"] > stats["selected_count"]:
        miss_boundary = "candidate_presence_not_observable_after_top3_and_diversity_selection"
    else:
        miss_boundary = "not_returned_without_reported_search_limit"
    return {
        "eligible_windows": len(windows),
        "oracle_pair_count": len(oracle_pairs),
        **oracle_stats,
        "oracle_runtime_seconds": oracle_elapsed,
        "detector_runtime_seconds": detector_elapsed,
        "detector_selected_phrases": len(detector["phrases"]),
        "detector_reported_pair_instances": reported_instances,
        "detector_reported_unique_pairs": len(reported),
        "valid_reported_pairs": len(valid),
        "oracle_inadmissible_reported_pairs": len(invalid),
        "detector_directly_verified_edges": len(verified_edges),
        "oracle_admissible_directly_verified_edges": len(valid_verified_edges),
        "oracle_inadmissible_directly_verified_edges": len(invalid_verified_edges),
        "missed_oracle_pairs": len(missed),
        "selected_pair_coverage": len(valid) / len(oracle_pairs) if oracle_pairs else None,
        "reported_pair_admissibility": len(valid) / len(reported) if reported else None,
        "miss_interpretation_boundary": miss_boundary,
        "missed_pair_endpoint_status": dict(missed_endpoint_status),
        "invalid_pair_diagnostics": invalid_diagnostics,
        "missed_pair_examples": [list(pair) for pair in sorted(missed)[:10]],
        "detector_stats": stats,
    }


def _file_sha256(path: Path) -> str:
    result = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _real_manifest_rows(repository: Path) -> list[dict]:
    rows = []
    with (repository/REAL_MANIFEST).open() as stream:
        for line_index, line in enumerate(stream):
            source = json.loads(line)
            if source.get("drum_stats", {}).get("input_drum_parts", 0) < 1:
                continue
            path = repository/REAL_ROOT/source["source_path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append({
                "cohort_type": "real_clip",
                "cohort_index": len(rows),
                "manifest_line_index": line_index,
                "source_path": source["source_path"],
                "manifest_source_sha256": source["source_sha256"],
                "current_source_sha256": _file_sha256(path),
                "clip_bars": REAL_CLIP_BARS,
            })
            if len(rows) == REAL_CASES:
                break
    if len(rows) != REAL_CASES:
        raise ValueError(f"expected {REAL_CASES} pilot files with drum parts")
    if any(row["manifest_source_sha256"] != row["current_source_sha256"] for row in rows):
        raise ValueError("real pilot source hash differs from frozen manifest")
    return rows


def _aggregate(rows: list[dict]) -> dict:
    oracle_pairs = sum(row["oracle_pair_count"] for row in rows)
    reported = sum(row["detector_reported_unique_pairs"] for row in rows)
    valid = sum(row["valid_reported_pairs"] for row in rows)
    invalid = sum(row["oracle_inadmissible_reported_pairs"] for row in rows)
    verified_edges = sum(row["detector_directly_verified_edges"] for row in rows)
    valid_verified_edges = sum(
        row["oracle_admissible_directly_verified_edges"] for row in rows
    )
    invalid_verified_edges = sum(
        row["oracle_inadmissible_directly_verified_edges"] for row in rows
    )
    return {
        "cases": len(rows),
        "eligible_windows": sum(row["eligible_windows"] for row in rows),
        "pair_comparisons": sum(row["pair_comparisons"] for row in rows),
        "pair_budget_reached_cases": sum(row["pair_budget_reached"] for row in rows),
        "oracle_pair_count": oracle_pairs,
        "detector_reported_unique_pairs": reported,
        "valid_reported_pairs": valid,
        "oracle_inadmissible_reported_pairs": invalid,
        "detector_directly_verified_edges": verified_edges,
        "oracle_admissible_directly_verified_edges": valid_verified_edges,
        "oracle_inadmissible_directly_verified_edges": invalid_verified_edges,
        "directly_verified_edge_admissibility": (
            valid_verified_edges / verified_edges if verified_edges else None
        ),
        "selected_pair_coverage": valid / oracle_pairs if oracle_pairs else None,
        "reported_pair_admissibility": valid / reported if reported else None,
        "detector_search_limited_cases": sum(
            row["detector_stats"]["search_limited"] for row in rows
        ),
        "detector_top_k_reached_cases": sum(
            row["detector_stats"]["selected_count"] == 3 for row in rows
        ),
        "detector_candidate_limit_cases": sum(
            row["detector_stats"]["candidate_limit_reached"] for row in rows
        ),
        "oracle_runtime_seconds": sum(row["oracle_runtime_seconds"] for row in rows),
        "detector_runtime_seconds": sum(row["detector_runtime_seconds"] for row in rows),
        "miss_boundaries": dict(Counter(
            row["miss_interpretation_boundary"]
            for row in rows
            if row["missed_oracle_pairs"]
        )),
        "missed_pair_endpoint_status": dict(sum(
            (Counter(row["missed_pair_endpoint_status"]) for row in rows),
            Counter(),
        )),
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def run(output: Path) -> dict:
    repository = Path(__file__).resolve().parent.parent
    all_synthetic, uniqueness = generate_cohort(40)
    synthetic = [case for case in all_synthetic if case.split == "development"]
    if len(synthetic) != 240:
        raise ValueError(f"expected 240 development cases, found {len(synthetic)}")
    real = _real_manifest_rows(repository)
    detector_config = DrumConfig(mode="tolerant", top_k=3)
    oracle_config = {
        "bar_counts": list(BAR_COUNTS),
        "timing_tolerance_beats": [1, 12],
        "hit_error_fraction": [1, 10],
        "edit_count": "left_hits + right_hits - 2 * maximum_cardinality_matches",
        "allowed_edits": "floor(0.10 * max(left_hits, right_hits))",
        "min_hits": MIN_HITS,
        "min_pitches": MIN_PITCHES,
        "nonoverlap": "half-open source tick intervals must not intersect",
        "same_geometry": "bar_count, meter numerator and meter denominator",
        "max_pair_comparisons_per_case": MAX_PAIR_COMPARISONS,
    }
    design = {
        "version": ORACLE_VERSION,
        "purpose": "symbolic discovery coverage against an independent exhaustive pair verifier",
        "synthetic_policy": "all 240 development cases from drum-stress-v1 with cases_per_condition=40",
        "real_policy": "first 16 manifest rows with parsed drum parts, clipped to first 32 complete meter bars",
        "oracle_config": oracle_config,
        "detector_config": asdict(detector_config),
        "reported_pair_policy": (
            "selected family coverage counts every unordered occurrence pair in each "
            "returned family; directly verified edges separately count only prototype "
            "to occurrence pairs that the detector matcher evaluated"
        ),
        "selection_boundary": (
            "coverage uses only the detector's selected top three families; the public "
            "result does not reveal whether a missed oracle pair existed before ranking "
            "or diversity pruning"
        ),
        "claim_boundary": (
            "pairwise symbolic admissibility only; no human annotation, musical quality, "
            "negative truth or real corpus accuracy claim"
        ),
    }
    receipt_cases = [
        {"cohort_type": "synthetic_development", **case.metadata()}
        for case in synthetic
    ] + real
    receipt = prepare_experiment(
        output,
        design=design,
        config={"oracle": oracle_config, "detector": asdict(detector_config)},
        cases=receipt_cases,
        required_files=(
            "samuged/drum_oracle.py",
            "samuged/drum_stress.py",
            "samuged/drums.py",
            "samuged/evaluate_drums.py",
            "samuged/experiment.py",
            "samuged/__init__.py",
            "samuged/metadata_recovery.py",
            "samuged/midi.py",
            REAL_MANIFEST.as_posix(),
            "pyproject.toml",
            "requirements-research.lock",
        ),
    )
    links = receipt_links(receipt)

    rows = []
    started = time.monotonic()
    for case in synthetic:
        row = evaluate_song(
            case.song,
            detector_config=detector_config,
            max_pair_comparisons=MAX_PAIR_COMPARISONS,
        )
        rows.append({
            "case_id": case.case_id,
            "cohort_type": "synthetic_development",
            "condition": case.condition,
            "target_bar_count": case.target_bar_count,
            **row,
        })
    for source in real:
        song = load_midi(repository/REAL_ROOT/source["source_path"])
        clipped = clip_to_first_bars(song, REAL_CLIP_BARS)
        row = evaluate_song(
            clipped,
            detector_config=detector_config,
            max_pair_comparisons=MAX_PAIR_COMPARISONS,
        )
        rows.append({
            "case_id": f"real-{source['cohort_index']:03d}",
            "cohort_type": "real_clip",
            "condition": None,
            "source_path": source["source_path"],
            "source_sha256": source["current_source_sha256"],
            "clip_bars": REAL_CLIP_BARS,
            "clip_drum_hits": len(drum_part(clipped).notes),
            **row,
        })
    elapsed = time.monotonic() - started

    synthetic_rows = [row for row in rows if row["cohort_type"] == "synthetic_development"]
    real_rows = [row for row in rows if row["cohort_type"] == "real_clip"]
    aggregate = {
        "version": ORACLE_VERSION,
        **links,
        "elapsed_seconds": elapsed,
        "config": {"oracle": oracle_config, "detector": asdict(detector_config)},
        "synthetic_development": _aggregate(synthetic_rows),
        "synthetic_by_condition": {
            condition: _aggregate([row for row in synthetic_rows if row["condition"] == condition])
            for condition in CONDITIONS
        },
        "real_clips": _aggregate(real_rows),
        "oracle_inadmissible_pair_cases": sum(
            row["oracle_inadmissible_reported_pairs"] > 0 for row in rows
        ),
        "oracle_inadmissible_direct_edge_cases": sum(
            row["oracle_inadmissible_directly_verified_edges"] > 0 for row in rows
        ),
        "pair_budget_reached_cases": sum(row["pair_budget_reached"] for row in rows),
        "claim_boundary": design["claim_boundary"],
        "selection_boundary": design["selection_boundary"],
        "interpretation": (
            "selected pair coverage is constrained by top_k=3, candidate limits, "
            "ranking and diversity pruning; it is not detector candidate recall"
        ),
        "family_pair_boundary": (
            "the detector matches every occurrence to one prototype, so pairwise "
            "admissibility is not transitive; inadmissible cross-occurrence family "
            "pairs do not imply an invalid prototype match"
        ),
        "uniqueness_audit": uniqueness,
    }
    raw = {"version": ORACLE_VERSION, **links, "design": design, "cases": rows}
    _write_json(output/"raw_results.json", raw)
    _write_json(output/"aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
