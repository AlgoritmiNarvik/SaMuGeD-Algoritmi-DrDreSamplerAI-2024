from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import struct

import mido
import pytest

import samuged.midi as midi_module
from samuged.midi import MidiSong, Note, Part, bar_length, export_phrase, load_midi


def _write_midi(
    tmp_path: Path,
    tracks: list[list[mido.Message | mido.MetaMessage]],
    *,
    ticks: int = 480,
) -> Path:
    midi = mido.MidiFile(type=1, ticks_per_beat=ticks)
    for messages in tracks:
        track = mido.MidiTrack(messages)
        if not track or track[-1].type != "end_of_track":
            track.append(mido.MetaMessage("end_of_track", time=0))
        midi.tracks.append(track)
    path = tmp_path / "input.mid"
    midi.save(path)
    return path


def _absolute_messages(
    track: mido.MidiTrack,
) -> list[tuple[int, mido.Message | mido.MetaMessage]]:
    tick = 0
    result = []
    for message in track:
        tick += message.time
        result.append((tick, message))
    return result


def _riff_chunk(chunk_id: bytes, payload: bytes, *, pad: bool = True) -> bytes:
    padding = b"\x00" if pad and len(payload) % 2 else b""
    return chunk_id + len(payload).to_bytes(4, "little") + payload + padding


def _riff_rmid(*chunks: bytes, form: bytes = b"RMID") -> bytes:
    body = form + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _raw_invalid_key_smf(*, malformed_tail: bytes = b"") -> bytes:
    track = (
        b"\x00\xff\x51\x03\x07\xa1\x20"
        b"\x00\xff\x58\x04\x03\x02\x18\x08"
        b"\x0c\xff\x59\x02\xff\xff"
        b"\x00\x90\x3c\x50"
        b"\x78\x80\x3c\x00"
        + malformed_tail
        + b"\x00\xff\x2f\x00"
    )
    return (
        b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0"
        + b"MTrk"
        + len(track).to_bytes(4, "big")
        + track
    )


def test_source_ticks_and_meter_changes_drive_bar_length(tmp_path: Path) -> None:
    path = _write_midi(
        tmp_path,
        [
            [
                mido.MetaMessage(
                    "time_signature", numerator=6, denominator=8, time=0
                ),
                mido.MetaMessage(
                    "time_signature", numerator=3, denominator=4, time=1440
                ),
            ],
            [
                mido.Message("note_on", channel=0, note=64, velocity=90, time=120),
                mido.Message("note_off", channel=0, note=64, velocity=0, time=360),
            ],
        ],
        ticks=480,
    )

    song = load_midi(path)

    assert song.ticks_per_beat == 480
    assert song.meters == [(0, 6, 8), (1440, 3, 4)]
    assert song.parts[0].notes == [Note(start=120, end=480, pitch=64, velocity=90)]
    assert bar_length(song, 1439) == 1440.0
    assert bar_length(song, 1440) == 1440.0


def test_defaults_velocity_zero_fifo_pairing_and_malformed_warnings(
    tmp_path: Path,
) -> None:
    path = _write_midi(
        tmp_path,
        [
            [
                mido.Message("note_on", channel=2, note=60, velocity=70, time=0),
                mido.Message("note_on", channel=2, note=60, velocity=80, time=10),
                mido.Message("note_on", channel=2, note=60, velocity=0, time=10),
                mido.Message("note_off", channel=2, note=60, velocity=44, time=10),
                mido.Message("note_on", channel=2, note=61, velocity=55, time=0),
                mido.Message("note_off", channel=2, note=61, velocity=0, time=0),
                mido.Message("note_off", channel=2, note=63, velocity=0, time=1),
                mido.Message("note_on", channel=2, note=62, velocity=50, time=1),
            ]
        ],
    )

    song = load_midi(path)

    assert song.tempos == [(0, 500_000)]
    assert song.meters == [(0, 4, 4)]
    assert song.parts[0].notes == [
        Note(start=0, end=20, pitch=60, velocity=70),
        Note(start=10, end=30, pitch=60, velocity=80),
    ]
    assert any("zero-duration note" in warning for warning in song.warnings)
    assert any("note-off without note-on" in warning for warning in song.warnings)
    assert any("dangling note-on" in warning for warning in song.warnings)


