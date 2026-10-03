"""Conservative in-memory recovery for invalid MIDI key metadata.

This module accepts an already unwrapped Standard MIDI File payload. It walks
the complete SMF structure and changes only the type byte of an invalid ``FF
59`` key-signature event to ``7F`` (sequencer-specific metadata). The complete
original payload remains in the event and is also recorded in the repair
receipt. No musical interpretation is substituted for the invalid value.
"""

from __future__ import annotations

from dataclasses import dataclass


MAX_SMF_BYTES = 16 * 1024 * 1024
MAX_SMF_EVENTS = 300_000
MAX_REPAIRS = 1_024

_HEADER = b"MThd"
_TRACK = b"MTrk"
_KEY_SIGNATURE = 0x59
_SEQUENCER_SPECIFIC = 0x7F


class MetadataRecoveryError(ValueError):
    """Raised when an SMF payload cannot be validated without guessing."""


@dataclass(frozen=True, slots=True)
class KeySignatureRepair:
    """A bounded receipt for one metadata type-byte substitution."""

    track_index: int
    event_index: int
    tick: int
    event_offset: int
    status_offset: int
    meta_type_offset: int
    payload_offset: int
    original_payload: bytes
    reason: str
    original_meta_type: int = _KEY_SIGNATURE
    replacement_meta_type: int = _SEQUENCER_SPECIFIC


@dataclass(frozen=True, slots=True)
class MetadataRecoveryResult:
    """Sanitized SMF bytes and the exact repairs used to produce them."""

    data: bytes
    repairs: tuple[KeySignatureRepair, ...]

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


def _error(message: str, *, track_index: int | None = None) -> MetadataRecoveryError:
    prefix = "invalid SMF"
    if track_index is not None:
        prefix += f" track {track_index}"
    return MetadataRecoveryError(f"{prefix}: {message}")


def _read_vlq(
    data: bytes,
    offset: int,
    end: int,
    *,
    label: str,
    track_index: int,
) -> tuple[int, int]:
    """Read one SMF variable-length quantity, limited to four bytes."""

    value = 0
    for _index in range(4):
        if offset >= end:
            raise _error(f"truncated {label} VLQ", track_index=track_index)
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, offset
    raise _error(f"{label} VLQ exceeds four bytes", track_index=track_index)


def _channel_data_length(status: int) -> int:
    high = status >> 4
    if high in (0xC, 0xD):
        return 1
    if 0x8 <= high <= 0xE:
        return 2
    raise AssertionError("channel status expected")


def _walk_track(
    source: bytes,
    output: bytearray,
    start: int,
    end: int,
    track_index: int,
    repairs: list[KeySignatureRepair],
    max_repairs: int,
    event_budget: list[int],
) -> None:
    offset = start
    tick = 0
    event_index = 0
    running_status: int | None = None
    saw_end_of_track = False

    while offset < end:
        if saw_end_of_track:
            raise _error("event follows end-of-track metadata", track_index=track_index)
        if event_budget[0] >= MAX_SMF_EVENTS:
            raise _error(
                f"event count exceeds {MAX_SMF_EVENTS}", track_index=track_index
            )
        event_budget[0] += 1
        event_offset = offset
        delta, offset = _read_vlq(
            source,
            offset,
            end,
            label="delta-time",
            track_index=track_index,
        )
        tick += delta
        if offset >= end:
            raise _error("missing event status or data", track_index=track_index)

        status_offset = offset
        first = source[offset]
        offset += 1
        first_running_data: int | None = None
        if first < 0x80:
            if running_status is None:
                raise _error(
                    "running status without a preceding channel status",
                    track_index=track_index,
                )
            status = running_status
            first_running_data = first
        else:
            status = first

        if 0x80 <= status <= 0xEF:
            if first_running_data is None:
                running_status = status
                remaining = _channel_data_length(status)
            else:
                remaining = _channel_data_length(status) - 1
            if offset + remaining > end:
                raise _error("truncated channel message", track_index=track_index)
            for data_byte in source[offset : offset + remaining]:
                if data_byte >= 0x80:
                    raise _error(
                        "channel data byte has its high bit set",
                        track_index=track_index,
                    )
            offset += remaining
        elif status in (0xF0, 0xF7):
            running_status = None
            length, offset = _read_vlq(
                source,
                offset,
                end,
                label="system-exclusive length",
                track_index=track_index,
            )
            if length > end - offset:
                raise _error(
                    "system-exclusive payload exceeds track boundary",
                    track_index=track_index,
                )
            offset += length
        elif status == 0xFF:
            # SMF readers, including mido, retain the previous channel running
            # status across meta events. A meta event does not become the new
            # running status.
            if offset >= end:
                raise _error("missing metadata type", track_index=track_index)
            meta_type_offset = offset
            meta_type = source[offset]
            offset += 1
            if meta_type >= 0x80:
                raise _error("metadata type has its high bit set", track_index=track_index)
            length, offset = _read_vlq(
                source,
                offset,
                end,
                label="metadata length",
                track_index=track_index,
            )
            payload_offset = offset
            payload_end = payload_offset + length
            if payload_end > end:
                raise _error(
                    "metadata payload exceeds track boundary",
                    track_index=track_index,
                )

            if meta_type == _KEY_SIGNATURE:
                if length < 2:
                    raise _error(
                        "key-signature metadata is too short for key and mode",
                        track_index=track_index,
                    )
                payload = source[payload_offset:payload_end]
                signed_key = int.from_bytes(payload[:1], "big", signed=True)
                mode = payload[1]
                invalid_key = not -7 <= signed_key <= 7
                invalid_mode = mode not in (0, 1)
                if invalid_key or invalid_mode:
                    if len(repairs) >= max_repairs:
                        raise _error(
                            f"repair count exceeds configured limit {max_repairs}",
                            track_index=track_index,
                        )
                    reasons = []
                    if invalid_key:
                        reasons.append("signed_key_out_of_range")
                    if invalid_mode:
                        reasons.append("mode_not_major_or_minor")
                    output[meta_type_offset] = _SEQUENCER_SPECIFIC
                    repairs.append(
                        KeySignatureRepair(
                            track_index=track_index,
                            event_index=event_index,
                            tick=tick,
                            event_offset=event_offset,
                            status_offset=status_offset,
                            meta_type_offset=meta_type_offset,
                            payload_offset=payload_offset,
                            original_payload=payload,
                            reason="+".join(reasons),
                        )
                    )
                elif length != 2:
                    raise _error(
                        "otherwise-valid key-signature metadata has extra payload bytes",
                        track_index=track_index,
                    )

            if meta_type == 0x2F:
                if length != 0:
                    raise _error(
                        "end-of-track metadata has a nonzero length",
                        track_index=track_index,
                    )
                saw_end_of_track = True
                if payload_end != end:
                    raise _error(
                        "bytes follow end-of-track metadata",
                        track_index=track_index,
                    )
            offset = payload_end
        else:
            raise _error(
                f"unsupported system status 0x{status:02x}",
                track_index=track_index,
            )

        event_index += 1

    if not saw_end_of_track:
        raise _error("missing end-of-track metadata", track_index=track_index)


