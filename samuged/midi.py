"""Deterministic MIDI parsing and phrase export in source tick units."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from io import BytesIO
import os
from pathlib import Path
from typing import Iterable

import mido


MAX_MIDI_BYTES = 16 * 1024 * 1024
MAX_MIDI_EVENTS = 300_000
MAX_MIDI_NOTES = 300_000
_MAX_WARNINGS = 1_000
_MIDI_SUFFIXES = frozenset({".mid", ".midi"})
_MIDI_MAGIC = b"MThd"
_RIFF_MAGIC = b"RIFF"
_RMID_FORM = b"RMID"
_RIFF_DATA = b"data"
_DEFAULT_TEMPO = 500_000
_DEFAULT_METER = (4, 4)


@dataclass(slots=True)
class Note:
    start: int
    end: int
    pitch: int
    velocity: int


@dataclass(slots=True)
class Part:
    index: int
    track: int
    channel: int
    program: int
    name: str
    is_drum: bool
    notes: list[Note] = field(default_factory=list)


@dataclass(slots=True)
class MidiSong:
    ticks_per_beat: int
    parts: list[Part]
    tempos: list[tuple[int, int]]
    meters: list[tuple[int, int, int]]
    warnings: list[str]


class _Warnings:
    """Bound diagnostics so a small malformed file cannot amplify memory use."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.omitted = 0

    def add(self, message: str) -> None:
        if len(self.items) < _MAX_WARNINGS:
            self.items.append(message)
        else:
            self.omitted += 1

    def finish(self) -> list[str]:
        if self.omitted:
            self.items.append(
                f"{self.omitted} additional MIDI warnings omitted after {_MAX_WARNINGS}"
            )
        return self.items