def test_parts_split_by_track_channel_and_program_with_drums(tmp_path: Path) -> None:
    path = _write_midi(
        tmp_path,
        [
            [
                mido.MetaMessage("track_name", name="Band", time=0),
                mido.Message("program_change", channel=0, program=12, time=0),
                mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
                mido.Message("note_off", channel=0, note=60, velocity=0, time=10),
                mido.Message("program_change", channel=0, program=13, time=0),
                mido.Message("note_on", channel=0, note=62, velocity=91, time=0),
                mido.Message("note_off", channel=0, note=62, velocity=0, time=10),
                mido.Message("note_on", channel=9, note=36, velocity=100, time=0),
                mido.Message("note_off", channel=9, note=36, velocity=0, time=10),
            ],
            [
                mido.Message("note_on", channel=0, note=65, velocity=75, time=0),
                mido.Message("note_off", channel=0, note=65, velocity=0, time=20),
            ],
        ],
    )

    song = load_midi(path)

    assert [
        (part.index, part.track, part.channel, part.program, part.name, part.is_drum)
        for part in song.parts
    ] == [
        (0, 0, 0, 12, "Band", False),
        (1, 1, 0, 12, "", False),
        (2, 0, 0, 13, "Band", False),
        (3, 0, 9, 0, "Band", True),
    ]


def test_format_one_program_changes_follow_global_timeline_without_cross_track_pairing(
    tmp_path: Path,
) -> None:
    path = _write_midi(
        tmp_path,
        [
            [
                mido.Message("program_change", channel=2, program=41, time=10),
                mido.Message("program_change", channel=2, program=42, time=10),
            ],
            [
                mido.Message("note_on", channel=2, note=60, velocity=71, time=10),
                mido.Message("note_off", channel=2, note=60, velocity=0, time=5),
                mido.Message("note_on", channel=2, note=62, velocity=72, time=5),
                mido.Message("note_off", channel=2, note=62, velocity=0, time=5),
            ],
            [
                mido.Message("program_change", channel=2, program=50, time=10),
                mido.Message("note_on", channel=2, note=60, velocity=73, time=0),
                mido.Message("note_off", channel=2, note=60, velocity=0, time=20),
            ],
        ],
    )

    song = load_midi(path)

    assert [
        (part.index, part.track, part.channel, part.program, part.notes)
        for part in song.parts
    ] == [
        (0, 1, 2, 41, [Note(10, 15, 60, 71)]),
        (1, 2, 2, 50, [Note(10, 30, 60, 73)]),
        (2, 1, 2, 42, [Note(20, 25, 62, 72)]),
    ]


def test_export_crops_notes_and_shifts_only_active_and_internal_metadata(
    tmp_path: Path,
) -> None:
    notes = [
        Note(240, 400, 60, 70),
        Note(400, 1_000, 62, 80),
        Note(1_000, 1_100, 64, 90),
    ]
    part = Part(0, 3, 4, 27, "Lead", False, notes)
    song = MidiSong(
        ticks_per_beat=480,
        parts=[part],
        tempos=[(0, 500_000), (240, 400_000), (480, 300_000), (960, 200_000)],
        meters=[(0, 4, 4), (600, 3, 4), (900, 7, 8)],
        warnings=[],
    )
    original = deepcopy(song)
    output = tmp_path / "phrase.mid"

    export_phrase(song, part, notes, 300, 900, output)

    assert song == original
    raw = mido.MidiFile(output)
    metadata = _absolute_messages(raw.tracks[0])
    assert [
        (tick, message.tempo)
        for tick, message in metadata
        if message.type == "set_tempo"
    ] == [(0, 400_000), (180, 300_000)]
    assert [
        (tick, message.numerator, message.denominator)
        for tick, message in metadata
        if message.type == "time_signature"
    ] == [(0, 4, 4), (300, 3, 4)]

    exported = load_midi(output)
    assert exported.tempos == [(0, 400_000), (180, 300_000)]
    assert exported.meters == [(0, 4, 4), (300, 3, 4)]
    assert len(exported.parts) == 1
    exported_part = exported.parts[0]
    assert (exported_part.channel, exported_part.program, exported_part.name) == (
        4,
        27,
        "Lead",
    )
    assert exported_part.notes == [
        Note(0, 100, 60, 70),
        Note(100, 600, 62, 80),
    ]


