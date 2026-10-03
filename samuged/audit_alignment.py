"""Independent checks for saved variable-length melodic alignments.

The functions in this module do not call the aligned detector, its dynamic
programming routine or its candidate generator. They reconstruct the saved edit
partition and numeric evidence directly from source notes.
"""

from __future__ import annotations

import math

from .midi import Note


EXPECTED_MATCHER_FLAGS = {
    "source_verified": True,
    "monotone_alignment": True,
    "fixed_transposition": True,
    "tempo_warp": False,
    "terminal_gaps_allowed": False,
    "similarity_only_acceptance": False,
}

_INTEGER_BOUNDS = {
    "min_notes": (4, 128),
    "max_notes": (4, 128),
    "max_edits": (0, 16),
    "seed_notes": (3, 5),
    "max_seed_offsets": (1, 32),
    "max_seed_pairs": (1, 64),
    "min_seed_support": (1, 32),
    "max_shift_candidates": (1, 32),
    "max_bucket": (1, 2_048),
    "max_comparisons": (1, 2_000_000),
    "max_stream_notes": (1, 20_000),
    "max_windows": (1, 400_000),
    "max_groups": (1, 200_000),
    "max_candidates": (1, 10_000),
    "top_k": (1, 100),
}
_NONNEGATIVE_NUMBERS = (
    "max_gap_beats",
    "timing_tolerance",
    "duration_tolerance",
    "duration_error_fraction",
    "max_edit_fraction",
    "onset_merge_beats",
    "seed_beat_bucket",
    "span_beat_bucket",
)


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_aligned_config(config: object) -> list[str]:
    """Validate the saved aligned configuration without constructing a detector."""

    if not isinstance(config, dict):
        return ["aligned config is not an object"]
    problems: list[str] = []
    for name, (lower, upper) in _INTEGER_BOUNDS.items():
        value = config.get(name)
        if type(value) is not int or not lower <= value <= upper:
            problems.append(f"aligned config {name} is outside supported bounds")
    for name in _NONNEGATIVE_NUMBERS:
        value = config.get(name)
        if not _number(value) or value < 0:
            problems.append(f"aligned config {name} is not finite and nonnegative")

    min_notes, max_notes = config.get("min_notes"), config.get("max_notes")
    if type(min_notes) is int and type(max_notes) is int and min_notes > max_notes:
        problems.append("aligned config min_notes exceeds max_notes")
    min_beats, max_beats = config.get("min_beats"), config.get("max_beats")
    if not (
        _number(min_beats)
        and _number(max_beats)
        and 0 < min_beats <= max_beats <= 128
    ):
        problems.append("aligned config beat bounds are invalid")
    edit_fraction = config.get("max_edit_fraction")
    if _number(edit_fraction) and not 0 < edit_fraction <= 0.15:
        problems.append("aligned config max_edit_fraction is outside (0, 0.15]")
    duration_fraction = config.get("duration_error_fraction")
    if _number(duration_fraction) and not 0 <= duration_fraction <= 0.5:
        problems.append("aligned config duration_error_fraction is outside [0, 0.5]")
    for name in ("seed_beat_bucket", "span_beat_bucket"):
        value = config.get(name)
        if _number(value) and value == 0:
            problems.append(f"aligned config {name} must be positive")
    seed_notes = config.get("seed_notes")
    if type(seed_notes) is int and type(min_notes) is int and seed_notes > min_notes:
        problems.append("aligned config seed_notes exceeds min_notes")
    return problems


def _indices(value: object, upper: int) -> bool:
    return (
        isinstance(value, list)
        and all(type(index) is int and 0 <= index < upper for index in value)
        and value == sorted(set(value))
    )


def _pairs(value: object, left_count: int, right_count: int) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(pair, list)
            and len(pair) == 2
            and type(pair[0]) is int
            and type(pair[1]) is int
            and 0 <= pair[0] < left_count
            and 0 <= pair[1] < right_count
            for pair in value
        )
    )