def _require_int(
    value: object, name: str, minimum: int, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        expected = (
            f"at least {minimum}"
            if maximum is None
            else f"between {minimum} and {maximum}"
        )
        raise ValueError(f"{name} must be {expected}")
    return value


def _coerce_path(path: str | Path, *, purpose: str) -> Path:
    if not isinstance(path, (str, Path)):
        raise TypeError(f"{purpose} path must be a string or pathlib.Path")
    result = Path(path)
    if result.suffix.lower() not in _MIDI_SUFFIXES:
        raise ValueError(f"{purpose} path must use a .mid or .midi extension")
    return result


def _canonical_changes(
    changes: Iterable[tuple[int, tuple[int, ...]]], default: tuple[int, ...]
) -> list[tuple[int, ...]]:
    """Keep the last source event at each tick and establish tick-zero state."""
    by_tick: dict[int, tuple[int, ...]] = {}
    for tick, values in sorted(changes, key=lambda item: item[0]):
        by_tick[tick] = values
    if 0 not in by_tick:
        by_tick[0] = default
    return [(tick, *by_tick[tick]) for tick in sorted(by_tick)]


def _unwrap_midi_payload(data: bytes) -> tuple[bytes, bool]:
    """Return an SMF payload, accepting only a structurally valid RIFF RMID."""
    if data.startswith(_MIDI_MAGIC):
        return data, False
    if not data.startswith(_RIFF_MAGIC):
        raise ValueError("invalid MIDI file: missing MThd or RIFF RMID header")
    if len(data) < 12:
        raise ValueError("invalid RIFF RMID file: truncated RIFF header")

    riff_size = int.from_bytes(data[4:8], "little")
    riff_end = 8 + riff_size
    if riff_size < 4:
        raise ValueError("invalid RIFF RMID file: RIFF size is too small")
    if riff_end > len(data):
        raise ValueError("invalid RIFF RMID file: truncated RIFF payload")
    if riff_end < len(data):
        raise ValueError("invalid RIFF RMID file: data follows the RIFF boundary")
    if data[8:12] != _RMID_FORM:
        raise ValueError("invalid RIFF RMID file: RIFF form is not RMID")

    midi_payload: bytes | None = None
    offset = 12
    while offset < riff_end:
        if riff_end - offset < 8:
            raise ValueError("invalid RIFF RMID file: truncated chunk header")
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > riff_end:
            raise ValueError("invalid RIFF RMID file: chunk exceeds RIFF boundary")
        padded_end = chunk_end + (chunk_size & 1)
        if padded_end > riff_end:
            raise ValueError("invalid RIFF RMID file: missing chunk padding")

        if chunk_id == _RIFF_DATA:
            if midi_payload is not None:
                raise ValueError("invalid RIFF RMID file: multiple data chunks")
            candidate = data[chunk_start:chunk_end]
            if not candidate.startswith(_MIDI_MAGIC):
                raise ValueError(
                    "invalid RIFF RMID file: data chunk does not start with MThd"
                )
            midi_payload = candidate
        offset = padded_end

    if midi_payload is None:
        raise ValueError("invalid RIFF RMID file: missing MIDI data chunk")
    return midi_payload, True


def load_midi(path: str | Path) -> MidiSong:
    """Load a format 0 or 1 standard MIDI file without converting source ticks.

    The caller is responsible for choosing a trusted path. The extension, header
    magic, byte size and parsed workload are checked before data is returned.
    """
    source = _coerce_path(path, purpose="input")

    try:
        with source.open("rb") as infile:
            # ASVS 5.2.1: cap input before the parser allocates from file content.
            size = os.fstat(infile.fileno()).st_size
            if size > MAX_MIDI_BYTES:
                raise ValueError(
                    f"MIDI file exceeds the {MAX_MIDI_BYTES}-byte size limit"
                )
            file_data = infile.read(MAX_MIDI_BYTES + 1)
            if len(file_data) > MAX_MIDI_BYTES:
                raise ValueError(
                    f"MIDI file exceeds the {MAX_MIDI_BYTES}-byte size limit"
                )
            if len(file_data) != size:
                raise ValueError("MIDI file changed while it was being read")
            # ASVS 5.2.2: validate the extension and the SMF or RIFF RMID structure.
            midi_payload, was_rmid = _unwrap_midi_payload(file_data)
            midi = mido.MidiFile(file=BytesIO(midi_payload), clip=False)
    except ValueError:
        raise
    except (EOFError, OSError) as exc:
        raise ValueError(f"invalid MIDI file: {exc or type(exc).__name__}") from exc

    if midi.type == 2:
        raise ValueError("MIDI format 2 files are not supported")
    if midi.type not in (0, 1):
        raise ValueError(f"unsupported MIDI format {midi.type}")
    if midi.ticks_per_beat <= 0:
        raise ValueError("SMPTE time division is not supported")

    warnings = _Warnings()
    if was_rmid:
        warnings.add("riff_rmid_unwrapped")
    track_names: dict[int, str] = {}
    part_by_key: dict[tuple[int, int, int], Part] = {}
    pending: dict[tuple[int, int, int], deque[tuple[int, int, Part]]] = {}
    tempo_events: list[tuple[int, tuple[int, ...]]] = []
    meter_events: list[tuple[int, tuple[int, ...]]] = []
    source_events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]] = []
    event_count = 0
    note_count = 0

    for track_index, track in enumerate(midi.tracks):
        absolute_tick = 0
        for event_index, message in enumerate(track):
            event_count += 1
            if event_count > MAX_MIDI_EVENTS:
                raise ValueError(
                    f"MIDI file exceeds the {MAX_MIDI_EVENTS}-event limit"
                )
            absolute_tick += message.time
            source_events.append((absolute_tick, track_index, event_index, message))
            if message.type == "track_name" and track_index not in track_names:
                track_names[track_index] = message.name

    programs: dict[int, int] = {channel: 0 for channel in range(16)}
    for absolute_tick, track_index, _event_index, message in sorted(source_events):
        if message.type == "set_tempo":
            tempo = _require_int(message.tempo, "tempo", 1, 0xFFFFFF)
            tempo_events.append((absolute_tick, (tempo,)))
        elif message.type == "time_signature":
            numerator, denominator = _validated_meter(
                message.numerator, message.denominator
            )
            meter_events.append((absolute_tick, (numerator, denominator)))
        elif message.type == "program_change":
            programs[message.channel] = message.program
        elif message.type == "note_on" and message.velocity > 0:
            program = programs[message.channel]
            part_key = (track_index, message.channel, program)
            part = part_by_key.get(part_key)
            if part is None:
                part = Part(
                    index=len(part_by_key),
                    track=track_index,
                    channel=message.channel,
                    program=program,
                    name=track_names.get(track_index, ""),
                    is_drum=message.channel == 9,
                )
                part_by_key[part_key] = part
            pending.setdefault(
                (track_index, message.channel, message.note), deque()
            ).append((absolute_tick, message.velocity, part))
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            pending_key = (track_index, message.channel, message.note)
            queue = pending.get(pending_key)
            if not queue:
                warnings.add(
                    "track "
                    f"{track_index}: note-off without note-on for channel "
                    f"{message.channel}, pitch {message.note} at tick {absolute_tick}"
                )
                continue
            start, velocity, part = queue.popleft()
            if not queue:
                del pending[pending_key]
            if absolute_tick == start:
                warnings.add(
                    "track "
                    f"{track_index}: zero-duration note for channel "
                    f"{message.channel}, pitch {message.note} at tick {absolute_tick}"
                )
                continue
            if absolute_tick < start:
                warnings.add(
                    "track "
                    f"{track_index}: note end precedes onset for channel "
                    f"{message.channel}, pitch {message.note} at tick {absolute_tick}"
                )
                continue
            note_count += 1
            if note_count > MAX_MIDI_NOTES:
                raise ValueError(
                    f"MIDI file exceeds the {MAX_MIDI_NOTES}-note limit"
                )
            part.notes.append(Note(start, absolute_tick, message.note, velocity))

    for (track_index, channel, pitch), queue in sorted(pending.items()):
        for start, _velocity, _part in queue:
            warnings.add(
                "track "
                f"{track_index}: dangling note-on for channel {channel}, "
                f"pitch {pitch} at tick {start}"
            )

    for part in part_by_key.values():
        part.notes.sort(
            key=lambda note: (note.start, note.end, note.pitch, note.velocity)
        )

    tempos = _canonical_changes(tempo_events, (_DEFAULT_TEMPO,))
    meters = _canonical_changes(meter_events, _DEFAULT_METER)
    return MidiSong(
        ticks_per_beat=midi.ticks_per_beat,
        parts=list(part_by_key.values()),
        tempos=[(tick, tempo) for tick, tempo in tempos],
        meters=[
            (tick, numerator, denominator)
            for tick, numerator, denominator in meters
        ],
        warnings=warnings.finish(),
    )