def recover_invalid_key_signatures(
    data: bytes, *, max_repairs: int = MAX_REPAIRS
) -> MetadataRecoveryResult:
    """Return a validated SMF copy with only invalid key events made ignorable.

    The input must be a raw SMF payload beginning with ``MThd``. RIFF RMID
    unwrapping remains the caller's responsibility. Any malformed framing,
    event status, channel data, VLQ or truncation fails closed. Valid key
    signatures and all non-key events are returned byte-for-byte unchanged.
    """

    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if isinstance(max_repairs, bool) or not isinstance(max_repairs, int):
        raise TypeError("max_repairs must be an integer")
    if not 1 <= max_repairs <= MAX_REPAIRS:
        raise ValueError(f"max_repairs must be between 1 and {MAX_REPAIRS}")
    if len(data) > MAX_SMF_BYTES:
        raise MetadataRecoveryError(
            f"SMF payload exceeds the {MAX_SMF_BYTES}-byte size limit"
        )
    if len(data) < 14:
        raise _error("truncated header")
    if data[:4] != _HEADER:
        raise _error("missing MThd header")
    header_length = int.from_bytes(data[4:8], "big")
    if header_length != 6:
        raise _error("MThd length is not six bytes")
    file_format = int.from_bytes(data[8:10], "big")
    track_count = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if file_format not in (0, 1, 2):
        raise _error(f"unsupported SMF format {file_format}")
    if track_count == 0:
        raise _error("header declares zero tracks")
    if file_format == 0 and track_count != 1:
        raise _error("format zero must declare exactly one track")
    if division == 0:
        raise _error("time division is zero")

    output = bytearray(data)
    repairs: list[KeySignatureRepair] = []
    event_budget = [0]
    offset = 14
    for track_index in range(track_count):
        if len(data) - offset < 8:
            raise _error("truncated track chunk header", track_index=track_index)
        if data[offset : offset + 4] != _TRACK:
            raise _error("missing MTrk header", track_index=track_index)
        track_length = int.from_bytes(data[offset + 4 : offset + 8], "big")
        track_start = offset + 8
        track_end = track_start + track_length
        if track_end > len(data):
            raise _error(
                "declared track payload exceeds file boundary",
                track_index=track_index,
            )
        _walk_track(
            data,
            output,
            track_start,
            track_end,
            track_index,
            repairs,
            max_repairs,
            event_budget,
        )
        offset = track_end

    if offset != len(data):
        raise _error("bytes follow the declared track chunks")
    sanitized = bytes(output) if repairs else data
    return MetadataRecoveryResult(sanitized, tuple(repairs))
