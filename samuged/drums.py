"""Bounded discovery of recurring drum patterns in meter aligned windows.

Drum pitches are General MIDI kit identities, not melodic pitches. Matching never
transposes them. The synthetic ensemble returned by :func:`drum_part` combines
all drum parts for export while phrase records retain their source part indices.
Bar zero is assumed at tick zero and reset at each meter change. Pickups are not
inferred from MIDI note content.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from hashlib import sha256
import json
import math

from .midi import MidiSong, Note, Part


@dataclass(frozen=True)
class DrumConfig:
    """Conservative fixed bounds for local recurring drum pattern extraction."""

    bar_counts: tuple[int, ...] = (1, 2, 4)
    mode: str = "tolerant"
    timing_tolerance_beats: float = 1 / 12
    hit_error_fraction: float = 0.10
    min_hits: int = 8
    min_pitches: int = 2
    max_hits: int = 100_000
    max_window_hits: int = 4_096
    max_windows: int = 12_000
    max_comparisons: int = 60_000
    max_bucket: int = 64
    max_candidates: int = 80
    top_k: int = 3

    def __post_init__(self) -> None:
        if self.mode not in {"exact", "tolerant"}:
            raise ValueError("mode must be exact or tolerant")
        if not self.bar_counts or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in {1, 2, 4}
            for value in self.bar_counts
        ):
            raise ValueError("bar_counts must contain one or more of 1, 2 and 4")
        if len(set(self.bar_counts)) != len(self.bar_counts):
            raise ValueError("bar_counts must not contain duplicates")
        if not math.isfinite(self.timing_tolerance_beats) or not (
            0 <= self.timing_tolerance_beats <= 0.25
        ):
            raise ValueError("timing_tolerance_beats must be between 0 and 0.25")
        if not math.isfinite(self.hit_error_fraction) or not (
            0 <= self.hit_error_fraction <= 0.10
        ):
            raise ValueError("hit_error_fraction must be between 0 and 0.10")
        for name, minimum in (("min_hits", 1), ("min_pitches", 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "max_hits",
            "max_window_hits",
            "max_windows",
            "max_comparisons",
            "max_bucket",
            "max_candidates",
            "top_k",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.top_k > self.max_candidates:
            raise ValueError("top_k must not exceed max_candidates")


@dataclass(frozen=True)
class _Window:
    start: int
    end: int
    bar_count: int
    numerator: int
    denominator: int
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class _Occurrence:
    window: _Window
    similarity: float


def _validate_song(song: MidiSong) -> None:
    if not isinstance(song, MidiSong):
        raise TypeError("song must be a MidiSong")
    if (
        isinstance(song.ticks_per_beat, bool)
        or not isinstance(song.ticks_per_beat, int)
        or song.ticks_per_beat <= 0
    ):
        raise ValueError("ticks_per_beat must be a positive integer")


def _validated_note(note: Note) -> None:
    if not isinstance(note, Note):
        raise TypeError("drum parts must contain Note instances")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (
        note.start, note.end, note.pitch, note.velocity
    )):
        raise TypeError("drum note fields must be integers")
    if note.start < 0 or note.end <= note.start:
        raise ValueError("drum note timing must have a nonnegative start and positive duration")
    if not 0 <= note.pitch <= 127 or not 1 <= note.velocity <= 127:
        raise ValueError("drum note pitch or velocity is outside MIDI range")


def _drum_metadata(song: MidiSong) -> tuple[list[int], list[int], list[int]]:
    parts = [part for part in song.parts if part.is_drum]
    return (
        sorted({part.index for part in parts}),
        sorted({part.track for part in parts}),
        sorted({part.program for part in parts}),
    )


def drum_part(song: MidiSong) -> Part:
    """Return a deterministic ensemble containing all distinct drum strikes.

    Exact duplicates from multiple source parts are merged by ``(start, pitch)``.
    Their maximum end and velocity are retained, then each gate is clipped at
    the next hit of the same pitch. This prevents ambiguous nested note-offs
    when independent source tracks are merged onto the one drum channel. Hit
    onsets and velocities are preserved; gate lengths are not matching features.
    The synthetic part uses index
    zero because the MIDI exporter validates source-like indices. Extracted phrase
    records use ``part_index=-1`` to state that they belong to an aggregate.
    """

    _validate_song(song)
    source_indices, source_tracks, kit_programs = _drum_metadata(song)
    merged: dict[tuple[int, int], tuple[int, int]] = {}
    drum_parts = sorted(
        (part for part in song.parts if part.is_drum),
        key=lambda part: (part.index, part.track, part.program, part.name),
    )
    for part in drum_parts:
        for note in part.notes:
            _validated_note(note)
            key = (note.start, note.pitch)
            end, velocity = merged.get(key, (note.end, note.velocity))
            merged[key] = (max(end, note.end), max(velocity, note.velocity))

    notes = [
        Note(start, end, pitch, velocity)
        for (start, pitch), (end, velocity) in sorted(merged.items())
    ]
    next_onset: dict[int, int] = {}
    for note in reversed(notes):
        if note.pitch in next_onset:
            note.end = min(note.end, next_onset[note.pitch])
        next_onset[note.pitch] = note.start
    program = kit_programs[0] if len(kit_programs) == 1 else 0
    name = (
        "drum ensemble; source_part_indices="
        + json.dumps(source_indices, separators=(",", ":"))
        + "; source_tracks="
        + json.dumps(source_tracks, separators=(",", ":"))
        + "; kit_programs="
        + json.dumps(kit_programs, separators=(",", ":"))
    )
    return Part(
        index=0,
        track=0,
        channel=9,
        program=program,
        name=name,
        is_drum=True,
        notes=notes,
    )


def _meters(song: MidiSong) -> list[tuple[int, int, int]]:
    by_tick: dict[int, tuple[int, int]] = {}
    for change in song.meters:
        if not isinstance(change, tuple) or len(change) != 3:
            raise ValueError("meter changes must be (tick, numerator, denominator)")
        tick, numerator, denominator = change
        if any(isinstance(value, bool) or not isinstance(value, int) for value in change):
            raise TypeError("meter fields must be integers")
        if tick < 0 or numerator <= 0 or denominator <= 0:
            raise ValueError("meter fields must be positive except for a zero tick")
        if denominator & (denominator - 1):
            raise ValueError("meter denominator must be a power of two")
        by_tick[tick] = (numerator, denominator)
    if 0 not in by_tick:
        by_tick[0] = (4, 4)
    return [(tick, *by_tick[tick]) for tick in sorted(by_tick)]


def _round_fraction(value: Fraction) -> int:
    """Round a nonnegative rational tick position to its nearest source tick."""

    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _make_windows(
    song: MidiSong, notes: list[Note], cfg: DrumConfig, stats: dict
) -> list[_Window]:
    if not notes:
        return []
    meters = _meters(song)
    ppq = song.ticks_per_beat
    final_note_end = max(note.end for note in notes)
    starts = [note.start for note in notes]
    windows: list[_Window] = []

    for meter_index, (origin, numerator, denominator) in enumerate(meters):
        next_change = meters[meter_index + 1][0] if meter_index + 1 < len(meters) else None
        if origin >= final_note_end and next_change is None:
            continue
        bar_ticks = Fraction(ppq * numerator * 4, denominator)
        if next_change is None:
            extent = max(Fraction(0), Fraction(final_note_end - origin, 1))
            available_bars = _ceil_fraction(extent / bar_ticks)
        else:
            if next_change <= origin:
                continue
            available_bars = int(Fraction(next_change - origin, 1) // bar_ticks)
        if available_bars <= 0:
            continue
        stats["meter_segments"] += 1

        for bar_offset in range(available_bars):
            for bar_count in sorted(cfg.bar_counts, reverse=True):
                if stats["window_attempts"] >= cfg.max_windows:
                    stats["window_limit_reached"] = True
                    return sorted(windows, key=lambda item: (item.start, -item.bar_count, item.end))
                stats["window_attempts"] += 1
                if bar_offset + bar_count > available_bars:
                    continue
                stats["windows_considered"] += 1
                start = _round_fraction(Fraction(origin) + bar_ticks * bar_offset)
                end = _round_fraction(Fraction(origin) + bar_ticks * (bar_offset + bar_count))
                if end <= start:
                    continue
                left = bisect_left(starts, start)
                right = bisect_left(starts, end, lo=left)
                selected = tuple(notes[left:right])
                if len(selected) > cfg.max_window_hits:
                    stats["oversized_windows"] += 1
                    continue
                if len(selected) < cfg.min_hits:
                    continue
                if len({note.pitch for note in selected}) < cfg.min_pitches:
                    continue
                windows.append(
                    _Window(start, end, bar_count, numerator, denominator, selected)
                )
    return sorted(windows, key=lambda item: (item.start, -item.bar_count, item.end))


def _relative_onset(note: Note, window: _Window, ppq: int) -> Fraction:
    return Fraction(note.start - window.start, ppq)


def _canonical_payload(window: _Window, ppq: int) -> dict:
    span = Fraction(window.end - window.start, ppq)
    hits = []
    for note in window.notes:
        onset = _relative_onset(note, window, ppq)
        hits.append((note.pitch, onset.numerator, onset.denominator))
    return {
        "window_beats": (span.numerator, span.denominator),
        "hits": hits,
    }


def _family_id(window: _Window, ppq: int) -> str:
    payload = json.dumps(
        _canonical_payload(window, ppq),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()


def _exact_key(window: _Window, ppq: int) -> tuple:
    payload = _canonical_payload(window, ppq)
    return (
        window.bar_count,
        window.numerator,
        window.denominator,
        tuple(payload["window_beats"]),
        tuple(tuple(hit) for hit in payload["hits"]),
    )


def _seed_keys(window: _Window, ppq: int) -> tuple[tuple, ...]:
    span = Fraction(window.end - window.start, ppq)
    return tuple(
        (
            window.bar_count,
            window.numerator,
            window.denominator,
            span.numerator,
            span.denominator,
            pitch,
        )
        for pitch in sorted({note.pitch for note in window.notes})
    )


def _times_by_pitch(window: _Window, ppq: int) -> dict[int, list[float]]:
    result: dict[int, list[float]] = defaultdict(list)
    for note in window.notes:
        result[note.pitch].append(float(_relative_onset(note, window, ppq)))
    return result


def _tolerant_match(
    reference: _Window, candidate: _Window, ppq: int, cfg: DrumConfig
) -> float | None:
    if reference.bar_count != candidate.bar_count:
        return None
    if (reference.numerator, reference.denominator) != (
        candidate.numerator,
        candidate.denominator,
    ):
        return None
    if Fraction(reference.end - reference.start, ppq) != Fraction(
        candidate.end - candidate.start, ppq
    ):
        return None
    reference_count = len(reference.notes)
    candidate_count = len(candidate.notes)
    allowed_errors = math.floor(
        max(reference_count, candidate_count) * cfg.hit_error_fraction
    )
    if abs(reference_count - candidate_count) > allowed_errors:
        return None

    left = _times_by_pitch(reference, ppq)
    right = _times_by_pitch(candidate, ppq)
    matched = 0
    timing_error = 0.0
    for pitch in sorted(set(left) | set(right)):
        a = left.get(pitch, [])
        b = right.get(pitch, [])
        i = 0
        j = 0
        while i < len(a) and j < len(b):
            difference = b[j] - a[i]
            if abs(difference) <= cfg.timing_tolerance_beats:
                matched += 1
                timing_error += abs(difference)
                i += 1
                j += 1
            elif difference < 0:
                j += 1
            else:
                i += 1

    unmatched = reference_count + candidate_count - 2 * matched
    if unmatched > allowed_errors:
        return None
    match_fraction = matched / max(reference_count, candidate_count)
    if cfg.timing_tolerance_beats == 0:
        timing_quality = 1.0
    else:
        timing_quality = 1 - min(
            1.0,
            timing_error / max(1, matched) / cfg.timing_tolerance_beats,
        )
    return 0.85 * match_fraction + 0.15 * timing_quality


def _nonoverlap(group: list[_Occurrence]) -> list[_Occurrence]:
    selected: list[_Occurrence] = []
    last_end = -1
    for occurrence in sorted(
        group,
        key=lambda item: (item.window.end, item.window.start, -item.similarity),
    ):
        if occurrence.window.start >= last_end:
            selected.append(occurrence)
            last_end = occurrence.window.end
    return sorted(selected, key=lambda item: item.window.start)


def _primitive_bar_period(window: _Window) -> int:
    """Return the shortest exact bar period represented by a window.

    Hit locations are normalized within each bar. This diagnostic prevents a
    four bar window made from one copied bar from receiving the same substance
    reward as a four bar phrase with distinct internal development.
    """

    if window.bar_count == 1:
        return 1
    span = window.end - window.start
    bar_span = Fraction(span, window.bar_count)
    profiles: list[list[tuple[int, int, int]]] = [
        [] for _ in range(window.bar_count)
    ]
    for note in window.notes:
        relative = note.start - window.start
        bar_index = min(window.bar_count - 1, int(Fraction(relative, 1) // bar_span))
        position = Fraction(relative, 1) / bar_span - bar_index
        profiles[bar_index].append((note.pitch, position.numerator, position.denominator))
    normalized = tuple(tuple(profile) for profile in profiles)
    for period in range(1, window.bar_count + 1):
        if window.bar_count % period == 0 and all(
            normalized[index] == normalized[index % period]
            for index in range(window.bar_count)
        ):
            return period
    return window.bar_count


def _score(
    prototype: _Window,
    occurrences: list[_Occurrence],
    notes: list[Note],
    ppq: int,
) -> tuple[float, dict[str, float]]:
    count = len(occurrences)
    support = min(1.0, math.log2(count) / 3)
    primitive_bar_period = _primitive_bar_period(prototype)
    bar_variation = primitive_bar_period / prototype.bar_count
    nominal_substance = {1: 0.45, 2: 0.75, 4: 1.0}[prototype.bar_count]
    bar_substance = nominal_substance * (0.45 + 0.55 * bar_variation)
    pitch_counts = Counter(note.pitch for note in prototype.notes)
    probabilities = [value / len(prototype.notes) for value in pitch_counts.values()]
    entropy = -sum(value * math.log2(value) for value in probabilities)
    entropy_scale = math.log2(max(2, len(pitch_counts)))
    distribution_diversity = min(1.0, entropy / entropy_scale)
    instrument_variety = min(1.0, (len(pitch_counts) - 1) / 5)
    diversity = (distribution_diversity + instrument_variety) / 2
    match_quality = sum(item.similarity for item in occurrences) / count
    density = min(1.0, len(prototype.notes) / (12 * prototype.bar_count))
    total_span = max(1, max(note.end for note in notes) - min(note.start for note in notes))
    coverage = min(
        1.0,
        sum(item.window.end - item.window.start for item in occurrences) / total_span,
    )
    components = {
        "support": support,
        "bar_substance": bar_substance,
        "bar_variation": bar_variation,
        "primitive_bar_period": float(primitive_bar_period),
        "instrument_diversity": diversity,
        "match_quality": match_quality,
        "hit_density": density,
        "coverage": coverage,
    }
    value = (
        0.27 * support
        + 0.26 * bar_substance
        + 0.17 * diversity
        + 0.15 * match_quality
        + 0.10 * density
        + 0.05 * coverage
    )
    return round(value, 8), {
        key: round(component, 8) for key, component in components.items()
    }


def _candidate(
    prototype: _Window,
    occurrences: list[_Occurrence],
    song: MidiSong,
    notes: list[Note],
    source_indices: list[int],
    source_tracks: list[int],
    kit_programs: list[int],
) -> dict:
    ppq = song.ticks_per_beat
    score, components = _score(prototype, occurrences, notes, ppq)
    return {
        "kind": "percussion",
        "duration_policy": "clip_at_next_same_pitch_hit",
        "family_id": _family_id(prototype, ppq),
        "part_index": -1,
        "source_part_indices": source_indices,
        "source_tracks": source_tracks,
        "channel": 9,
        "kit_programs": kit_programs,
        "bar_count": prototype.bar_count,
        "meter_numerator": prototype.numerator,
        "meter_denominator": prototype.denominator,
        "start_tick": prototype.start,
        "end_tick": prototype.end,
        "note_count": len(prototype.notes),
        "duration_beats": round((prototype.end - prototype.start) / ppq, 8),
        "recurrence_score": score,
        "score_components": components,
        "occurrence_count": len(occurrences),
        "occurrences": [
            {
                "start_tick": item.window.start,
                "end_tick": item.window.end,
                "similarity": round(item.similarity, 8),
                "transpose_semitones": 0,
            }
            for item in occurrences
        ],
        "pitches": [note.pitch for note in prototype.notes],
        "onsets_beats": [
            round((note.start - prototype.start) / ppq, 8)
            for note in prototype.notes
        ],
        "durations_beats": [
            round((note.end - note.start) / ppq, 8) for note in prototype.notes
        ],
        "velocities": [note.velocity for note in prototype.notes],
    }


def _overlap_fraction(left: dict, right: dict) -> float:
    covered = 0
    right_occurrences = right["occurrences"]
    right_index = 0
    for occurrence in left["occurrences"]:
        left_length = occurrence["end_tick"] - occurrence["start_tick"]
        while (
            right_index < len(right_occurrences)
            and right_occurrences[right_index]["end_tick"] <= occurrence["start_tick"]
        ):
            right_index += 1
        candidate_index = right_index
        found = False
        while (
            candidate_index < len(right_occurrences)
            and right_occurrences[candidate_index]["start_tick"] < occurrence["end_tick"]
        ):
            other = right_occurrences[candidate_index]
            overlap = max(
                0,
                min(occurrence["end_tick"], other["end_tick"])
                - max(occurrence["start_tick"], other["start_tick"]),
            )
            if overlap / max(
                1, min(left_length, other["end_tick"] - other["start_tick"])
            ) >= 0.8:
                found = True
                break
            candidate_index += 1
        if found:
            covered += 1
    return covered / max(1, len(left["occurrences"]))


def _redundant(candidate: dict, selected: dict) -> bool:
    if candidate["family_id"] == selected["family_id"]:
        return True
    left_pitches = set(candidate["pitches"])
    right_pitches = set(selected["pitches"])
    pitch_similarity = len(left_pitches & right_pitches) / max(
        1, len(left_pitches | right_pitches)
    )
    return pitch_similarity >= 0.8 and (
        _overlap_fraction(candidate, selected) >= 0.7
        or _overlap_fraction(selected, candidate) >= 0.7
    )


def extract_drums(
    song: MidiSong,
    cfg: DrumConfig | None = None,
    *,
    mode: str | None = None,
) -> dict:
    """Find recurring one, two and four bar drum patterns.

    Tolerant mode allows at most ``1/12`` beat timing error and at most ten
    percent missing or extra hits. Matching still requires identical drum pitch
    identities and at least two nonoverlapping occurrences.
    """

    _validate_song(song)
    cfg = cfg or DrumConfig()
    if not isinstance(cfg, DrumConfig):
        raise TypeError("cfg must be a DrumConfig")
    if mode is not None:
        cfg = replace(cfg, mode=mode)

    source_indices, source_tracks, kit_programs = _drum_metadata(song)
    source_hit_count = sum(
        len(part.notes) for part in song.parts if part.is_drum
    )
    ensemble = drum_part(song)
    notes = ensemble.notes
    stats = {
        "config": asdict(cfg),
        "mode": cfg.mode,
        "source_part_indices": source_indices,
        "source_tracks": source_tracks,
        "kit_programs": kit_programs,
        "input_drum_parts": sum(1 for part in song.parts if part.is_drum),
        "input_hits": source_hit_count,
        "merged_hits": len(notes),
        "duplicate_hits_removed": source_hit_count - len(notes),
        "meter_segments": 0,
        "window_attempts": 0,
        "windows_considered": 0,
        "oversized_windows": 0,
        "eligible_windows": 0,
        "comparisons": 0,
        "saturated_seed_buckets": 0,
        "window_limit_reached": False,
        "comparison_limit_reached": False,
        "hit_limit_reached": False,
        "raw_group_count": 0,
        "raw_candidate_count": 0,
        "candidate_count": 0,
        "candidates_truncated": 0,
        "candidate_limit_reached": False,
        "diversity_comparisons": 0,
        "diversity_pruned": 0,
        "selected_count": 0,
        "search_limited": False,
        "bar_origin_assumption": (
            "bar zero is tick zero and each meter change starts a new bar; "
            "pickup alignment is unverified"
        ),
    }
    if not notes:
        return {"phrases": [], "stats": stats}
    if len(notes) > cfg.max_hits:
        stats["hit_limit_reached"] = True
        stats["search_limited"] = True
        return {"phrases": [], "stats": stats}

    windows = _make_windows(song, notes, cfg, stats)
    stats["eligible_windows"] = len(windows)
    groups: list[list[_Occurrence]] = []
    comparison_limit = False

    if cfg.mode == "exact":
        group_by_key: dict[tuple, int] = {}
        for window in windows:
            key = _exact_key(window, song.ticks_per_beat)
            group_index = group_by_key.get(key)
            if group_index is None:
                group_index = len(groups)
                group_by_key[key] = group_index
                groups.append([])
            groups[group_index].append(_Occurrence(window, 1.0))
    else:
        seed_index: dict[tuple, list[int]] = defaultdict(list)
        saturated: set[tuple] = set()
        for window in windows:
            keys = _seed_keys(window, song.ticks_per_beat)
            possible = sorted(
                {group_index for key in keys for group_index in seed_index[key]}
            )
            best: tuple[float, int] | None = None
            for group_index in possible:
                if stats["comparisons"] >= cfg.max_comparisons:
                    stats["comparison_limit_reached"] = True
                    comparison_limit = True
                    break
                stats["comparisons"] += 1
                similarity = _tolerant_match(
                    groups[group_index][0].window,
                    window,
                    song.ticks_per_beat,
                    cfg,
                )
                if similarity is not None and (
                    best is None or similarity > best[0]
                ):
                    best = (similarity, group_index)
                    if similarity == 1.0:
                        break
            if comparison_limit:
                break
            if best is None:
                group_index = len(groups)
                groups.append([_Occurrence(window, 1.0)])
                for key in keys:
                    bucket = seed_index[key]
                    if len(bucket) < cfg.max_bucket:
                        bucket.append(group_index)
                    else:
                        saturated.add(key)
            else:
                groups[best[1]].append(_Occurrence(window, best[0]))
        stats["saturated_seed_buckets"] = len(saturated)

    stats["raw_group_count"] = len(groups)
    candidates = []
    for group in groups:
        occurrences = _nonoverlap(group)
        if len(occurrences) < 2:
            continue
        candidates.append(
            _candidate(
                group[0].window,
                occurrences,
                song,
                notes,
                source_indices,
                source_tracks,
                kit_programs,
            )
        )
    candidates.sort(
        key=lambda item: (
            -item["recurrence_score"],
            -item["bar_count"],
            -item["note_count"],
            item["start_tick"],
            item["family_id"],
        )
    )
    stats["raw_candidate_count"] = len(candidates)
    stats["candidates_truncated"] = max(0, len(candidates) - cfg.max_candidates)
    stats["candidate_limit_reached"] = bool(stats["candidates_truncated"])
    candidates = candidates[: cfg.max_candidates]
    stats["candidate_count"] = len(candidates)
    stats["search_limited"] = bool(
        stats["window_limit_reached"]
        or stats["comparison_limit_reached"]
        or stats["hit_limit_reached"]
        or stats["candidate_limit_reached"]
        or stats["saturated_seed_buckets"]
        or stats["oversized_windows"]
    )

    selected = []
    for candidate in candidates:
        redundant = False
        for other in selected:
            stats["diversity_comparisons"] += 1
            if _redundant(candidate, other):
                redundant = True
                break
        if redundant:
            stats["diversity_pruned"] += 1
        else:
            selected.append(candidate)
        if len(selected) == cfg.top_k:
            break
    stats["selected_count"] = len(selected)
    return {"phrases": selected, "stats": stats}