def _validate_song(song: MidiSong) -> None:
    if not isinstance(song, MidiSong):
        raise TypeError("song must be a MidiSong")
    _require_int(song.ticks_per_beat, "ticks_per_beat", 1, 0x7FFF)


def _validate_part(part: Part) -> None:
    if not isinstance(part, Part):
        raise TypeError("part must be a Part")
    _require_int(part.index, "part index", 0)
    _require_int(part.track, "part track", 0)
    _require_int(part.channel, "part channel", 0, 15)
    _require_int(part.program, "part program", 0, 127)
    if not isinstance(part.name, str):
        raise TypeError("part name must be a string")
    if not isinstance(part.is_drum, bool):
        raise TypeError("part is_drum must be a bool")


def _validate_note(note: Note) -> None:
    if not isinstance(note, Note):
        raise TypeError("notes must contain Note instances")
    start = _require_int(note.start, "note start", 0)
    end = _require_int(note.end, "note end", 1)
    if end <= start:
        raise ValueError("note end must be greater than note start")
    _require_int(note.pitch, "note pitch", 0, 127)
    _require_int(note.velocity, "note velocity", 1, 127)


def _active_change(
    changes: list[tuple[int, ...]], tick: int, default: tuple[int, ...]
) -> tuple[int, ...]:
    active = default
    for change in changes:
        change_tick = _require_int(change[0], "metadata tick", 0)
        if change_tick > tick:
            break
        active = tuple(change[1:])
    return active


def _tempo_messages(
    song: MidiSong, start: int, end: int
) -> list[tuple[int, mido.MetaMessage]]:
    ordered = sorted(song.tempos, key=lambda change: change[0])
    active = _active_change(ordered, start, (_DEFAULT_TEMPO,))
    tempo = _require_int(active[0], "tempo", 1, 0xFFFFFF)
    result = [(0, mido.MetaMessage("set_tempo", tempo=tempo, time=0))]
    for tick, value in ordered:
        tick = _require_int(tick, "tempo tick", 0)
        value = _require_int(value, "tempo", 1, 0xFFFFFF)
        if start < tick < end:
            result.append(
                (tick - start, mido.MetaMessage("set_tempo", tempo=value, time=0))
            )
    return result


def _meter_messages(
    song: MidiSong, start: int, end: int
) -> list[tuple[int, mido.MetaMessage]]:
    ordered = sorted(song.meters, key=lambda change: change[0])
    active = _active_change(ordered, start, _DEFAULT_METER)
    numerator, denominator = _validated_meter(active[0], active[1])
    result = [
        (
            0,
            mido.MetaMessage(
                "time_signature",
                numerator=numerator,
                denominator=denominator,
                time=0,
            ),
        )
    ]
    for tick, numerator, denominator in ordered:
        tick = _require_int(tick, "meter tick", 0)
        numerator, denominator = _validated_meter(numerator, denominator)
        if start < tick < end:
            result.append(
                (
                    tick - start,
                    mido.MetaMessage(
                        "time_signature",
                        numerator=numerator,
                        denominator=denominator,
                        time=0,
                    ),
                )
            )
    return result


