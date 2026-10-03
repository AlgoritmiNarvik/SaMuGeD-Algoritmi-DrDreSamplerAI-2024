"""Experimental exact-first index for the frozen aligned detector.

This module preserves the frozen alignment verifier and ranking functions. It
only changes index work: an exact transposed signature is checked before seed
keys are generated and exact descriptors are cached for final verification.
The bounded seed postings and their saturation semantics remain unchanged.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict

from . import aligned as _frozen
from .midi import MidiSong, Part
from .phrases import Window


AlignedConfig = _frozen.AlignedConfig


def detect_indexed_part(
    song: MidiSong, part: Part, cfg: AlignedConfig
) -> tuple[list[dict], dict]:
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
        "exact_fast_path_hits": 0,
        "seed_key_calls": 0,
        "seed_keys_bypassed": 0,
        "exact_key_cache_hits": 0,
        "posting_entries_visited": 0,
        "seed_index_keys": 0,
        "seed_index_postings": 0,
        "max_seed_bucket_size": 0,
        "saturated_seed_postings_dropped": 0,
        "saturated_seed_key_types": {},
    }
    if part.is_drum:
        return [], stats
    stream = _frozen.skyline(part, song.ticks_per_beat, cfg.onset_merge_beats)
    stats["skyline_notes"] = len(stream)
    stats["onset_notes_removed_fraction"] = round(
        1 - len(stream) / max(1, len(part.notes)), 8
    )
    if len(stream) > cfg.max_stream_notes:
        stats["note_limit_reached"] = True
        return [], stats

    groups: list[list[Window]] = []
    seed_index: dict[tuple, list[int]] = defaultdict(list)
    exact_index: dict[tuple, int] = {}
    exact_key_cache: dict[tuple[int, int], tuple] = {}
    alignment_cache: dict[tuple[int, int, int, int], _frozen.Alignment | None] = {}
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
            candidate = _frozen._valid_window(stream, start, count, song, cfg)
            if candidate is None:
                continue
            stats["windows"] += 1
            window_key = (candidate.index, len(candidate.notes))
            exact_key = _frozen._exact_key(candidate)
            exact_key_cache[window_key] = exact_key
            exact_group = exact_index.get(exact_key)
            if exact_group is not None:
                representative = groups[exact_group][0]
                result = _frozen._exact_alignment(representative, candidate)
                groups[exact_group].append(candidate)
                alignment_cache[
                    (
                        representative.index,
                        len(representative.notes),
                        candidate.index,
                        len(candidate.notes),
                    )
                ] = result
                stats["exact_signature_hits"] += 1
                stats["exact_fast_path_hits"] += 1
                stats["seed_keys_bypassed"] += 1
                continue

            stats["seed_key_calls"] += 1
            query_keys = _frozen._seed_keys(candidate, cfg)
            postings = [seed_index.get(key, ()) for key in query_keys]
            stats["posting_entries_visited"] += sum(len(posting) for posting in postings)
            group_votes = Counter(group for posting in postings for group in posting)
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
                if not (
                    candidate.end <= representative.start
                    or representative.end <= candidate.start
                ):
                    stats["overlap_rejections"] += 1
                    continue
                allowed = _frozen._allowed_edits(
                    len(representative.notes), len(candidate.notes), cfg
                )
                if abs(len(representative.notes) - len(candidate.notes)) > allowed:
                    stats["length_rejections"] += 1
                    continue
                if (
                    abs(representative.onsets[-1] - candidate.onsets[-1])
                    > cfg.timing_tolerance
                ):
                    stats["terminal_timing_rejections"] += 1
                    continue
                timing_pairs = _frozen._timing_alignment(
                    representative, candidate, allowed, cfg.timing_tolerance
                )
                if timing_pairs is None:
                    stats["timing_feasibility_rejections"] += 1
                    continue
                if not _frozen._pitch_feasible(
                    representative, candidate, timing_pairs, allowed
                ):
                    stats["pitch_feasibility_rejections"] += 1
                    continue
                result = _frozen._anchor_alignment(
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
            if best is None:
                if len(groups) >= cfg.max_groups:
                    stats["group_limit_reached"] = True
                    stop = True
                    break
                group_index = len(groups)
                groups.append([candidate])
                exact_index[exact_key] = group_index
                for key in query_keys:
                    bucket = seed_index[key]
                    if len(bucket) < cfg.max_bucket:
                        bucket.append(group_index)
                    else:
                        saturated.add(key)
                        stats["saturated_seed_postings_dropped"] += 1
            else:
                groups[best[1]].append(candidate)
        if stop:
            break
    stats["saturated_seed_buckets"] = len(saturated)
    stats["saturated_seed_key_types"] = dict(
        sorted(Counter(key[0] for key in saturated).items())
    )
    stats["seed_index_keys"] = len(seed_index)
    stats["seed_index_postings"] = sum(len(bucket) for bucket in seed_index.values())
    stats["max_seed_bucket_size"] = max(
        (len(bucket) for bucket in seed_index.values()), default=0
    )
    stats["groups"] = len(groups)

    output = []
    for members in groups:
        unique = {(member.index, len(member.notes)): member for member in members}
        members = list(unique.values())
        if len(members) < 2:
            continue
        prototype = min(
            members,
            key=lambda item: (item.start, item.end, len(item.notes), item.index),
        )
        prototype_key = exact_key_cache[(prototype.index, len(prototype.notes))]
        verified = []
        for member in members:
            member_window_key = (member.index, len(member.notes))
            cache_key = (
                prototype.index,
                len(prototype.notes),
                member.index,
                len(member.notes),
            )
            if cache_key in alignment_cache:
                result = alignment_cache[cache_key]
                stats["alignment_cache_hits"] += 1
            else:
                member_key = exact_key_cache[member_window_key]
                stats["exact_key_cache_hits"] += 1
                if prototype_key == member_key:
                    result = _frozen._exact_alignment(prototype, member)
                    stats["exact_signature_hits"] += 1
                    alignment_cache[cache_key] = result
                else:
                    allowed = _frozen._allowed_edits(
                        len(prototype.notes), len(member.notes), cfg
                    )
                    timing_pairs = _frozen._timing_alignment(
                        prototype, member, allowed, cfg.timing_tolerance
                    )
                    result = None
                    if timing_pairs is not None and _frozen._pitch_feasible(
                        prototype, member, timing_pairs, allowed
                    ):
                        result = _frozen._anchor_alignment(
                            prototype, member, timing_pairs, cfg
                        )
                        if result is not None:
                            stats["anchor_alignment_hits"] += 1
                    if result is None:
                        stats["anchor_alignment_fallbacks"] += 1
                        if stats["comparisons"] >= cfg.max_comparisons:
                            stats["comparison_limit_reached"] = True
                            continue
                        shifts = _frozen._shift_candidates(
                            prototype,
                            member,
                            allowed,
                            cfg.max_shift_candidates,
                        )
                        stats["comparisons"] += 1
                        stats["dp_calls"] += 1
                        result = _frozen._align_with_shifts(
                            prototype, member, cfg, shifts
                        )
                    alignment_cache[cache_key] = result
            if result is not None:
                verified.append((member, result))
        occurrences = _frozen._nonoverlap(verified)
        stats["overlapping_occurrences_removed"] += len(verified) - len(occurrences)
        if len(occurrences) < 2:
            continue
        stats["repeat_groups"] += 1
        score, components = _frozen._score(
            prototype, occurrences, stream, song
        )
        output.append(
            {
                "family_id": _frozen._family_id(prototype),
                "part_index": part.index,
                "source_track": part.track,
                "channel": part.channel,
                "program": part.program,
                "part_name": part.name,
                "note_count": len(prototype.notes),
                "start_tick": prototype.start,
                "end_tick": prototype.end,
                "duration_beats": round(
                    (prototype.end - prototype.start) / song.ticks_per_beat, 8
                ),
                "prototype_note_index": prototype.index,
                "pitches": list(prototype.pitches),
                "onsets_beats": [round(value, 8) for value in prototype.onsets],
                "durations_beats": [
                    round(value, 8) for value in prototype.durations
                ],
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
                "occurrences": [
                    _frozen._occurrence(candidate, result)
                    for candidate, result in occurrences
                ],
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


def extract_indexed(song: MidiSong, cfg: AlignedConfig | None = None) -> dict:
    """Extract phrases with the exact-first experimental candidate index."""
    cfg = cfg or AlignedConfig()
    if not isinstance(cfg, AlignedConfig):
        raise TypeError("cfg must be an AlignedConfig")
    candidates, stats = [], []
    for part in song.parts:
        found, audit = detect_indexed_part(song, part, cfg)
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
            (
                index
                for index, prior in enumerate(selected)
                if _frozen._redundant(candidate, prior)
            ),
            None,
        )
        if redundant_index is None:
            selected.append(candidate)
        elif _frozen._prefer_boundary_extension(
            candidate, selected[redundant_index]
        ):
            selected[redundant_index] = candidate
        if len(selected) == cfg.top_k:
            break
    limit_keys = (
        "note_limit_reached",
        "window_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
    )
    search_limited = any(
        any(part[key] for key in limit_keys) or part["saturated_seed_buckets"]
        for part in stats
    )
    return {
        "config": asdict(cfg),
        "phrases": selected,
        "candidate_count": len(candidates),
        "raw_repeat_group_count": sum(part["repeat_groups"] for part in stats),
        "shortlisted_candidate_count": len(candidates),
        "curation_truncated": any(
            part["candidate_limit_reached"] for part in stats
        ),
        "search_limited": search_limited,
        "part_stats": stats,
        "index_variant": "exact_first_cached_v1",
    }