def verify_alignment(
    prototype: list[Note],
    occurrence_notes: list[Note],
    occurrence: object,
    ppq: int,
    config: dict,
) -> list[str]:
    """Verify one saved occurrence against its two exact source note slices."""

    if not isinstance(occurrence, dict):
        return ["alignment occurrence is not an object"]
    if type(ppq) is not int or ppq <= 0:
        return ["alignment PPQ is invalid"]
    if validate_aligned_config(config):
        return ["alignment cannot be checked with invalid config"]
    if not prototype or not occurrence_notes:
        return ["alignment source notes absent"]
    if not all(isinstance(note, Note) for note in [*prototype, *occurrence_notes]):
        return ["alignment source notes are invalid"]

    problems: list[str] = []

    def require(condition: bool, reason: str) -> None:
        if not condition:
            problems.append(reason)

    left_count, right_count = len(prototype), len(occurrence_notes)
    require(
        type(occurrence.get("note_count")) is int
        and occurrence["note_count"] == right_count,
        "occurrence note count differs from source",
    )
    require(
        config["min_notes"] <= left_count <= config["max_notes"]
        and config["min_notes"] <= right_count <= config["max_notes"],
        "alignment note count is outside configured bounds",
    )
    spans = [
        (max(note.end for note in notes) - notes[0].start) / ppq
        for notes in (prototype, occurrence_notes)
    ]
    require(
        all(config["min_beats"] <= span <= config["max_beats"] for span in spans),
        "alignment beat span is outside configured bounds",
    )
    require(
        all(
            (notes[index + 1].start - notes[index].end) / ppq
            <= config["max_gap_beats"]
            for notes in (prototype, occurrence_notes)
            for index in range(len(notes) - 1)
        ),
        "alignment source gap exceeds configured bound",
    )
    require(
        all(len({note.pitch for note in notes}) >= 3
            for notes in (prototype, occurrence_notes)),
        "alignment source slice lacks required pitch variety",
    )
    require(
        occurrence.get("start_tick") == occurrence_notes[0].start
        and occurrence.get("end_tick") == max(note.end for note in occurrence_notes),
        "occurrence coordinates differ from source",
    )

    pairs = occurrence.get("matched_note_pairs")
    if not _pairs(pairs, left_count, right_count):
        return problems + ["invalid alignment note pairs"]
    left = [pair[0] for pair in pairs]
    right = [pair[1] for pair in pairs]
    require(
        all(a < b for a, b in zip(left, left[1:]))
        and all(a < b for a, b in zip(right, right[1:])),
        "alignment is not strictly monotone",
    )
    require(
        pairs[0] == [0, 0]
        and pairs[-1] == [left_count - 1, right_count - 1],
        "alignment has terminal gaps",
    )

    insertions = occurrence.get("inserted_note_indices")
    deletions = occurrence.get("deleted_prototype_note_indices")
    if not _indices(insertions, right_count) or not _indices(deletions, left_count):
        return problems + ["invalid inserted or deleted note indices"]
    require(
        set(left).isdisjoint(deletions)
        and set(left) | set(deletions) == set(range(left_count)),
        "prototype alignment partition is incomplete or overlapping",
    )
    require(
        set(right).isdisjoint(insertions)
        and set(right) | set(insertions) == set(range(right_count)),
        "occurrence alignment partition is incomplete or overlapping",
    )

    shift = occurrence.get("transpose_semitones")
    if type(shift) is not int:
        return problems + ["invalid fixed transposition"]
    substitutions = [
        [left_index, right_index]
        for left_index, right_index in pairs
        if occurrence_notes[right_index].pitch - prototype[left_index].pitch != shift
    ]
    require(
        occurrence.get("substituted_note_pairs") == substitutions,
        "substitution list differs from source pitches",
    )

    edits = len(insertions) + len(deletions) + len(substitutions)
    allowed = min(
        config["max_edits"],
        max(1, math.floor(max(left_count, right_count) * config["max_edit_fraction"])),
    )
    require(
        type(occurrence.get("edit_count")) is int
        and occurrence["edit_count"] == edits,
        "edit count differs from alignment",
    )
    require(edits <= allowed, "alignment edit budget exceeded")

    prototype_start = prototype[0].start
    occurrence_start = occurrence_notes[0].start
    timing = [
        abs(
            (prototype[left_index].start - prototype_start)
            - (occurrence_notes[right_index].start - occurrence_start)
        )
        / ppq
        for left_index, right_index in pairs
    ]
    duration = [
        abs(
            (prototype[left_index].end - prototype[left_index].start)
            - (
                occurrence_notes[right_index].end
                - occurrence_notes[right_index].start
            )
        )
        / ppq
        for left_index, right_index in pairs
    ]
    require(
        max(timing) <= config["timing_tolerance"] + 1e-9,
        "alignment onset tolerance violated",
    )
    require(
        sum(value > config["duration_tolerance"] + 1e-9 for value in duration)
        <= math.floor(len(pairs) * config["duration_error_fraction"]),
        "alignment duration count tolerance violated",
    )
    mean_timing = sum(timing) / len(pairs)
    mean_duration = sum(duration) / len(pairs)
    require(
        mean_duration <= config["duration_tolerance"] + 1e-9,
        "alignment mean duration tolerance violated",
    )
    for key, expected in (
        ("max_timing_error_beats", max(timing)),
        ("max_duration_error_beats", max(duration)),
    ):
        value = occurrence.get(key)
        require(
            _number(value) and abs(value - expected) <= 1e-7,
            f"{key} differs from source",
        )

    similarity = (
        0.7 * (1 - edits / max(left_count, right_count))
        + 0.2
        * (1 - mean_timing / max(config["timing_tolerance"], 1e-12))
        + 0.1
        * (
            1
            - min(
                1,
                mean_duration / max(config["duration_tolerance"], 1e-12),
            )
        )
    )
    reported = occurrence.get("similarity")
    require(
        _number(reported) and abs(reported - similarity) <= 1e-7,
        "alignment similarity differs from source",
    )
    require(
        occurrence.get("source_verified") is True,
        "alignment source verification flag absent",
    )
    return problems