def test_rejects_malformed_type_two_and_smpte_files(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.mid"
    malformed.write_bytes(b"not a MIDI file")
    with pytest.raises(ValueError, match="MThd"):
        load_midi(malformed)

    type_two = mido.MidiFile(type=2, ticks_per_beat=480)
    type_two.tracks.append(mido.MidiTrack([mido.MetaMessage("end_of_track")]))
    type_two_path = tmp_path / "type-two.mid"
    type_two.save(type_two_path)
    with pytest.raises(ValueError, match="format 2"):
        load_midi(type_two_path)

    smpte = tmp_path / "smpte.mid"
    smpte.write_bytes(
        b"MThd"
        + struct.pack(">Ihhh", 6, 0, 1, -6360)
        + b"MTrk"
        + struct.pack(">I", 4)
        + b"\x00\xff\x2f\x00"
    )
    with pytest.raises(ValueError, match="SMPTE"):
        load_midi(smpte)


def test_rejects_wrong_extension_and_input_over_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_extension = tmp_path / "song.bin"
    wrong_extension.write_bytes(b"MThd")
    with pytest.raises(ValueError, match=r"\.mid"):
        load_midi(wrong_extension)

    oversized = tmp_path / "oversized.mid"
    oversized.write_bytes(b"MThd" + b"\x00" * 32)
    monkeypatch.setattr(midi_module, "MAX_MIDI_BYTES", 16)
    with pytest.raises(ValueError, match="size limit"):
        load_midi(oversized)


def test_loads_aligned_riff_rmid_data_chunk_with_provenance(tmp_path: Path) -> None:
    smf_path = _write_midi(
        tmp_path,
        [
            [
                mido.Message("note_on", channel=1, note=67, velocity=88, time=12),
                mido.Message("note_off", channel=1, note=67, velocity=0, time=24),
            ]
        ],
    )
    smf = smf_path.read_bytes()
    wrapped = _riff_rmid(
        _riff_chunk(b"JUNK", b"odd"),
        _riff_chunk(b"data", smf),
        _riff_chunk(b"LIST", b"INFO"),
    )
    rmid_path = tmp_path / "wrapped.mid"
    rmid_path.write_bytes(wrapped)

    song = load_midi(rmid_path)

    assert song.parts[0].notes == [Note(12, 36, 67, 88)]
    assert song.warnings == ["riff_rmid_unwrapped"]


def test_invalid_key_recovery_is_explicit_and_preserves_musical_data(
    tmp_path: Path,
) -> None:
    source = _raw_invalid_key_smf()
    path = tmp_path / "invalid-key.mid"
    path.write_bytes(source)

    with pytest.raises(mido.KeySignatureError):
        load_midi(path)

    song = load_midi(path, recover_invalid_keys=True)

    assert path.read_bytes() == source
    assert song.parts[0].notes == [Note(12, 132, 60, 80)]
    assert song.tempos == [(0, 500_000)]
    assert song.meters == [(0, 3, 4)]
    assert song.warnings == [
        "invalid_key_signature_metadata_recovered: 1 event(s) retyped "
        "as sequencer-specific; see metadata_repairs"
    ]
    assert len(song.metadata_repairs) == 1
    receipt = song.metadata_repairs[0]
    assert receipt["kind"] == "invalid_key_signature_retyped_as_sequencer_specific"
    assert receipt["tick"] == 12
    assert receipt["offset_basis"] == "unwrapped_smf_bytes"
    assert receipt["original_payload_hex"] == "ffff"
    assert receipt["reason"] == "mode_not_major_or_minor"
    assert receipt["original_smf_sha256"] != receipt["recovered_smf_sha256"]
    json.dumps(song.metadata_repairs)


def test_valid_file_ignores_recovery_option_and_has_no_receipts(tmp_path: Path) -> None:
    path = _write_midi(
        tmp_path,
        [[mido.MetaMessage("key_signature", key="F", time=0)]],
    )

    strict = load_midi(path)
    opted_in = load_midi(path, recover_invalid_keys=True)

    assert opted_in == strict
    assert strict.metadata_repairs == []
    assert not any("recovered" in warning for warning in strict.warnings)


def test_rmid_recovery_offsets_are_relative_to_unwrapped_smf(tmp_path: Path) -> None:
    smf = _raw_invalid_key_smf()
    wrapped = _riff_rmid(
        _riff_chunk(b"JUNK", b"prefix-data"),
        _riff_chunk(b"data", smf),
    )
    path = tmp_path / "invalid-key-rmid.mid"
    path.write_bytes(wrapped)

    song = load_midi(path, recover_invalid_keys=True)

    receipt = song.metadata_repairs[0]
    assert receipt["offset_basis"] == "unwrapped_smf_bytes"
    assert receipt["meta_type_offset"] == smf.index(b"\xff\x59") + 1
    data_chunk = wrapped.index(b"data" + len(smf).to_bytes(4, "little"))
    smf_start_in_riff = data_chunk + 8
    assert wrapped[smf_start_in_riff + receipt["meta_type_offset"]] == 0x59
    assert smf_start_in_riff + receipt["meta_type_offset"] != receipt["meta_type_offset"]
    assert song.warnings[0] == "riff_rmid_unwrapped"
    assert len([warning for warning in song.warnings if "recovered" in warning]) == 1
    assert path.read_bytes() == wrapped


def test_opt_in_recovery_fails_closed_on_other_malformed_events(
    tmp_path: Path,
) -> None:
    source = _raw_invalid_key_smf(malformed_tail=b"\x00\x90\x40\xff")
    path = tmp_path / "invalid-key-and-channel-data.mid"
    path.write_bytes(source)

    with pytest.raises(ValueError, match="channel data byte"):
        load_midi(path, recover_invalid_keys=True)
    assert path.read_bytes() == source


def test_riff_parser_rejects_truncation_smuggling_and_invalid_chunk_boundaries(
    tmp_path: Path,
) -> None:
    smf_path = _write_midi(tmp_path, [[]])
    smf = smf_path.read_bytes()
    valid = _riff_rmid(_riff_chunk(b"data", smf))
    missing_pad_chunk = _riff_chunk(b"JUNK", b"odd", pad=False)
    malformed_cases = [
        ("wrong-form", _riff_rmid(_riff_chunk(b"data", smf), form=b"WAVE"), "not RMID"),
        (
            "truncated-riff",
            b"RIFF" + (len(valid) + 8).to_bytes(4, "little") + valid[8:],
            "truncated RIFF payload",
        ),
        (
            "missing-pad",
            _riff_rmid(missing_pad_chunk),
            "missing chunk padding",
        ),
        (
            "embedded-header",
            _riff_rmid(_riff_chunk(b"JUNK", b"MThd" + smf)),
            "missing MIDI data chunk",
        ),
        (
            "offset-header",
            _riff_rmid(_riff_chunk(b"data", b"xxxx" + smf)),
            "does not start with MThd",
        ),
        (
            "chunk-overrun",
            _riff_rmid(
                b"data" + (len(smf) + 1).to_bytes(4, "little") + smf
            ),
            "chunk exceeds RIFF boundary",
        ),
        ("trailing-data", valid + b"x", "follows the RIFF boundary"),
        (
            "duplicate-data",
            _riff_rmid(_riff_chunk(b"data", smf), _riff_chunk(b"data", smf)),
            "multiple data chunks",
        ),
    ]

    for name, payload, match in malformed_cases:
        path = tmp_path / f"{name}.mid"
        path.write_bytes(payload)
        with pytest.raises(ValueError, match=match):
            load_midi(path)


@pytest.mark.parametrize(
    ("message", "match"),
    [
        (mido.MetaMessage("set_tempo", tempo=0), "tempo"),
        (
            mido.MetaMessage("time_signature", numerator=0, denominator=4),
            "meter numerator",
        ),
    ],
)
def test_rejects_nonpositive_tempo_and_meter_numerator(
    tmp_path: Path, message: mido.MetaMessage, match: str
) -> None:
    path = _write_midi(tmp_path, [[message]])

    with pytest.raises(ValueError, match=match):
        load_midi(path)


@pytest.mark.parametrize(
    ("start", "end", "match"),
    [
        (10, 10, "positive duration"),
        (11, 10, "positive duration"),
        (-1, 10, "start"),
    ],
)
def test_export_validates_region(
    tmp_path: Path, start: int, end: int, match: str
) -> None:
    song = MidiSong(480, [], [(0, 500_000)], [(0, 4, 4)], [])
    part = Part(0, 0, 0, 0, "", False, [])

    with pytest.raises(ValueError, match=match):
        export_phrase(song, part, [], start, end, tmp_path / "bad.mid")


def test_export_preserves_requested_tail_silence(tmp_path):
    song = MidiSong(480, [], [(0, 500000)], [(0, 4, 4)], [])
    part = Part(0, 0, 9, 0, 'drums', True, [Note(0, 60, 36, 100)])
    output = tmp_path / 'tail.mid'
    export_phrase(song, part, part.notes, 0, 1920, output)
    exported = mido.MidiFile(output)
    assert all(sum(message.time for message in track) == 1920 for track in exported.tracks)