def _validated_meter(numerator: object, denominator: object) -> tuple[int, int]:
    numerator = _require_int(numerator, "meter numerator", 1, 255)
    denominator = _require_int(denominator, "meter denominator", 1, 2**255)
    if denominator & (denominator - 1):
        raise ValueError("meter denominator must be a power of two")
    return numerator, denominator


def _to_delta_track(
    events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]],
    end_tick: int | None = None,
) -> mido.MidiTrack:
    result = mido.MidiTrack()
    previous_tick = 0
    for tick, _priority, _sequence, message in sorted(
        events, key=lambda item: item[:3]
    ):
        result.append(message.copy(time=tick - previous_tick))
        previous_tick = tick
    result.append(mido.MetaMessage("end_of_track", time=max(0, (end_tick or previous_tick)-previous_tick)))
    return result


def export_phrase(
    song: MidiSong,
    part: Part,
    notes: list[Note],
    start: int,
    end: int,
    path: str | Path,
) -> None:
    """Export notes intersecting ``[start, end)`` with the origin moved to zero.

    ``path`` must be a trusted caller-selected destination (ASVS 5.3.2). Existing
    files are replaced, matching :meth:`mido.MidiFile.save` semantics.
    """
    _validate_song(song)
    _validate_part(part)
    start = _require_int(start, "start", 0)
    end = _require_int(end, "end", 1)
    if end <= start:
        raise ValueError("export region must have positive duration")
    if not isinstance(notes, list):
        raise TypeError("notes must be a list")
    if len(notes) > MAX_MIDI_NOTES:
        raise ValueError(f"notes exceed the {MAX_MIDI_NOTES}-note limit")
    for note in notes:
        _validate_note(note)

    destination = _coerce_path(path, purpose="output")
    midi = mido.MidiFile(type=1, ticks_per_beat=song.ticks_per_beat)

    metadata_events: list[tuple[int, int, int, mido.MetaMessage]] = []
    sequence = 0
    for tick, message in _tempo_messages(song, start, end):
        metadata_events.append((tick, 0, sequence, message))
        sequence += 1
    for tick, message in _meter_messages(song, start, end):
        metadata_events.append((tick, 1, sequence, message))
        sequence += 1
    midi.tracks.append(_to_delta_track(metadata_events, end-start))

    note_events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]] = []
    sequence = 0
    if part.name:
        note_events.append(
            (0, 0, sequence, mido.MetaMessage("track_name", name=part.name))
        )
        sequence += 1
    note_events.append(
        (
            0,
            1,
            sequence,
            mido.Message(
                "program_change", channel=part.channel, program=part.program, time=0
            ),
        )
    )
    sequence += 1

    for note in notes:
        clipped_start = max(note.start, start)
        clipped_end = min(note.end, end)
        if clipped_start >= clipped_end:
            continue
        relative_start = clipped_start - start
        relative_end = clipped_end - start
        note_events.append(
            (
                relative_start,
                3,
                sequence,
                mido.Message(
                    "note_on",
                    channel=part.channel,
                    note=note.pitch,
                    velocity=note.velocity,
                    time=0,
                ),
            )
        )
        sequence += 1
        note_events.append(
            (
                relative_end,
                2,
                sequence,
                mido.Message(
                    "note_off",
                    channel=part.channel,
                    note=note.pitch,
                    velocity=0,
                    time=0,
                ),
            )
        )
        sequence += 1
    midi.tracks.append(_to_delta_track(note_events, end-start))

    buffer = BytesIO()
    midi.save(file=buffer)
    payload = buffer.getvalue()
    if len(payload) > MAX_MIDI_BYTES:
        raise ValueError(f"export exceeds the {MAX_MIDI_BYTES}-byte size limit")
    destination.write_bytes(payload)


def bar_length(song: MidiSong, tick: int) -> float:
    """Return the active meter's bar length in MIDI ticks."""
    _validate_song(song)
    tick = _require_int(tick, "tick", 0)
    ordered = sorted(song.meters, key=lambda change: change[0])
    active = _active_change(ordered, tick, _DEFAULT_METER)
    numerator, denominator = _validated_meter(active[0], active[1])
    return song.ticks_per_beat * numerator * 4 / denominator
