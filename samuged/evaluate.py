"""Deterministic planted-motif evaluation for recurring phrase extraction.

This benchmark measures recovery of known symbolic recurrence. It does not
measure musical quality, listener response or memorability.
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
import subprocess
import sys
import tempfile
import time
from typing import Iterable

from .midi import MidiSong, Note, Part, export_phrase, load_midi
from .experiment import complete_experiment, prepare_experiment, receipt_links
from .phrases import Config, extract


BENCHMARK_VERSION = "planted-motif-v1"
IOU_THRESHOLD = 0.8
CASE_KINDS = (
    "legacy_contiguous_exact",
    "exact",
    "transpose",
    "jitter",
    "pitch_mutation",
    "rhythm_negative",
    "random_negative",
    "polyphonic_chords",
    "offbeat",
    "inserted_note",
    "deleted_note",
    "meter_ppq_change",
    "transposed_jitter",
)
MATCH_MODES = ("exact", "transposed", "approximate")
_DEV_SEED_BASE = 10_000_000
_TEST_SEED_BASE = 20_000_000


@dataclass
class BenchmarkCase:
    case_id: str
    split: str
    kind: str
    rng_seed: int
    song: MidiSong
    truth_intervals: list[tuple[int, int]]
    prototype: list[Note]
    positive: bool
    limitation: str | None = None

    def metadata(self) -> dict:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "kind": self.kind,
            "rng_seed": self.rng_seed,
            "positive": self.positive,
            "limitation": self.limitation,
            "ticks_per_beat": self.song.ticks_per_beat,
            "meters": self.song.meters,
            "truth_intervals": [list(interval) for interval in self.truth_intervals],
            "prototype": [asdict(note) for note in self.prototype],
            "note_count": sum(len(part.notes) for part in self.song.parts),
        }


def benchmark_design() -> dict:
    """Return the frozen design recorded in each result artifact."""
    return {
        "version": BENCHMARK_VERSION,
        "case_kinds": list(CASE_KINDS),
        "match_modes": list(MATCH_MODES),
        "iou_threshold": IOU_THRESHOLD,
        "candidate_definition": (
            "a predicted family is correct when distinct predicted occurrences "
            "match every planted occurrence at temporal IoU >= 0.8"
        ),
        "occurrence_definition": (
            "one-to-one temporal interval matching across returned families at IoU >= 0.8"
        ),
        "positive_limitations": ["inserted_note", "deleted_note"],
        "negative_cases": ["rhythm_negative", "random_negative"],
        "lengths": [6, 8, 12, 16, 24, 32],
        "span_beats": [4.0, 32.0],
        "detector_config": {
            "top_k": 10,
            "timing_tolerance_beats": 0.125,
            "duration_tolerance_beats": 0.25,
            "pitch_error_fraction": 0.125,
            "duration_error_fraction": 0.25,
            "onset_merge_beats": 1 / 24,
            "mode": "varied over match_modes",
        },
        "development_seed_namespace": _DEV_SEED_BASE,
        "test_seed_namespace": _TEST_SEED_BASE,
        "primary_hypotheses": [
            "transposition-invariant matching recovers planted transpositions",
            "explicit onset and duration checks reject repeated pitch sequences with different rhythm",
        ],
        "claim_boundary": (
            "planted symbolic recurrence only; real-corpus phrase quality and human memorability are unproven"
        ),
    }


def _motif(rng: random.Random, length: int) -> tuple[list[int], list[float], list[float]]:
    pitch = rng.randint(58, 68)
    pitches = [pitch]
    steps = (-5, -3, -2, 2, 3, 5)
    for _ in range(length - 1):
        pitch += rng.choice(steps)
        if pitch < 48:
            pitch += 12
        elif pitch > 84:
            pitch -= 12
        pitches.append(pitch)
    onsets = [0.0]
    for _ in range(length - 1):
        # The shortest supported eight-note motif remains above the detector's
        # frozen four-beat lower span bound.
        onsets.append(onsets[-1] + rng.choice((0.625, 0.75, 1.0)))
    durations = [rng.choice((0.3, 0.4, 0.5, 0.75)) for _ in range(length)]
    return pitches, onsets, durations


def _notes_from_pattern(
    pitches: list[int],
    onsets: list[float],
    durations: list[float],
    *,
    start_beat: float,
    ppq: int,
    velocity: int = 92,
) -> list[Note]:
    return [
        Note(
            round((start_beat + onset) * ppq),
            round((start_beat + onset + duration) * ppq),
            pitch,
            velocity,
        )
        for pitch, onset, duration in zip(pitches, onsets, durations)
    ]


def _context(rng: random.Random, ppq: int, start_beat: float, count: int, base: int) -> list[Note]:
    notes = []
    beat = start_beat
    for index in range(count):
        beat += rng.choice((0.45, 0.65, 0.85))
        pitch = base + index * 2 + rng.choice((0, 1))
        notes.append(Note(round(beat * ppq), round((beat + 0.23) * ppq), pitch, 62 + index))
    return notes


def _interval(notes: list[Note]) -> tuple[int, int]:
    return min(note.start for note in notes), max(note.end for note in notes)


def _build_case(kind: str, split: str, local_index: int, rng_seed: int) -> BenchmarkCase:
    rng = random.Random(rng_seed)
    ppq = rng.choice((240, 480, 960)) if kind == "meter_ppq_change" else 480
    length = rng.choice((8, 12, 16))
    pitches, onsets, durations = _motif(rng, length)
    first_beat = 6.25 if kind == "offbeat" else 6.0
    first = _notes_from_pattern(pitches, onsets, durations, start_beat=first_beat, ppq=ppq)
    motif_beats = max(onset + duration for onset, duration in zip(onsets, durations))
    # The legacy control has no inter-copy silence and varies by case seed.
    # Its third copy below lets the old state machine observe the boundary.
    second_beat = first_beat + motif_beats
    if kind != "legacy_contiguous_exact":
        second_beat += 5.0
    second_pitches = list(pitches)
    second_onsets = list(onsets)
    second_durations = list(durations)
    positive = kind not in {"rhythm_negative", "random_negative"}
    limitation = None

    if kind in {"transpose", "transposed_jitter"}:
        shift = rng.choice((-7, -5, 3, 5, 7))
        second_pitches = [pitch + shift for pitch in second_pitches]
    if kind in {"jitter", "transposed_jitter"}:
        second_onsets = [
            onset if index == 0 else onset + rng.uniform(-0.07, 0.07)
            for index, onset in enumerate(second_onsets)
        ]
        second_durations = [max(0.12, duration + rng.uniform(-0.14, 0.14)) for duration in durations]
    if kind == "pitch_mutation":
        mutation = length // 2
        second_pitches[mutation] += rng.choice((-1, 1))
    if kind == "rhythm_negative":
        second_onsets = [onset * 1.45 for onset in onsets]
        second_durations = [duration * 1.35 for duration in durations]
    if kind == "inserted_note":
        limitation = "fixed-length matcher has no insertion alignment"
        insert_at = length // 2
        inserted_onset = (second_onsets[insert_at - 1] + second_onsets[insert_at]) / 2
        second_pitches.insert(insert_at, second_pitches[insert_at - 1] + 1)
        second_onsets.insert(insert_at, inserted_onset)
        second_durations.insert(insert_at, 0.2)
    if kind == "deleted_note":
        limitation = "fixed-length matcher has no deletion alignment"
        delete_at = length // 2
        del second_pitches[delete_at]
        del second_onsets[delete_at]
        del second_durations[delete_at]

    if kind == "random_negative":
        # No repeated seed triples or contexts. This is a genuine no-motif case,
        # not a positive with a threshold chosen to force failure.
        notes = []
        beat = 0.0
        for index in range(38):
            beat += rng.choice((0.35, 0.55, 0.8, 1.05))
            pitch = 36 + ((index * 11 + index * index * 3) % 55)
            notes.append(Note(round(beat * ppq), round((beat + 0.21 + (index % 3) * 0.07) * ppq), pitch, 70))
        song = MidiSong(ppq, [Part(0, 1, 0, 0, "melody", False, notes)],
                        [(0, 500_000)], [(0, 4, 4)], [])
        case_id = f"{split}-{local_index:04d}-{kind}"
        return BenchmarkCase(case_id, split, kind, rng_seed, song, [], [], False)

    second = _notes_from_pattern(
        second_pitches, second_onsets, second_durations, start_beat=second_beat, ppq=ppq
    )
    if kind == "legacy_contiguous_exact":
        third_beat = second_beat + motif_beats
        third = _notes_from_pattern(
            pitches, onsets, durations, start_beat=third_beat, ppq=ppq
        )
        notes = _context(rng, ppq, 0.0, 5, 38) + first + second + third
        notes += _context(rng, ppq, third_beat + max(onsets) + 1.0, 5, 49)
    else:
        third = []
        notes = _context(rng, ppq, 0.0, 5, 38) + first
        notes += _context(rng, ppq, first_beat + motif_beats + 0.4, 5, 43) + second
        notes += _context(rng, ppq, second_beat + max(second_onsets) + 1.0, 5, 49)
    if kind == "polyphonic_chords":
        for note in first + second:
            notes.extend(
                [
                    Note(note.start, note.end, max(0, note.pitch - 7), 58),
                    Note(note.start, note.end, max(0, note.pitch - 12), 55),
                ]
            )
    notes.sort(key=lambda note: (note.start, note.end, note.pitch, note.velocity))
    meters = [(0, 4, 4)]
    if kind == "meter_ppq_change":
        meters = [(0, 3, 4), (round(second_beat * ppq), 6, 8)]
    song = MidiSong(ppq, [Part(0, 1, 0, 0, "melody", False, notes)],
                    [(0, 500_000)], meters, [])
    truth = [_interval(first), _interval(second)] + ([_interval(third)] if third else []) if positive else []
    case_id = f"{split}-{local_index:04d}-{kind}"
    return BenchmarkCase(case_id, split, kind, rng_seed, song, truth, first, positive, limitation)


def generate_cases(count: int = 100) -> list[BenchmarkCase]:
    """Generate balanced cases with nonoverlapping development and test RNG seeds."""
    if count < 1:
        raise ValueError("case count must be positive")
    dev_count = (count + 1) // 2
    split_counts = {"development": dev_count, "test": count - dev_count}
    cases = []
    for split in ("development", "test"):
        base = _DEV_SEED_BASE if split == "development" else _TEST_SEED_BASE
        for local_index in range(split_counts[split]):
            kind = CASE_KINDS[local_index % len(CASE_KINDS)]
            cases.append(_build_case(kind, split, local_index, base + local_index))
    return cases


def temporal_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0 else 0.0


def _one_to_one_matches(
    predicted: Iterable[tuple[int, int]], truth: Iterable[tuple[int, int]], threshold: float
) -> list[tuple[int, int, float]]:
    predicted = list(predicted)
    truth = list(truth)
    choices = sorted(
        (
            (temporal_iou(predicted[p_index], truth[t_index]), p_index, t_index)
            for p_index in range(len(predicted))
            for t_index in range(len(truth))
        ),
        reverse=True,
    )
    used_predicted, used_truth, matches = set(), set(), []
    for iou, p_index, t_index in choices:
        if iou < threshold:
            break
        if p_index not in used_predicted and t_index not in used_truth:
            used_predicted.add(p_index)
            used_truth.add(t_index)
            matches.append((p_index, t_index, iou))
    return matches


def score_case(case: BenchmarkCase, phrases: list[dict], elapsed_seconds: float) -> dict:
    candidates = []
    true_candidate_rank = None
    for rank, phrase in enumerate(phrases, 1):
        intervals = [(row["start_tick"], row["end_tick"]) for row in phrase["occurrences"]]
        matches = _one_to_one_matches(intervals, case.truth_intervals, IOU_THRESHOLD)
        correct = bool(case.truth_intervals) and len(matches) == len(case.truth_intervals)
        if correct and true_candidate_rank is None:
            true_candidate_rank = rank
        candidates.append(
            {
                "rank": rank,
                "family_id": phrase["family_id"],
                "note_count": phrase["note_count"],
                "recurrence_score": phrase["recurrence_score"],
                "intervals": [list(interval) for interval in intervals],
                "correct_family": correct,
                "truth_matches": [[p, t, round(iou, 8)] for p, t, iou in matches],
            }
        )

    flattened = [tuple(interval) for candidate in candidates for interval in candidate["intervals"]]
    occurrence_matches = _one_to_one_matches(flattened, case.truth_intervals, IOU_THRESHOLD)
    candidate_tp = int(true_candidate_rank is not None)
    candidate_fp = len(candidates) - candidate_tp
    candidate_fn = int(case.positive and not candidate_tp)
    occurrence_tp = len(occurrence_matches)
    return {
        "case_id": case.case_id,
        "split": case.split,
        "kind": case.kind,
        "positive": case.positive,
        "limitation": case.limitation,
        "elapsed_seconds": round(elapsed_seconds, 8),
        "candidate_tp": candidate_tp,
        "candidate_fp": candidate_fp,
        "candidate_fn": candidate_fn,
        "occurrence_tp": occurrence_tp,
        "occurrence_fp": len(flattened) - occurrence_tp,
        "occurrence_fn": len(case.truth_intervals) - occurrence_tp,
        "recovered": bool(candidate_tp),
        "recovery_rank": true_candidate_rank,
        "false_positive_case": not case.positive and bool(candidates),
        "candidates": candidates,
    }


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def aggregate_results(rows: list[dict]) -> dict:
    positive = [row for row in rows if row["positive"]]
    negative = [row for row in rows if not row["positive"]]
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
    elapsed = [row["elapsed_seconds"] for row in rows]
    ranks = [row["recovery_rank"] for row in positive if row["recovery_rank"] is not None]
    by_kind = {}
    for kind in CASE_KINDS:
        selected = [row for row in rows if row["kind"] == kind]
        if not selected:
            continue
        by_kind[kind] = {
            "cases": len(selected),
            "positive_cases": sum(row["positive"] for row in selected),
            "recovered_cases": sum(row["recovered"] for row in selected),
            "false_positive_cases": sum(row["false_positive_case"] for row in selected),
        }
    return {
        "cases": len(rows),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "candidate": candidate,
        "occurrence": occurrence,
        "recovered_positive_cases": sum(row["recovered"] for row in positive),
        "top1_recovery": _ratio(sum(row["recovery_rank"] == 1 for row in positive), len(positive)),
        "mean_reciprocal_rank": _ratio(sum(1 / rank for rank in ranks), len(positive)),
        "false_positive_case_count": sum(row["false_positive_case"] for row in negative),
        "false_positive_case_rate": _ratio(sum(row["false_positive_case"] for row in negative), len(negative)),
        "false_positive_case_ids": [row["case_id"] for row in negative if row["false_positive_case"]],
        "runtime_seconds": {
            "total": sum(elapsed),
            "mean": statistics.mean(elapsed) if elapsed else 0.0,
            "median": statistics.median(elapsed) if elapsed else 0.0,
            "maximum": max(elapsed, default=0.0),
        },
        "by_kind": by_kind,
    }


def bootstrap_intervals(rows: list[dict], iterations: int = 1000, seed: int = 7001) -> dict:
    if not rows or iterations < 1:
        return {}
    rng = random.Random(seed)
    values = {name: [] for name in ("candidate_f1", "occurrence_f1", "top1_recovery", "false_positive_case_rate")}
    for _ in range(iterations):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        aggregate = aggregate_results(sample)
        values["candidate_f1"].append(aggregate["candidate"]["f1"])
        values["occurrence_f1"].append(aggregate["occurrence"]["f1"])
        values["top1_recovery"].append(aggregate["top1_recovery"])
        values["false_positive_case_rate"].append(aggregate["false_positive_case_rate"])

    result = {}
    for name, samples in values.items():
        samples.sort()
        low = samples[math.floor(0.025 * (len(samples) - 1))]
        high = samples[math.ceil(0.975 * (len(samples) - 1))]
        result[name] = [low, high]
    return result


def _write_case(case: BenchmarkCase, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = case.song.parts[0]
    end = max(note.end for note in part.notes) + 1
    export_phrase(case.song, part, part.notes, 0, end, path)


def _prototype_key(notes: list[Note]) -> tuple[tuple[int, int, int], ...]:
    if not notes:
        return ()
    first = min(note.start for note in notes)
    return tuple(
        (note.pitch, note.start - first, note.end - note.start)
        for note in sorted(notes, key=lambda note: (note.start, note.pitch, note.end))
    )


def select_legacy_cases(cases: list[BenchmarkCase], limit: int) -> list[BenchmarkCase]:
    if limit <= 0:
        return []
    by_kind = {kind: [case for case in cases if case.kind == kind] for kind in CASE_KINDS}
    selected = []
    round_index = 0
    while len(selected) < min(limit, len(cases)):
        progress = False
        for kind_index, kind in enumerate(CASE_KINDS):
            bucket = by_kind[kind]
            if not bucket:
                continue
            preferred = "development" if kind_index % 2 == 0 else "test"
            ordered = sorted(bucket, key=lambda case: (case.split != preferred, case.case_id))
            if round_index < len(ordered):
                selected.append(ordered[round_index])
                progress = True
                if len(selected) == min(limit, len(cases)):
                    break
        if not progress:
            break
        round_index += 1
    return selected


def run_legacy(
    cases: list[BenchmarkCase], case_paths: dict[str, Path], output: Path, limit: int
) -> tuple[list[dict], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_legacy_case.py"
    selected = select_legacy_cases(cases, limit)
    rows = []
    for case in selected:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"legacy-{case.case_id}-", dir=output) as directory:
            export_dir = Path(directory)
            command = [sys.executable, str(script), str(case_paths[case.case_id]), str(export_dir)]
            status, returncode = "ok", None
            try:
                completed = subprocess.run(
                    command,
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                    env={**__import__("os").environ, "MPLBACKEND": "Agg"},
                )
                returncode = completed.returncode
                if returncode:
                    status = "error"
            except subprocess.TimeoutExpired:
                status = "timeout"

            exported = sorted(export_dir.rglob("*.mid"))
            valid, invalid, recovered = 0, 0, False
            prototype = _prototype_key(case.prototype)
            for path in exported:
                try:
                    song = load_midi(path)
                    valid += 1
                    if prototype and any(_prototype_key(part.notes) == prototype for part in song.parts):
                        recovered = True
                except Exception:
                    invalid += 1
            rows.append(
                {
                    "case_id": case.case_id,
                    "split": case.split,
                    "kind": case.kind,
                    "positive": case.positive,
                    "status": status,
                    "returncode": returncode,
                    "elapsed_seconds": round(time.monotonic() - started, 8),
                    "export_count": len(exported),
                    "valid_export_count": valid,
                    "invalid_export_count": invalid,
                    "prototype_recovered": recovered,
                    "false_positive_case": not case.positive and bool(exported),
                }
            )

    positive = [row for row in rows if row["positive"]]
    positive_control = [row for row in rows if row["kind"] == "legacy_contiguous_exact"]
    aggregate = {
        "cases": len(rows),
        "status_counts": {
            status: sum(row["status"] == status for row in rows)
            for status in ("ok", "error", "timeout")
        },
        "export_count": sum(row["export_count"] for row in rows),
        "valid_export_count": sum(row["valid_export_count"] for row in rows),
        "invalid_export_count": sum(row["invalid_export_count"] for row in rows),
        "prototype_recovered_cases": sum(row["prototype_recovered"] for row in positive),
        "prototype_coverage": _ratio(sum(row["prototype_recovered"] for row in positive), len(positive)),
        "positive_control_cases": len(positive_control),
        "positive_control_recovered_cases": sum(
            row["prototype_recovered"] for row in positive_control
        ),
        "positive_control_coverage": _ratio(
            sum(row["prototype_recovered"] for row in positive_control), len(positive_control)
        ),
        "false_positive_case_count": sum(row["false_positive_case"] for row in rows),
        "runtime_seconds": {
            "total": sum(row["elapsed_seconds"] for row in rows),
            "mean": statistics.mean([row["elapsed_seconds"] for row in rows]) if rows else 0.0,
            "maximum": max((row["elapsed_seconds"] for row in rows), default=0.0),
        },
        "candidate_metrics": None,
        "occurrence_metrics": None,
        "noncomparability_reason": (
            "the legacy detector exports prototypes without occurrence coordinates; "
            "candidate and occurrence F1 would be fabricated"
        ),
    }
    return rows, aggregate


def _json_write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_markdown(aggregate: dict) -> str:
    lines = [
        "# Planted motif evaluation",
        "",
        f"Design: `{aggregate['benchmark_version']}`. Cases: {aggregate['case_count']}. "
        f"Temporal match threshold: IoU >= {aggregate['iou_threshold']}.",
        "",
        "| Method | Candidate F1 | Occurrence F1 | Top 1 recovery | False positive cases | Mean seconds per case |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MATCH_MODES:
        row = aggregate["methods"][mode]["by_split"]["test"]
        lines.append(
            f"| {mode} | {row['candidate']['f1']:.3f} | {row['occurrence']['f1']:.3f} | "
            f"{_pct(row['top1_recovery'])} | {row['false_positive_case_count']}/{row['negative_cases']} | "
            f"{row['runtime_seconds']['mean']:.4f} |"
        )
    legacy = aggregate["legacy"]
    lines.extend(
        [
            f"| legacy subset | n/a | n/a | n/a | {legacy['false_positive_case_count']} | "
            f"{legacy['runtime_seconds']['mean']:.4f} |",
            "",
            "The main detector table reports the frozen test seed namespace. Development and combined metrics remain in `aggregate.json`.",
            "",
            "Legacy prototype coverage is reported separately because the legacy detector does not emit occurrence coordinates. "
            f"It recovered {legacy['prototype_recovered_cases']} planted prototypes from its positive subset "
            f"({_pct(legacy['prototype_coverage'])}) and produced {legacy['valid_export_count']} parseable exports.",
            f"Its adjacent exact-repeat positive control recovered "
            f"{legacy['positive_control_recovered_cases']}/{legacy['positive_control_cases']} cases. ",
            "",
            "## Recovery by case kind",
            "",
            "| Case kind | Exact | Transposed | Approximate |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for kind in CASE_KINDS:
        values = []
        for mode in MATCH_MODES:
            row = aggregate["methods"][mode]["by_kind"].get(kind, {})
            values.append(f"{row.get('recovered_cases', 0)}/{row.get('positive_cases', 0)}")
        lines.append(f"| {kind.replace('_', ' ')} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "Inserted and deleted note cases are retained as known fixed-length alignment limitations. "
            "Negative cases are generated independently of detector thresholds.",
            "",
            "These results measure planted symbolic recurrence. They do not validate phrase quality on real music or human memorability.",
            "",
        ]
    )
    return "\n".join(lines)


def run_benchmark(
    output: Path,
    *,
    seeds: int = 100,
    legacy_limit: int = 12,
    bootstrap_iterations: int = 1000,
) -> dict:
    if seeds < 1:
        raise ValueError("seeds must be positive")
    if legacy_limit < 0:
        raise ValueError("legacy_limit must be nonnegative")
    if isinstance(bootstrap_iterations, bool) or not isinstance(bootstrap_iterations, int) or bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be a positive integer")
    output = output.resolve()
    cases = generate_cases(seeds)
    design = benchmark_design()
    design["result_artifacts"] = ["raw_results.json", "aggregate.json", *(
        f"cases/{case.case_id}.mid" for case in cases
    )]
    design_hash = sha256(json.dumps(design, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    run_parameters = {
        "seeds": seeds,
        "legacy_limit": legacy_limit,
        "bootstrap_iterations": bootstrap_iterations,
    }
    detector_configs = {
        mode: asdict(Config(mode=mode, top_k=10)) for mode in MATCH_MODES
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config={"run_parameters": run_parameters, "detectors": detector_configs},
        cases=cases,
    )
    links = receipt_links(receipt)
    cases_dir = output / "cases"
    case_paths = {}
    for case in cases:
        path = cases_dir / f"{case.case_id}.mid"
        _write_case(case, path)
        case_paths[case.case_id] = path

    method_rows = {}
    for mode in MATCH_MODES:
        rows = []
        config = Config(**detector_configs[mode])
        for case in cases:
            started = time.monotonic()
            result = extract(case.song, config)
            elapsed = time.monotonic() - started
            row = score_case(case, result["phrases"], elapsed)
            row["search_limited"] = result["search_limited"]
            row["candidate_count_before_reranking"] = result["candidate_count"]
            rows.append(row)
        method_rows[mode] = rows

    legacy_rows, legacy_aggregate = run_legacy(cases, case_paths, output, legacy_limit)
    aggregate_methods = {}
    for index, mode in enumerate(MATCH_MODES):
        aggregate_methods[mode] = aggregate_results(method_rows[mode])
        aggregate_methods[mode]["bootstrap_ci95"] = bootstrap_intervals(
            method_rows[mode], bootstrap_iterations, seed=7100 + index
        )
        aggregate_methods[mode]["by_split"] = {}
        for split_index, split in enumerate(("development", "test")):
            split_rows = [row for row in method_rows[mode] if row["split"] == split]
            split_aggregate = aggregate_results(split_rows)
            split_aggregate["bootstrap_ci95"] = bootstrap_intervals(
                split_rows,
                bootstrap_iterations,
                seed=7200 + index * 10 + split_index,
            )
            aggregate_methods[mode]["by_split"][split] = split_aggregate

    raw = {
        "benchmark_version": BENCHMARK_VERSION,
        "design_sha256": design_hash,
        **links,
        "design": design,
        "run_parameters": run_parameters,
        "cases": [
            {
                **case.metadata(),
                "midi_path": case_paths[case.case_id].relative_to(output).as_posix(),
                "midi_sha256": sha256(case_paths[case.case_id].read_bytes()).hexdigest(),
                "methods": {mode: next(row for row in method_rows[mode] if row["case_id"] == case.case_id)
                            for mode in MATCH_MODES},
            }
            for case in cases
        ],
        "legacy": legacy_rows,
    }
    aggregate = {
        "benchmark_version": BENCHMARK_VERSION,
        "design_sha256": design_hash,
        **links,
        "case_count": len(cases),
        "split_counts": {split: sum(case.split == split for case in cases) for split in ("development", "test")},
        "iou_threshold": IOU_THRESHOLD,
        "run_parameters": run_parameters,
        "methods": aggregate_methods,
        "legacy": legacy_aggregate,
    }
    _json_write(output / "raw_results.json", raw)
    _json_write(output / "aggregate.json", aggregate)
    (output / "report.md").write_text(render_markdown(aggregate), encoding="utf-8")
    complete_experiment(output)
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=100, help="total deterministic benchmark cases")
    parser.add_argument("--legacy-limit", type=int, default=12)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(argv)
    result = run_benchmark(
        args.output,
        seeds=args.seeds,
        legacy_limit=args.legacy_limit,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
