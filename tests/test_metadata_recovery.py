from __future__ import annotations

from io import BytesIO

import mido
import pytest

from samuged.metadata_recovery import (
    MAX_REPAIRS,
    MetadataRecoveryError,
    recover_invalid_key_signatures,
)


def _vlq(value: int) -> bytes:
    if value < 0:
        raise ValueError("VLQ value must be nonnegative")
    encoded = [value & 0x7F]
    value >>= 7
    while value:
        encoded.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(encoded))


def _meta(delta: int, meta_type: int, payload: bytes) -> bytes:
    return _vlq(delta) + bytes((0xFF, meta_type)) + _vlq(len(payload)) + payload


def _smf(*tracks: bytes, file_format: int | None = None) -> bytes:
    if file_format is None:
        file_format = 0 if len(tracks) == 1 else 1
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + file_format.to_bytes(2, "big")
        + len(tracks).to_bytes(2, "big")
        + (480).to_bytes(2, "big")
    )
    chunks = b"".join(
        b"MTrk" + len(track).to_bytes(4, "big") + track for track in tracks
    )
    return header + chunks


def _end() -> bytes:
    return _meta(0, 0x2F, b"")


def test_invalid_key_becomes_sequencer_specific_with_exact_payload_receipt() -> None:
    source = _smf(_meta(12, 0x59, b"\xff\xff") + _end())

    result = recover_invalid_key_signatures(source)

    assert result.changed
    assert len(result.repairs) == 1
    repair = result.repairs[0]
    assert repair.track_index == 0
    assert repair.event_index == 0
    assert repair.tick == 12
    assert repair.event_offset == 22
    assert repair.status_offset == 23
    assert repair.meta_type_offset == 24
    assert repair.payload_offset == 26
    assert repair.original_payload == b"\xff\xff"
    assert repair.reason == "mode_not_major_or_minor"
    assert result.data[repair.meta_type_offset] == 0x7F
    assert result.data[repair.payload_offset : repair.payload_offset + 2] == b"\xff\xff"

    parsed = mido.MidiFile(file=BytesIO(result.data), clip=False)
    message = parsed.tracks[0][0]
    assert message.type == "sequencer_specific"
    assert bytes(message.data) == b"\xff\xff"


def test_invalid_key_with_extra_payload_preserves_every_payload_byte() -> None:
    source = _smf(_meta(0, 0x59, b"\x0c\x5f\x3a") + _end())

    result = recover_invalid_key_signatures(source)

    repair = result.repairs[0]
    assert repair.original_payload == b"\x0c\x5f\x3a"
    assert (
        result.data[repair.payload_offset : repair.payload_offset + 3]
        == repair.original_payload
    )
    message = mido.MidiFile(file=BytesIO(result.data), clip=False).tracks[0][0]
    assert message.type == "sequencer_specific"
    assert bytes(message.data) == b"\x0c\x5f\x3a"


def test_valid_keys_and_unrelated_events_are_byte_identical() -> None:
    track = (
        _meta(0, 0x59, b"\xf9\x00")
        + _meta(4, 0x59, b"\x07\x01")
        + b"\x00\x90\x3c\x40\x10\x3c\x00"
        + _end()
    )
    source = _smf(track)

    result = recover_invalid_key_signatures(source)

    assert not result.changed
    assert result.repairs == ()
    assert result.data is source


def test_embedded_ff59_bytes_in_text_and_sysex_are_not_scanned_as_events() -> None:
    embedded = b"prefix\xff\x59\x02\x7f\xffsuffix"
    sysex = b"\x00\xf0" + _vlq(len(embedded)) + embedded
    source = _smf(
        _meta(0, 0x01, embedded)
        + sysex
        + _meta(0, 0x59, b"\x08\x00")
        + _end()
    )

    result = recover_invalid_key_signatures(source)

    assert len(result.repairs) == 1
    repair = result.repairs[0]
    assert repair.original_payload == b"\x08\x00"
    differences = [
        index for index, (before, after) in enumerate(zip(source, result.data))
        if before != after
    ]
    assert differences == [repair.meta_type_offset]
    assert result.data.count(embedded) == 2


