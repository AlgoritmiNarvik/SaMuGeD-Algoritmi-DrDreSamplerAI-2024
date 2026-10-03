"""Bounded recurrence discovery with explicit monotone note alignment.

The detector allows a small number of internal note insertions, deletions or
substitutions. It preserves source ticks and does not perform tempo warping.
An occurrence with an inserted or deleted first or last note is excluded
because its boundary is underdetermined. Boundary pitch substitutions remain
allowed and retain the varied occurrence's exact source interval.
Its ranking score is evidence of symbolic recurrence, not human memorability.
Candidate generation is heuristic. It uses a bounded set of separated interval
and rhythm anchors, so edits that disrupt every selected anchor can be missed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
import time

from .midi import MidiSong, Part, bar_length
from .phrases import Window, skyline, window


@dataclass(frozen=True)
class AlignedConfig:
    min_notes: int = 6
    max_notes: int = 32
    min_beats: float = 4.0
    max_beats: float = 32.0
    max_gap_beats: float = 2.0
    timing_tolerance: float = 0.125
    duration_tolerance: float = 0.25
    duration_error_fraction: float = 0.25
    max_edit_fraction: float = 0.15
    max_edits: int = 4
    onset_merge_beats: float = 1 / 24
    seed_notes: int = 3
    seed_beat_bucket: float = 0.5
    span_beat_bucket: float = 1.0
    max_seed_offsets: int = 6
    max_seed_pairs: int = 6
    min_seed_support: int = 3
    max_shift_candidates: int = 4
    max_bucket: int = 192
    max_comparisons: int = 2_000
    max_stream_notes: int = 12_000
    max_windows: int = 120_000
    max_groups: int = 50_000
    max_candidates: int = 80
    top_k: int = 3

    def __post_init__(self) -> None:
        integer_bounds = {
            "min_notes": (4, 128),
            "max_notes": (4, 128),
            "max_edits": (0, 16),
            "seed_notes": (3, 5),
            "max_seed_offsets": (1, 32),
            "max_seed_pairs": (1, 64),
            "min_seed_support": (1, 32),
            "max_shift_candidates": (1, 32),
            "max_bucket": (1, 2048),
            "max_comparisons": (1, 2_000_000),
            "max_stream_notes": (1, 20_000),
            "max_windows": (1, 400_000),
            "max_groups": (1, 200_000),
            "max_candidates": (1, 10_000),
            "top_k": (1, 100),
        }
        for name, (low, high) in integer_bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        if self.min_notes > self.max_notes:
            raise ValueError("min_notes must not exceed max_notes")
        if not 0 < self.min_beats <= self.max_beats <= 128:
            raise ValueError("require 0 < min_beats <= max_beats <= 128")
        for name in (
            "max_gap_beats",
            "timing_tolerance",
            "duration_tolerance",
            "duration_error_fraction",
            "max_edit_fraction",
            "onset_merge_beats",
            "seed_beat_bucket",
            "span_beat_bucket",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not 0 < self.max_edit_fraction <= 0.15:
            raise ValueError("max_edit_fraction must be in (0, 0.15]")
        if not 0 <= self.duration_error_fraction <= 0.5:
            raise ValueError("duration_error_fraction must be in [0, 0.5]")
        if self.seed_beat_bucket == 0 or self.span_beat_bucket == 0:
            raise ValueError("seed and span beat buckets must be positive")
        if self.seed_notes > self.min_notes:
            raise ValueError("seed_notes must not exceed min_notes")


@dataclass(frozen=True)
class Alignment:
    shift: int
    edits: int
    insertions: tuple[int, ...]
    deletions: tuple[int, ...]
    substitutions: tuple[tuple[int, int], ...]
    matched_pairs: tuple[tuple[int, int], ...]
    max_timing_error: float
    mean_timing_error: float
    max_duration_error: float
    mean_duration_error: float
    similarity: float


def _allowed_edits(left_count: int, right_count: int, cfg: AlignedConfig) -> int:
    # One edit is allowed for short phrases. Above that, the integer bound never
    # exceeds the configured fraction or absolute cap.
    fractional = math.floor(max(left_count, right_count) * cfg.max_edit_fraction)
    return min(cfg.max_edits, max(1, fractional))


def _shift_candidates(left: Window, right: Window, allowed: int, limit: int) -> list[int]:
    counts: Counter[int] = Counter()
    for i, pitch in enumerate(left.pitches):
        low = max(0, i - allowed)
        high = min(len(right.pitches), i + allowed + 1)
        for j in range(low, high):
            counts[right.pitches[j] - pitch] += 1
    minimum_support = max(2, min(len(left.pitches), len(right.pitches)) - 2 * allowed)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], abs(item[0]), item[0]))
    supported = [shift for shift, count in ordered if count >= minimum_support]
    return supported[:limit]


def _edit_alignment(
    left: Window, right: Window, shift: int, allowed: int, cfg: AlignedConfig
) -> Alignment | None:
    m, n = len(left.pitches), len(right.pitches)
    if abs(m - n) > allowed:
        return None
    states: list[list[tuple[int, int, float, float, int] | None]] = [
        [None] * (n + 1) for _ in range(m + 1)
    ]
    steps = [[""] * (n + 1) for _ in range(m + 1)]
    # No initialization along row or column zero. The first source notes must
    # align, so terminal gaps are excluded inside the dynamic program.
    states[0][0] = (0, 0, 0.0, 0.0, 0)
    for i in range(1, m + 1):
        # Any alignment costing at most ``allowed`` stays inside this band.
        # This keeps verification proportional to phrase length times the
        # explicit edit allowance rather than the full Cartesian matrix.
        for j in range(max(1, i - allowed), min(n, i + allowed) + 1):
            substitution = int(right.pitches[j - 1] - left.pitches[i - 1] != shift)
            choices = []
            previous = states[i - 1][j - 1]
            timing_error = abs(
                (left.onsets[i - 1] - left.onsets[0])
                - (right.onsets[j - 1] - right.onsets[0])
            )
            if previous is not None and timing_error <= cfg.timing_tolerance:
                duration_error = abs(left.durations[i - 1] - right.durations[j - 1])
                edits, bad_duration, duration_sum, timing_sum, matched = previous
                state = (
                    edits + substitution,
                    bad_duration + int(duration_error > cfg.duration_tolerance),
                    duration_sum + duration_error,
                    timing_sum + timing_error,
                    matched + 1,
                )
                choices.append((state, "M" if not substitution else "S", 0))
            # The final notes must also align. This excludes trailing terminal
            # gaps in the DP rather than rejecting one arbitrary traceback.
            if (i, j) != (m, n):
                previous = states[i - 1][j]
                if previous is not None:
                    edits, bad_duration, duration_sum, timing_sum, matched = previous
                    choices.append(
                        ((edits + 1, bad_duration, duration_sum, timing_sum, matched), "D", 1)
                    )
                previous = states[i][j - 1]
                if previous is not None:
                    edits, bad_duration, duration_sum, timing_sum, matched = previous
                    choices.append(
                        ((edits + 1, bad_duration, duration_sum, timing_sum, matched), "I", 2)
                    )
            choices = [choice for choice in choices if choice[0][0] <= allowed]
            if not choices:
                continue
            state, step, _ = min(
                choices,
                key=lambda item: (
                    item[0][0],
                    item[0][1],
                    item[0][2] / max(1, item[0][4]),
                    item[0][3] / max(1, item[0][4]),
                    -item[0][4],
                    item[2],
                ),
            )
            states[i][j], steps[i][j] = state, step
    final_state = states[m][n]
    if final_state is None or final_state[0] > allowed:
        return None

    insertions: list[int] = []
    deletions: list[int] = []
    substitutions: list[tuple[int, int]] = []
    matched: list[tuple[int, int]] = []
    i, j = m, n
    while i or j:
        step = steps[i][j]
        if step in {"M", "S"}:
            i -= 1
            j -= 1
            matched.append((i, j))
            if step == "S":
                substitutions.append((i, j))
        elif step == "D":
            i -= 1
            deletions.append(i)
        elif step == "I":
            j -= 1
            insertions.append(j)
        else:
            return None
    matched.reverse()
    insertions.reverse()
    deletions.reverse()
    substitutions.reverse()
    if not matched or matched[0] != (0, 0) or matched[-1] != (m - 1, n - 1):
        # Internal edits are supported. Terminal gaps make phrase boundaries
        # underdetermined and are rejected rather than hidden by a score.
        return None

    first_left, first_right = matched[0]
    timing_errors = [
        abs(
            (left.onsets[a] - left.onsets[first_left])
            - (right.onsets[b] - right.onsets[first_right])
        )
        for a, b in matched
    ]
    duration_errors = [abs(left.durations[a] - right.durations[b]) for a, b in matched]
    return Alignment(
        shift=shift,
        edits=final_state[0],
        insertions=tuple(insertions),
        deletions=tuple(deletions),
        substitutions=tuple(substitutions),
        matched_pairs=tuple(matched),
        max_timing_error=max(timing_errors, default=0.0),
        mean_timing_error=statistics.mean(timing_errors) if timing_errors else 0.0,
        max_duration_error=max(duration_errors, default=0.0),
        mean_duration_error=statistics.mean(duration_errors) if duration_errors else 0.0,
        similarity=0.0,
    )


def _align_with_shifts(
    left: Window,
    right: Window,
    cfg: AlignedConfig,
    shifts: list[int],
) -> Alignment | None:
    allowed = _allowed_edits(len(left.pitches), len(right.pitches), cfg)
    best: Alignment | None = None
    for shift in shifts:
        result = _edit_alignment(left, right, shift, allowed, cfg)
        if result is None:
            continue
        if result.max_timing_error > cfg.timing_tolerance:
            continue
        duration_errors = [
            abs(left.durations[a] - right.durations[b]) for a, b in result.matched_pairs
        ]
        excessive = sum(error > cfg.duration_tolerance for error in duration_errors)
        if excessive > math.floor(len(duration_errors) * cfg.duration_error_fraction):
            continue
        if result.mean_duration_error > cfg.duration_tolerance:
            continue
        edit_quality = 1 - result.edits / max(len(left.pitches), len(right.pitches))
        timing_quality = 1 - result.mean_timing_error / max(cfg.timing_tolerance, 1e-12)
        duration_quality = 1 - min(
            1.0, result.mean_duration_error / max(cfg.duration_tolerance, 1e-12)
        )
        result = Alignment(
            **{**asdict(result), "similarity": 0.7 * edit_quality + 0.2 * timing_quality + 0.1 * duration_quality}
        )
        if best is None or (result.edits, -result.similarity, abs(result.shift), result.shift) < (
            best.edits,
            -best.similarity,
            abs(best.shift),
            best.shift,
        ):
            best = result
    return best


def align(left: Window, right: Window, cfg: AlignedConfig) -> Alignment | None:
    """Return a source-verifiable bounded alignment or ``None``."""
    allowed = _allowed_edits(len(left.pitches), len(right.pitches), cfg)
    shifts = _shift_candidates(left, right, allowed, cfg.max_shift_candidates)
    return _align_with_shifts(left, right, cfg, shifts)


def _offsets(count: int, seed_notes: int, maximum: int) -> tuple[int, ...]:
    available = count - seed_notes + 1
    if maximum == 1:
        return (0,)
    if available <= maximum:
        return tuple(range(available))
    return tuple(sorted({round(i * (available - 1) / (maximum - 1)) for i in range(maximum)}))


def _bucket(value: float, width: float, phase: float) -> int:
    return math.floor((value + phase * width) / width)


def _seed_keys(candidate: Window, cfg: AlignedConfig) -> tuple[tuple, ...]:
    keys = set()
    # Window onsets are already in beats. Recover the PPQ-independent span by
    # including the final duration rather than using source ticks.
    full_span_beats = max(
        onset + duration for onset, duration in zip(candidate.onsets, candidate.durations)
    )
    offsets = _offsets(len(candidate.pitches), cfg.seed_notes, cfg.max_seed_offsets)
    for seed_phase in (0.0, 0.5):
        anchors = []
        for offset in offsets:
            pitches = candidate.pitches[offset : offset + cfg.seed_notes]
            intervals = tuple(
                pitches[index + 1] - pitches[index]
                for index in range(len(pitches) - 1)
            )
            rhythm = tuple(
                _bucket(
                    candidate.onsets[offset + index] - candidate.onsets[offset],
                    cfg.seed_beat_bucket,
                    seed_phase,
                )
                for index in range(1, cfg.seed_notes)
            )
            anchors.append((offset, intervals, rhythm, candidate.onsets[offset]))
        pairs = [
            (left, right)
            for left_index, left in enumerate(anchors)
            for right in anchors[left_index + 1 :]
            if right[0] - left[0] >= cfg.seed_notes
        ]
        pairs.sort(key=lambda pair: (-(pair[1][0] - pair[0][0]), pair[0][0], pair[1][0]))
        pairs = pairs[: cfg.max_seed_pairs]
        if len(candidate.notes) <= 7 or not pairs:
            # Six and seven note windows have little room for two independent
            # anchors. Their single-anchor fallback remains fully verified.
            for _, intervals, rhythm, _ in anchors:
                for span_phase in (0.0, 0.5):
                    keys.add(
                        (
                            "single",
                            intervals,
                            rhythm,
                            _bucket(full_span_beats, cfg.span_beat_bucket, span_phase),
                        )
                    )
            if not pairs:
                continue
        for left, right in pairs:
            anchor_distance = right[3] - left[3]
            for distance_phase in (0.0, 0.5):
                for span_phase in (0.0, 0.5):
                    keys.add(
                        (
                            "pair",
                            left[1],
                            left[2],
                            right[1],
                            right[2],
                            _bucket(anchor_distance, cfg.span_beat_bucket, distance_phase),
                            _bucket(full_span_beats, cfg.span_beat_bucket, span_phase),
                        )
                    )
    return tuple(sorted(keys))


def _valid_window(stream, start: int, count: int, song: MidiSong, cfg: AlignedConfig) -> Window | None:
    candidate = window(stream, start, count, song.ticks_per_beat)
    beats = (candidate.end - candidate.start) / song.ticks_per_beat
    if not cfg.min_beats <= beats <= cfg.max_beats:
        return None
    if len(set(candidate.pitches)) < 3:
        return None
    if any(
        (stream[index + 1].start - stream[index].end) / song.ticks_per_beat > cfg.max_gap_beats
        for index in range(start, start + count - 1)
    ):
        return None
    return candidate


def _nonoverlap(items: list[tuple[Window, Alignment]]) -> list[tuple[Window, Alignment]]:
    chosen = []
    last_end = -1
    for item in sorted(items, key=lambda row: (row[0].end, row[0].start, row[0].index, len(row[0].notes))):
        if item[0].start >= last_end:
            chosen.append(item)
            last_end = item[0].end
    return sorted(chosen, key=lambda row: (row[0].start, row[0].end))


def _family_id(candidate: Window) -> str:
    payload = (
        tuple(pitch - candidate.pitches[0] for pitch in candidate.pitches),
        tuple(round(onset * 24) for onset in candidate.onsets),
        tuple(round(duration * 24) for duration in candidate.durations),
    )
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _exact_key(candidate: Window) -> tuple:
    """PPQ-independent exact transposed content key."""
    return (
        tuple(pitch - candidate.pitches[0] for pitch in candidate.pitches),
        tuple(round(onset, 8) for onset in candidate.onsets),
        tuple(round(duration, 8) for duration in candidate.durations),
    )


def _exact_alignment(left: Window, right: Window) -> Alignment:
    shift = right.pitches[0] - left.pitches[0]
    pairs = tuple((index, index) for index in range(len(left.notes)))
    return Alignment(
        shift=shift,
        edits=0,
        insertions=(),
        deletions=(),
        substitutions=(),
        matched_pairs=pairs,
        max_timing_error=0.0,
        mean_timing_error=0.0,
        max_duration_error=0.0,
        mean_duration_error=0.0,
        similarity=1.0,
    )


def _timing_alignment(
    left: Window, right: Window, allowed: int, tolerance: float
) -> tuple[tuple[int, int], ...] | None:
    """Greedily maximize monotone onset matches under the terminal-gap policy."""
    m, n = len(left.notes), len(right.notes)
    if abs(left.onsets[0] - right.onsets[0]) > tolerance:
        return None
    if abs(left.onsets[-1] - right.onsets[-1]) > tolerance:
        return None
    i = j = 1
    pairs = [(0, 0)]
    while i < m - 1 and j < n - 1:
        delta = left.onsets[i] - right.onsets[j]
        if abs(delta) <= tolerance:
            pairs.append((i, j))
            i += 1
            j += 1
        elif delta < 0:
            i += 1
        else:
            j += 1
    pairs.append((m - 1, n - 1))
    timing_edits = (m - len(pairs)) + (n - len(pairs))
    return tuple(pairs) if timing_edits <= allowed else None


def _anchor_alignment(
    left: Window,
    right: Window,
    pairs: tuple[tuple[int, int], ...],
    cfg: AlignedConfig,
) -> Alignment | None:
    """Verify a timing-derived alignment without a pitch edit matrix."""
    allowed = _allowed_edits(len(left.notes), len(right.notes), cfg)
    left_matched = {left_index for left_index, _ in pairs}
    right_matched = {right_index for _, right_index in pairs}
    deletions = tuple(index for index in range(len(left.notes)) if index not in left_matched)
    insertions = tuple(index for index in range(len(right.notes)) if index not in right_matched)
    shifts = Counter(
        right.pitches[right_index] - left.pitches[left_index]
        for left_index, right_index in pairs
    )
    best = None
    for shift, _ in sorted(
        shifts.items(), key=lambda item: (-item[1], abs(item[0]), item[0])
    )[: cfg.max_shift_candidates]:
        substitutions = tuple(
            (left_index, right_index)
            for left_index, right_index in pairs
            if right.pitches[right_index] - left.pitches[left_index] != shift
        )
        edits = len(insertions) + len(deletions) + len(substitutions)
        if edits > allowed:
            continue
        timing_errors = tuple(
            abs(left.onsets[left_index] - right.onsets[right_index])
            for left_index, right_index in pairs
        )
        duration_errors = tuple(
            abs(left.durations[left_index] - right.durations[right_index])
            for left_index, right_index in pairs
        )
        excessive = sum(error > cfg.duration_tolerance for error in duration_errors)
        if excessive > math.floor(len(duration_errors) * cfg.duration_error_fraction):
            continue
        mean_duration = statistics.mean(duration_errors) if duration_errors else 0.0
        if mean_duration > cfg.duration_tolerance:
            continue
        mean_timing = statistics.mean(timing_errors) if timing_errors else 0.0
        edit_quality = 1 - edits / max(len(left.notes), len(right.notes))
        timing_quality = 1 - mean_timing / max(cfg.timing_tolerance, 1e-12)
        duration_quality = 1 - min(
            1.0, mean_duration / max(cfg.duration_tolerance, 1e-12)
        )
        result = Alignment(
            shift=shift,
            edits=edits,
            insertions=insertions,
            deletions=deletions,
            substitutions=substitutions,
            matched_pairs=pairs,
            max_timing_error=max(timing_errors, default=0.0),
            mean_timing_error=mean_timing,
            max_duration_error=max(duration_errors, default=0.0),
            mean_duration_error=mean_duration,
            similarity=0.7 * edit_quality + 0.2 * timing_quality + 0.1 * duration_quality,
        )
        if best is None or (result.edits, -result.similarity, abs(result.shift), result.shift) < (
            best.edits,
            -best.similarity,
            abs(best.shift),
            best.shift,
        ):
            best = result
    return best


def _pitch_feasible(
    left: Window,
    right: Window,
    pairs: tuple[tuple[int, int], ...],
    allowed: int,
) -> bool:
    """Return whether one fixed shift can fit inside the edit allowance."""
    gap_edits = len(left.notes) + len(right.notes) - 2 * len(pairs)
    substitution_budget = allowed - gap_edits
    if substitution_budget < 0:
        return False
    shift_counts = Counter(
        right.pitches[right_index] - left.pitches[left_index]
        for left_index, right_index in pairs
    )
    return max(shift_counts.values(), default=0) >= len(pairs) - substitution_budget


def _boundary(candidate: Window, stream, song: MidiSong) -> float:
    before = (
        (candidate.start - stream[candidate.index - 1].end) / song.ticks_per_beat
        if candidate.index
        else 1.0
    )
    after_index = candidate.index + len(candidate.notes)
    after = (
        (stream[after_index].start - candidate.end) / song.ticks_per_beat
        if after_index < len(stream)
        else 1.0
    )
    meter_tick = max((tick for tick, _, _ in song.meters if tick <= candidate.start), default=0)
    bar = bar_length(song, candidate.start)
    position = (candidate.start - meter_tick) % bar
    bar_aligned = min(position, bar - position) <= song.ticks_per_beat / 12
    return (
        min(1.0, max(0.0, before) * 2)
        + min(1.0, max(0.0, after) * 2)
        + float(bar_aligned)
    ) / 3


def _score(prototype: Window, occurrences, stream, song: MidiSong) -> tuple[float, dict]:
    quality = statistics.mean(alignment.similarity for _, alignment in occurrences)
    support = min(1.0, math.log2(len(occurrences)) / 3)
    length = min(1.0, len(prototype.notes) / 16)
    boundary = statistics.mean(_boundary(candidate, stream, song) for candidate, _ in occurrences)
    terms = {
        "match_quality": quality,
        "support": support,
        "note_length": length,
        "boundary": boundary,
    }
    score = 0.65 * quality + 0.15 * support + 0.12 * length + 0.08 * boundary
    return round(score, 8), {name: round(value, 8) for name, value in terms.items()}


def _occurrence(candidate: Window, alignment: Alignment) -> dict:
    return {
        "start_tick": candidate.start,
        "end_tick": candidate.end,
        "note_index": candidate.index,
        "note_count": len(candidate.notes),
        "transpose_semitones": alignment.shift,
        "similarity": round(alignment.similarity, 8),
        "edit_count": alignment.edits,
        "inserted_note_indices": list(alignment.insertions),
        "deleted_prototype_note_indices": list(alignment.deletions),
        "substituted_note_pairs": [list(pair) for pair in alignment.substitutions],
        "matched_note_pairs": [list(pair) for pair in alignment.matched_pairs],
        "max_timing_error_beats": round(alignment.max_timing_error, 8),
        "max_duration_error_beats": round(alignment.max_duration_error, 8),
        "source_verified": True,
    }


def detect_aligned_part(song: MidiSong, part: Part, cfg: AlignedConfig) -> tuple[list[dict], dict]:
    stats = {
        "part_index": part.index,
        "input_notes": len(part.notes),
        "skyline_notes": 0,
        "windows_considered": 0,
        "windows": 0,
        "comparisons": 0,
        "proposed_pairs": 0,
        "seed_support_rejections": 0,
        "exact_signature_hits": 0,
        "alignment_cache_hits": 0,
        "dp_calls": 0,
        "overlap_rejections": 0,
        "length_rejections": 0,
        "terminal_timing_rejections": 0,
        "timing_feasibility_rejections": 0,
        "pitch_feasibility_rejections": 0,
        "anchor_alignment_hits": 0,
        "anchor_alignment_fallbacks": 0,
        "anchor_alignment_rejections": 0,
        "groups": 0,
        "repeat_groups": 0,
        "overlapping_occurrences_removed": 0,
        "saturated_seed_buckets": 0,
        "note_limit_reached": False,
        "window_limit_reached": False,
        "comparison_limit_reached": False,
        "group_limit_reached": False,
        "candidate_limit_reached": False,
        "candidates_truncated": 0,
    }
    if part.is_drum:
        return [], stats
    stream = skyline(part, song.ticks_per_beat, cfg.onset_merge_beats)
    stats["skyline_notes"] = len(stream)
    stats["onset_notes_removed_fraction"] = round(1 - len(stream) / max(1, len(part.notes)), 8)
    if len(stream) > cfg.max_stream_notes:
        stats["note_limit_reached"] = True
        return [], stats

    groups: list[list[Window]] = []
    seed_index: dict[tuple, list[int]] = defaultdict(list)
    exact_index: dict[tuple, int] = {}
    alignment_cache: dict[tuple[int, int, int, int], Alignment | None] = {}
    saturated: set[tuple] = set()
    stop = False
    for count in range(cfg.max_notes, cfg.min_notes - 1, -1):
        if count > len(stream):
            continue
        for start in range(len(stream) - count + 1):
            if stats["windows_considered"] >= cfg.max_windows:
                stats["window_limit_reached"] = True
                stop = True
                break
            stats["windows_considered"] += 1
            candidate = _valid_window(stream, start, count, song, cfg)
            if candidate is None:
                continue
            stats["windows"] += 1
            query_keys = _seed_keys(candidate, cfg)
            index_keys = query_keys
            exact_key = _exact_key(candidate)
            exact_group = exact_index.get(exact_key)
            if exact_group is not None:
                representative = groups[exact_group][0]
                result = _exact_alignment(representative, candidate)
                groups[exact_group].append(candidate)
                alignment_cache[
                    (representative.index, len(representative.notes), candidate.index, len(candidate.notes))
                ] = result
                stats["exact_signature_hits"] += 1
                continue
            # Phase-shifted bucket keys deliberately overlap. Requiring
            # multiple key votes removes accidental one-key collisions
            # before the onset and pitch verifiers. Six-note windows still
            # emit four phase variants for each usable single anchor.
            group_votes = Counter(
                group for key in query_keys for group in seed_index[key]
            )
            stats["seed_support_rejections"] += sum(
                votes < cfg.min_seed_support for votes in group_votes.values()
            )
            candidate_groups = sorted(
                group
                for group, votes in group_votes.items()
                if votes >= cfg.min_seed_support
            )
            best: tuple[float, int] | None = None
            for group_index in candidate_groups:
                stats["proposed_pairs"] += 1
                representative = groups[group_index][0]
                if not (candidate.end <= representative.start or representative.end <= candidate.start):
                    stats["overlap_rejections"] += 1
                    continue
                allowed = _allowed_edits(len(representative.notes), len(candidate.notes), cfg)
                if abs(len(representative.notes) - len(candidate.notes)) > allowed:
                    stats["length_rejections"] += 1
                    continue
                # With terminal gaps and tempo warping forbidden, the last
                # aligned onset must retain the prototype's relative time.
                if abs(representative.onsets[-1] - candidate.onsets[-1]) > cfg.timing_tolerance:
                    stats["terminal_timing_rejections"] += 1
                    continue
                timing_pairs = _timing_alignment(
                    representative, candidate, allowed, cfg.timing_tolerance
                )
                if timing_pairs is None:
                    stats["timing_feasibility_rejections"] += 1
                    continue
                if not _pitch_feasible(
                    representative, candidate, timing_pairs, allowed
                ):
                    stats["pitch_feasibility_rejections"] += 1
                    continue
                result = _anchor_alignment(
                    representative, candidate, timing_pairs, cfg
                )
                if result is not None:
                    stats["anchor_alignment_hits"] += 1
                    alignment_cache[
                        (
                            representative.index,
                            len(representative.notes),
                            candidate.index,
                            len(candidate.notes),
                        )
                    ] = result
                    if best is None or result.similarity > best[0]:
                        best = (result.similarity, group_index)
                    continue
                stats["anchor_alignment_rejections"] += 1
            if stop:
                break
            if best is None:
                if len(groups) >= cfg.max_groups:
                    stats["group_limit_reached"] = True
                    stop = True
                    break
                group_index = len(groups)
                groups.append([candidate])
                exact_index[exact_key] = group_index
                for key in index_keys:
                    bucket = seed_index[key]
                    if len(bucket) < cfg.max_bucket:
                        bucket.append(group_index)
                    else:
                        saturated.add(key)
            else:
                group_index = best[1]
                groups[group_index].append(candidate)
        if stop:
            break
    stats["saturated_seed_buckets"] = len(saturated)
    stats["groups"] = len(groups)

    output = []
    for members in groups:
        unique = {(member.index, len(member.notes)): member for member in members}
        members = list(unique.values())
        if len(members) < 2:
            continue
        prototype = min(members, key=lambda item: (item.start, item.end, len(item.notes), item.index))
        verified = []
        for member in members:
            cache_key = (
                prototype.index,
                len(prototype.notes),
                member.index,
                len(member.notes),
            )
            if cache_key in alignment_cache:
                result = alignment_cache[cache_key]
                stats["alignment_cache_hits"] += 1
            elif _exact_key(prototype) == _exact_key(member):
                result = _exact_alignment(prototype, member)
                stats["exact_signature_hits"] += 1
                alignment_cache[cache_key] = result
            else:
                allowed = _allowed_edits(len(prototype.notes), len(member.notes), cfg)
                timing_pairs = _timing_alignment(
                    prototype, member, allowed, cfg.timing_tolerance
                )
                result = None
                if timing_pairs is not None and _pitch_feasible(
                    prototype, member, timing_pairs, allowed
                ):
                    result = _anchor_alignment(
                        prototype, member, timing_pairs, cfg
                    )
                    if result is not None:
                        stats["anchor_alignment_hits"] += 1
                if result is None:
                    # A timing-first greedy alignment can miss another valid
                    # monotone path. Use the banded DP only for those residual
                    # cases and keep that fallback explicitly bounded.
                    stats["anchor_alignment_fallbacks"] += 1
                    if stats["comparisons"] >= cfg.max_comparisons:
                        stats["comparison_limit_reached"] = True
                        continue
                    shifts = _shift_candidates(
                        prototype, member, allowed, cfg.max_shift_candidates
                    )
                    stats["comparisons"] += 1
                    stats["dp_calls"] += 1
                    result = _align_with_shifts(prototype, member, cfg, shifts)
                alignment_cache[cache_key] = result
            if result is not None:
                verified.append((member, result))
        occurrences = _nonoverlap(verified)
        stats["overlapping_occurrences_removed"] += len(verified) - len(occurrences)
        if len(occurrences) < 2:
            continue
        stats["repeat_groups"] += 1
        score, components = _score(prototype, occurrences, stream, song)
        output.append(
            {
                "family_id": _family_id(prototype),
                "part_index": part.index,
                "source_track": part.track,
                "channel": part.channel,
                "program": part.program,
                "part_name": part.name,
                "note_count": len(prototype.notes),
                "start_tick": prototype.start,
                "end_tick": prototype.end,
                "duration_beats": round((prototype.end - prototype.start) / song.ticks_per_beat, 8),
                "prototype_note_index": prototype.index,
                "pitches": list(prototype.pitches),
                "onsets_beats": [round(value, 8) for value in prototype.onsets],
                "durations_beats": [round(value, 8) for value in prototype.durations],
                "velocities": [note.velocity for note in prototype.notes],
                "recurrence_score": score,
                "score_components": components,
                "raw_occurrence_count": len(verified),
                "occurrence_count": len(occurrences),
                "matcher_flags": {
                    "source_verified": True,
                    "monotone_alignment": True,
                    "fixed_transposition": True,
                    "tempo_warp": False,
                    "terminal_gaps_allowed": False,
                    "similarity_only_acceptance": False,
                },
                "occurrences": [_occurrence(candidate, result) for candidate, result in occurrences],
            }
        )
    output.sort(
        key=lambda item: (
            -item["recurrence_score"],
            -item["note_count"],
            item["start_tick"],
            item["family_id"],
        )
    )
    stats["candidates_truncated"] = max(0, len(output) - cfg.max_candidates)
    stats["candidate_limit_reached"] = bool(stats["candidates_truncated"])
    return output[: cfg.max_candidates], stats


def _redundant(candidate: dict, selected: dict) -> bool:
    if candidate["family_id"] == selected["family_id"]:
        return True
    if candidate["part_index"] != selected["part_index"]:
        return False
    covered = 0
    for left in candidate["occurrences"]:
        for right in selected["occurrences"]:
            overlap = max(
                0,
                min(left["end_tick"], right["end_tick"])
                - max(left["start_tick"], right["start_tick"]),
            )
            shorter = max(
                1,
                min(
                    left["end_tick"] - left["start_tick"],
                    right["end_tick"] - right["start_tick"],
                ),
            )
            if overlap / shorter >= 0.7:
                covered += 1
                break
    return covered / len(candidate["occurrences"]) >= 0.7


def _prefer_boundary_extension(candidate: dict, selected: dict) -> bool:
    """Prefer a verified terminal-note extension over its truncated sibling."""
    if candidate["part_index"] != selected["part_index"]:
        return False
    if candidate["note_count"] <= selected["note_count"]:
        return False
    if candidate["occurrence_count"] != selected["occurrence_count"]:
        return False
    if candidate["recurrence_score"] + 0.02 < selected["recurrence_score"]:
        return False
    if candidate["score_components"]["boundary"] <= selected["score_components"]["boundary"]:
        return False
    for inner in selected["occurrences"]:
        if not any(
            outer["start_tick"] <= inner["start_tick"]
            and outer["end_tick"] >= inner["end_tick"]
            and (
                outer["start_tick"] == inner["start_tick"]
                or outer["end_tick"] == inner["end_tick"]
            )
            for outer in candidate["occurrences"]
        ):
            return False
    return True


def extract_aligned(song: MidiSong, cfg: AlignedConfig | None = None) -> dict:
    """Extract insertion and deletion tolerant recurring melodic phrases."""
    cfg = cfg or AlignedConfig()
    if not isinstance(cfg, AlignedConfig):
        raise TypeError("cfg must be an AlignedConfig")
    candidates, stats = [], []
    for part in song.parts:
        found, audit = detect_aligned_part(song, part, cfg)
        candidates.extend(found)
        stats.append(audit)
    candidates.sort(
        key=lambda item: (
            -item["recurrence_score"],
            -item["note_count"],
            item["part_index"],
            item["start_tick"],
            item["family_id"],
        )
    )
    selected = []
    for candidate in candidates:
        redundant_index = next(
            (index for index, prior in enumerate(selected) if _redundant(candidate, prior)),
            None,
        )
        if redundant_index is None:
            selected.append(candidate)
        elif _prefer_boundary_extension(candidate, selected[redundant_index]):
            selected[redundant_index] = candidate
        if len(selected) == cfg.top_k:
            break
    limit_keys = (
        "note_limit_reached",
        "window_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
    )
    search_limited = any(any(part[key] for key in limit_keys) or part["saturated_seed_buckets"] for part in stats)
    return {
        "config": asdict(cfg),
        "phrases": selected,
        "candidate_count": len(candidates),
        "raw_repeat_group_count": sum(part["repeat_groups"] for part in stats),
        "shortlisted_candidate_count": len(candidates),
        "curation_truncated": any(part["candidate_limit_reached"] for part in stats),
        "search_limited": search_limited,
        "part_stats": stats,
    }


def run_development_benchmark(output: Path, seeds: int = 1000) -> dict:
    """Evaluate only the frozen development seed namespace."""
    from .evaluate import aggregate_results, bootstrap_intervals, generate_cases, score_case
    from .phrases import Config, extract

    started = time.monotonic()
    cases = [case for case in generate_cases(seeds) if case.split == "development"]
    aligned_cfg = AlignedConfig(top_k=10)
    baseline_cfg = Config(mode="approximate", top_k=10)
    rows = {"aligned": [], "baseline_approximate": []}
    profile_keys = (
        "proposed_pairs",
        "seed_support_rejections",
        "exact_signature_hits",
        "alignment_cache_hits",
        "dp_calls",
        "comparisons",
        "overlap_rejections",
        "length_rejections",
        "terminal_timing_rejections",
        "timing_feasibility_rejections",
        "pitch_feasibility_rejections",
        "anchor_alignment_hits",
        "anchor_alignment_fallbacks",
        "anchor_alignment_rejections",
        "saturated_seed_buckets",
    )
    aligned_profile = {key: 0 for key in profile_keys}
    for case in cases:
        for name, detector, config in (
            ("aligned", extract_aligned, aligned_cfg),
            ("baseline_approximate", extract, baseline_cfg),
        ):
            case_started = time.monotonic()
            result = detector(case.song, config)
            row = score_case(case, result["phrases"], time.monotonic() - case_started)
            row["search_limited"] = result["search_limited"]
            row["candidate_count_before_reranking"] = result["candidate_count"]
            rows[name].append(row)
            if name == "aligned":
                for part_stats in result["part_stats"]:
                    for key in profile_keys:
                        aligned_profile[key] += part_stats.get(key, 0)
    aggregate = {
        "scope": "development_only",
        "generated_case_count": seeds,
        "evaluated_case_count": len(cases),
        "development_seed_namespace": 10_000_000,
        "iou_threshold": 0.8,
        "aligned_config": asdict(aligned_cfg),
        "baseline_config": asdict(baseline_cfg),
        "methods": {},
        "wall_seconds": time.monotonic() - started,
        "claim_boundary": "symbolic planted recurrence only; real-corpus quality and human memorability are unproven",
        "alignment_exclusion": "inserted or deleted first and last notes are rejected because terminal gaps make boundaries underdetermined",
        "candidate_generation_limitation": "six separated anchor pairs are a bounded heuristic; a recurrence can be missed when edits disrupt all selected anchors",
    }
    for index, (name, method_rows) in enumerate(rows.items()):
        summary = aggregate_results(method_rows)
        summary["bootstrap_ci95"] = bootstrap_intervals(method_rows, 1000, 8800 + index)
        summary["search_limited_cases"] = sum(row["search_limited"] for row in method_rows)
        if name == "aligned":
            summary["profile_counters"] = aligned_profile
        aggregate["methods"][name] = summary
    output.mkdir(parents=True, exist_ok=True)
    (output / "raw_results.json").write_text(
        json.dumps({"aggregate_parameters": {"seeds": seeds}, "rows": rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    aligned = aggregate["methods"]["aligned"]
    baseline = aggregate["methods"]["baseline_approximate"]
    report = (
        "# Aligned detector development benchmark\n\n"
        f"Cases: {len(cases)} development cases from `generate_cases({seeds})`. Test cases were not evaluated.\n\n"
        "| Method | Candidate F1 | Occurrence F1 | Top 1 recovery | Negative false positive cases | Mean seconds |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: |\n"
        f"| aligned | {aligned['candidate']['f1']:.3f} | {aligned['occurrence']['f1']:.3f} | "
        f"{aligned['top1_recovery']:.3f} | {aligned['false_positive_case_count']} | {aligned['runtime_seconds']['mean']:.4f} |\n"
        f"| baseline approximate | {baseline['candidate']['f1']:.3f} | {baseline['occurrence']['f1']:.3f} | "
        f"{baseline['top1_recovery']:.3f} | {baseline['false_positive_case_count']} | {baseline['runtime_seconds']['mean']:.4f} |\n\n"
        "Aligned profile counters are recorded in `aggregate.json`, including proposed pairs, seed and feasibility rejections, exact and cache hits and DP calls.\n\n"
        "The aligned matcher excludes insertion or deletion of the first or last note because terminal gaps make boundaries underdetermined. Boundary pitch substitutions remain eligible.\n\n"
        "Candidate generation uses six separated anchor pairs. It can miss a recurrence when edits disrupt every selected anchor.\n\n"
        "These results measure planted symbolic recurrence. Real-corpus phrase quality and human memorability are unproven.\n"
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("research_local/aligned_dev"))
    parser.add_argument("--seeds", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.seeds < 2:
        raise ValueError("seeds must be at least 2")
    result = run_development_benchmark(args.output, args.seeds)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
