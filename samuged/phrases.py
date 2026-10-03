"""Bounded, beat-aware discovery of recurring melodic phrase candidates.

The score ranks repetition evidence, not human memorability. Matching uses a
representative per family, so similarity is never assumed to be transitive.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from statistics import median

from .midi import MidiSong, Note, Part, bar_length


@dataclass(frozen=True)
class Config:
    lengths: tuple[int, ...] = (6, 8, 12, 16, 24, 32)
    min_beats: float = 4.0
    max_beats: float = 32.0
    max_gap_beats: float = 2.0
    timing_tolerance: float = 0.125
    duration_tolerance: float = 0.25
    pitch_error_fraction: float = 0.125
    duration_error_fraction: float = 0.25
    onset_merge_beats: float = 1 / 24
    max_bucket: int = 192
    max_comparisons: int = 250000
    max_stream_notes: int = 12000
    max_windows: int = 80000
    max_candidates: int = 80
    top_k: int = 3
    mode: str = "approximate"

    def __post_init__(self):
        # ASVS 2.2.1: bound work and numeric configuration at the input boundary.
        if self.mode not in {"exact", "transposed", "approximate"}:
            raise ValueError("mode must be exact, transposed or approximate")
        if not self.lengths or len(self.lengths) > 24 or any(isinstance(n, bool) or not isinstance(n, int) or n < 4 or n > 128 for n in self.lengths):
            raise ValueError("phrase lengths must be between 4 and 128 notes")
        if not 0 < self.min_beats <= self.max_beats <= 128:
            raise ValueError("require 0 < min_beats <= max_beats <= 128")
        upper = {"max_bucket":1024, "max_comparisons":2000000, "max_stream_notes":20000,
                 "max_windows":200000, "max_candidates":10000, "top_k":100}
        for name, ceiling in upper.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer between 1 and {ceiling}")
        for name in ("timing_tolerance", "duration_tolerance", "pitch_error_fraction",
                     "duration_error_fraction", "onset_merge_beats", "max_gap_beats"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.pitch_error_fraction > 0.25 or self.duration_error_fraction > 0.5:
            raise ValueError("error fractions exceed supported conservative bounds")


def skyline(part: Part, ppq: int, merge_beats: float = 1 / 24) -> list[Note]:
    """Highest note in each near-simultaneous onset group, not a melody oracle.

    Groups are anchored at their first onset, avoiding unbounded chaining of
    nearby events. Source notes and sustained overlaps remain unmodified.
    """
    notes = sorted(part.notes, key=lambda n: (n.start, -n.pitch, -n.end, -n.velocity))
    out: list[Note] = []
    i = 0
    while i < len(notes):
        j = i + 1
        while j < len(notes) and notes[j].start - notes[i].start <= merge_beats * ppq:
            j += 1
        out.append(max(notes[i:j], key=lambda n: (n.pitch, n.end - n.start, n.velocity, -n.start)))
        i = j
    return out


@dataclass
class Window:
    index: int
    notes: list[Note]
    pitches: tuple[int, ...]
    onsets: tuple[float, ...]
    durations: tuple[float, ...]
    start: int
    end: int


def window(notes: list[Note], i: int, n: int, ppq: int) -> Window:
    selected = notes[i:i+n]
    start = selected[0].start
    return Window(i, selected, tuple(x.pitch for x in selected),
                  tuple((x.start - start) / ppq for x in selected),
                  tuple((x.end - x.start) / ppq for x in selected),
                  start, max(x.end for x in selected))


def signature(w: Window, transpose: bool = True) -> str:
    pitches = tuple(p - w.pitches[0] for p in w.pitches) if transpose else w.pitches
    # Content family, quantized to 1/24 quarter note; not a recording identity.
    payload = (pitches, tuple(round(x * 24) for x in w.onsets),
               tuple(round(x * 24) for x in w.durations))
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _seeds(w: Window):
    n = len(w.pitches)
    for offset in sorted(set(range(0, n-3, 4)) | {n-4}):
        p = w.pitches[offset:offset+4]
        intervals = tuple(p[i+1]-p[i] for i in range(3))
        # Two offset coarse grids reduce timing-boundary losses. Full-window
        # verification, rather than a seed collision, establishes recurrence.
        onset = w.onsets[offset:offset+4]
        for phase in (0.0, 0.25):
            rhythm = tuple(math.floor((t-onset[0]+phase)/0.5) for t in onset[1:])
            yield (n, offset, intervals, phase, rhythm)
        # Pitch-only fallback preserves timing-tolerant candidates at coarse
        # grid boundaries. Its extra collisions still require full verification.
        yield (n, offset, intervals, None, None)


def match(a: Window, b: Window, cfg: Config) -> tuple[float, int] | None:
    if len(a.pitches) != len(b.pitches):
        return None
    shift = 0 if cfg.mode == "exact" else int(median([q-p for p, q in zip(a.pitches, b.pitches)]))
    errors = sum(q-p != shift for p, q in zip(a.pitches, b.pitches))
    max_errors = math.floor(len(a.pitches) * cfg.pitch_error_fraction) if cfg.mode == "approximate" else 0
    if errors > max_errors:
        return None
    if cfg.mode != "approximate":
        if any(round(x*24) != round(y*24) for x, y in zip(a.onsets, b.onsets)):
            return None
        if any(round(x*24) != round(y*24) for x, y in zip(a.durations, b.durations)):
            return None
        return 1.0, shift
    timing = [abs(x-y) for x, y in zip(a.onsets, b.onsets)]
    if max(timing) > cfg.timing_tolerance:
        return None
    duration = [abs(x-y) for x, y in zip(a.durations, b.durations)]
    if sum(d > cfg.duration_tolerance for d in duration) > math.floor(len(duration)*cfg.duration_error_fraction):
        return None
    # Prevent permissive duration errors from hiding radically different rhythms.
    if sum(duration) / len(duration) > cfg.duration_tolerance:
        return None
    rhythm_quality = 1 - sum(timing) / (len(timing) * max(cfg.timing_tolerance, 1e-9))
    duration_quality = 1 - min(1, sum(duration) / (len(duration)*max(cfg.duration_tolerance, 1e-9)))
    return 0.65*(1-errors/len(a.pitches)) + 0.25*rhythm_quality + 0.10*duration_quality, shift


def _nonoverlap(occurrences: list[tuple[Window, float, int]]) -> list[tuple[Window, float, int]]:
    # Earliest finish greedy yields maximum cardinality for intervals.
    chosen = []
    last_end = -1
    for item in sorted(occurrences, key=lambda x: (x[0].end, x[0].start, x[0].index)):
        if item[0].start >= last_end:
            chosen.append(item)
            last_end = item[0].end
    return sorted(chosen, key=lambda x: x[0].start)


def _primitive_penalty(w: Window) -> float:
    # Penalize a repeated short arpeggio/ostinato, without asserting it is invalid.
    tokens = [(p, round((w.onsets[i+1]-w.onsets[i])*24))
              for i, p in enumerate(w.pitches[:-1])]
    for period in range(1, min(5, len(tokens)//2+1)):
        if all(tokens[i] == tokens[i % period] for i in range(len(tokens))):
            return 0.35
    return 1.0


def _boundary(w: Window, notes: list[Note], ppq: int, song: MidiSong) -> float:
    i, n = w.index, len(w.notes)
    before = (w.start - notes[i-1].end) / ppq if i else 1.0
    after = (notes[i+n].start - w.end) / ppq if i+n < len(notes) else 1.0
    active_meter_tick = max((t for t, _, _ in song.meters if t <= w.start), default=0)
    beat_in_bar = (w.start-active_meter_tick) % bar_length(song, w.start)
    bar_aligned = min(beat_in_bar, bar_length(song, w.start)-beat_in_bar) <= ppq/12
    return (min(1, max(0, before)*2) + min(1, max(0, after)*2) + float(bar_aligned))/3


def _score(w: Window, occurrences, stream, part, song):
    count = len(occurrences)
    support = min(1.0, math.log2(count)/3)
    total_span = max(1, max(n.end for n in stream)-stream[0].start)
    coverage = min(1, sum(x.end-x.start for x, _, _ in occurrences)/total_span)
    beats = (w.end-w.start)/song.ticks_per_beat
    length = math.exp(-abs(math.log2(beats/8))/2)
    counts = Counter(w.pitches)
    entropy = -sum((c/len(w.notes))*math.log2(c/len(w.notes)) for c in counts.values())
    diversity = min(1, entropy/2.5)
    boundary = _boundary(w, stream, song.ticks_per_beat, song)
    quality = sum(q for _, q, _ in occurrences)/count
    # An explicit small instrumental prior, not a trained melody classifier.
    salience = 0.25 if 32 <= part.program <= 39 else 0.75
    penalty = _primitive_penalty(w)
    terms = dict(support=support, coverage=coverage, length=length, diversity=diversity,
                 boundary=boundary, match_quality=quality, instrument_prior=salience,
                 ostinato_multiplier=penalty)
    score = penalty*(.30*support+.20*coverage+.15*length+.10*diversity+.10*boundary+.10*quality+.05*salience)
    return round(score, 8), {k: round(v, 8) for k, v in terms.items()}


def detect_part(song: MidiSong, part: Part, cfg: Config) -> tuple[list[dict], dict]:
    stats = {"part_index": part.index, "input_notes": len(part.notes), "skyline_notes": 0,
             "windows": 0, "comparisons": 0, "saturated_seed_buckets": 0,
             "comparison_limit_reached": False, "note_limit_reached": False,
             "raw_groups": 0, "repeat_groups": 0, "overlapping_occurrences_removed": 0,
             "windows_considered": 0, "window_limit_reached": False,
             "candidate_limit_reached": False, "candidates_truncated": 0}
    if part.is_drum:
        return [], stats
    stream = skyline(part, song.ticks_per_beat, cfg.onset_merge_beats)
    stats["skyline_notes"] = len(stream)
    stats["onset_notes_removed_fraction"] = round(1-len(stream)/max(1, len(part.notes)), 8)
    if len(stream) > cfg.max_stream_notes:
        # Explicit exclusion; do not label a prefix as a complete song analysis.
        stats["note_limit_reached"] = True
        return [], stats
    groups: list[list[tuple[Window, float, int]]] = []
    index: dict[tuple, list[int]] = defaultdict(list)
    strict_index: dict[str, int] = {}
    saturated: set[tuple] = set()
    ppq = song.ticks_per_beat
    for n in sorted(set(cfg.lengths), reverse=True):
        for i in range(len(stream)-n+1):
            if stats["windows_considered"] >= cfg.max_windows:
                stats["window_limit_reached"] = True
                break
            stats["windows_considered"] += 1
            w = window(stream, i, n, ppq)
            beats = (w.end-w.start)/ppq
            if not cfg.min_beats <= beats <= cfg.max_beats:
                continue
            if len(set(w.pitches)) < 3:
                continue
            if any((stream[j+1].start-stream[j].end)/ppq > cfg.max_gap_beats for j in range(i, i+n-1)):
                continue
            stats["windows"] += 1
            if cfg.mode != "approximate":
                key = signature(w, transpose=cfg.mode == "transposed")
                if key in strict_index:
                    gid = strict_index[key]
                    shift = w.pitches[0]-groups[gid][0][0].pitches[0]
                    groups[gid].append((w, 1.0, shift))
                else:
                    strict_index[key] = len(groups)
                    groups.append([(w, 1.0, 0)])
                continue
            seeds = tuple(_seeds(w))
            candidates = sorted(set(g for key in seeds for g in index[key]))
            best = None
            for gid in candidates:
                if stats["comparisons"] >= cfg.max_comparisons:
                    stats["comparison_limit_reached"] = True
                    break
                stats["comparisons"] += 1
                result = match(groups[gid][0][0], w, cfg)
                if result is not None and (best is None or result[0] > best[0]):
                    best = (result[0], gid, result[1])
                    if result[0] == 1:
                        break
            if best is not None:
                quality, gid, shift = best
                groups[gid].append((w, quality, shift))
            else:
                gid = len(groups)
                groups.append([(w, 1.0, 0)])
                for key in seeds:
                    if len(index[key]) < cfg.max_bucket:
                        index[key].append(gid)
                    else:
                        saturated.add(key)
        if stats["window_limit_reached"]:
            break
    stats["saturated_seed_buckets"] = len(saturated)
    stats["raw_groups"] = len(groups)
    out = []
    for group in groups:
        occurrences = _nonoverlap(group)
        stats["overlapping_occurrences_removed"] += len(group)-len(occurrences)
        if len(occurrences) < 2:
            continue
        stats["repeat_groups"] += 1
        # Prototype remains the matching representative, even if greedy interval
        # selection omitted it. Explicit prototype coordinates make this auditable.
        w = group[0][0]
        score, terms = _score(w, occurrences, stream, part, song)
        out.append({"family_id": signature(w, transpose=cfg.mode != "exact"), "part_index": part.index,
                    "source_track": part.track, "channel": part.channel,
                    "program": part.program, "part_name": part.name,
                    "note_count": len(w.notes), "start_tick": w.start, "end_tick": w.end,
                    "duration_beats": round((w.end-w.start)/ppq, 8),
                    "prototype_note_index": w.index,
                    "pitches": list(w.pitches),
                    "onsets_beats": [round(x, 8) for x in w.onsets],
                    "durations_beats": [round(x, 8) for x in w.durations],
                    "velocities": [x.velocity for x in w.notes],
                    "recurrence_score": score, "score_components": terms,
                    "raw_occurrence_count": len(group),
                    "occurrence_count": len(occurrences),
                    "occurrences": [{"start_tick": x.start, "end_tick": x.end,
                                     "note_index": x.index, "transpose_semitones": shift,
                                     "similarity": round(q, 8)} for x, q, shift in occurrences]})
    out.sort(key=lambda c: (-c["recurrence_score"], -c["note_count"], c["start_tick"], c["family_id"]))
    stats["candidates_truncated"] = max(0, len(out)-cfg.max_candidates)
    stats["candidate_limit_reached"] = bool(stats["candidates_truncated"])
    return out[:cfg.max_candidates], stats


def _redundant(a: dict, b: dict) -> bool:
    if a["family_id"] == b["family_id"]:
        return True
    if a["part_index"] != b["part_index"]:
        return False
    covered = 0
    for x in a["occurrences"]:
        if any(max(0, min(x["end_tick"], y["end_tick"])-max(x["start_tick"], y["start_tick"]))
               / max(1, min(x["end_tick"]-x["start_tick"], y["end_tick"]-y["start_tick"])) >= .7
               for y in b["occurrences"]):
            covered += 1
    return covered / len(a["occurrences"]) >= .7


def extract(song: MidiSong, cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    candidates, stats = [], []
    for part in song.parts:
        found, audit = detect_part(song, part, cfg)
        candidates.extend(found)
        stats.append(audit)
    candidates.sort(key=lambda c: (-c["recurrence_score"], -c["note_count"],
                                   c["part_index"], c["start_tick"], c["family_id"]))
    selected = []
    for candidate in candidates:
        if not any(_redundant(candidate, other) for other in selected):
            selected.append(candidate)
        if len(selected) == cfg.top_k:
            break
    limited = any(s["comparison_limit_reached"] or s["note_limit_reached"] or s["window_limit_reached"] or s["saturated_seed_buckets"] for s in stats)
    return {"config": asdict(cfg), "phrases": selected, "candidate_count": len(candidates),
            "raw_repeat_group_count": sum(s["repeat_groups"] for s in stats),
            "shortlisted_candidate_count": len(candidates),
            "curation_truncated": any(s["candidate_limit_reached"] for s in stats),
            "search_limited": limited, "part_stats": stats}