def test_running_status_is_validated_and_preserved_across_metadata() -> None:
    track = (
        b"\x00\x90\x3c\x40"
        + b"\x10\x3c\x00"
        + _meta(3, 0x59, b"\x00\x02")
        + b"\x00\x3d\x41"
        + b"\x10\x3d\x00"
        + _end()
    )
    source = _smf(track)

    result = recover_invalid_key_signatures(source)

    assert len(result.repairs) == 1
    assert result.repairs[0].tick == 19
    parsed = mido.MidiFile(file=BytesIO(result.data), clip=False)
    channel_messages = [message for message in parsed.tracks[0] if not message.is_meta]
    assert [(message.type, message.note, message.velocity) for message in channel_messages] == [
        ("note_on", 60, 64),
        ("note_on", 60, 0),
        ("note_on", 61, 65),
        ("note_on", 61, 0),
    ]


def test_byte_diff_is_limited_to_recorded_metadata_type_offsets() -> None:
    first = _meta(0, 0x59, b"\x08\x00")
    valid = _meta(1, 0x59, b"\x00\x01")
    second = _meta(129, 0x59, b"\x02\x02")
    source = _smf(first + valid + second + _end())

    result = recover_invalid_key_signatures(source)

    allowed = {repair.meta_type_offset for repair in result.repairs}
    actual = {
        index for index, (before, after) in enumerate(zip(source, result.data))
        if before != after
    }
    assert len(source) == len(result.data)
    assert len(result.repairs) == 2
    assert actual == allowed
    assert all(source[index] == 0x59 and result.data[index] == 0x7F for index in actual)
    assert [repair.original_payload for repair in result.repairs] == [
        b"\x08\x00",
        b"\x02\x02",
    ]


@pytest.mark.parametrize(
    "track",
    [
        b"\x00\x3c\x40" + _end(),
        b"\x00\x90\x3c\xff" + _end(),
        b"\x00\xf1\x00" + _end(),
        b"\x00\x90\x3c\x40\x00\xf0\x01\xf7\x00\x3d\x40" + _end(),
        b"\x81",
        b"\x00\xff\x01\x05ab" + _end(),
        _meta(0, 0x59, b"\x00") + _end(),
        _meta(0, 0x59, b"\x00\x00\x7f") + _end(),
        b"\x00\xff\x2f\x01\x00",
        _end() + b"\x00",
    ],
)
def test_malformed_event_data_fails_closed(track: bytes) -> None:
    with pytest.raises(MetadataRecoveryError):
        recover_invalid_key_signatures(_smf(track))


@pytest.mark.parametrize(
    "source",
    [
        b"not midi",
        b"MThd" + (5).to_bytes(4, "big") + b"\x00" * 6,
        _smf(_end())[:-1],
        _smf(_end()) + b"trailing",
        _smf(_end(), file_format=1).replace(b"MTrk", b"JUNK", 1),
    ],
)
def test_malformed_smf_framing_fails_closed(source: bytes) -> None:
    with pytest.raises(MetadataRecoveryError):
        recover_invalid_key_signatures(source)


def test_repair_receipts_are_bounded_and_failure_returns_no_partial_result() -> None:
    source = _smf(
        _meta(0, 0x59, b"\x08\x00")
        + _meta(0, 0x59, b"\x09\x00")
        + _end()
    )

    with pytest.raises(MetadataRecoveryError, match="repair count exceeds"):
        recover_invalid_key_signatures(source, max_repairs=1)
    with pytest.raises(ValueError, match="between 1"):
        recover_invalid_key_signatures(source, max_repairs=MAX_REPAIRS + 1)
    assert source.count(b"\xff\x59\x02") == 2
