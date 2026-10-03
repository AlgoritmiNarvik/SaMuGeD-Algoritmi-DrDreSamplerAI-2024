from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import mido
import pytest

from samuged.midi import Note
from scripts.render_drum_solos import (
    resolve_verified_source,
    verify_paired_drum_midi,
    verify_source_drum_notes,
)


def _track(channel: int, *, length: int = 960) -> mido.MidiTrack:
    return mido.MidiTrack(
        [
            mido.Message("program_change", channel=channel, program=0, time=0),
            mido.Message("note_on", channel=channel, note=36, velocity=101, time=120),
            mido.Message("note_off", channel=channel, note=36, velocity=0, time=240),
            mido.MetaMessage("end_of_track", time=length - 360),
        ]
    )


def _midi(path: Path, channels: list[int], *, tempo: int = 500_000, length: int = 960) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    midi.tracks.append(
        mido.MidiTrack(
            [
                mido.MetaMessage("set_tempo", tempo=tempo, time=0),
                mido.MetaMessage("time_signature", numerator=7, denominator=8, time=0),
                mido.MetaMessage("end_of_track", time=length),
            ]
        )
    )
    midi.tracks.extend(_track(channel, length=length) for channel in channels)
    midi.save(path)


def test_drum_only_midi_must_equal_paired_tempo_cycle_and_drum_track(tmp_path: Path) -> None:
    _midi(tmp_path / "paired.mid", [0, 9])
    _midi(tmp_path / "solo.mid", [9])

    verify_paired_drum_midi(tmp_path / "paired.mid", tmp_path / "solo.mid")

    paired = mido.MidiFile(tmp_path / "paired.mid")
    solo = mido.MidiFile(tmp_path / "solo.mid")
    assert solo.tracks[0] == paired.tracks[0]
    assert solo.tracks[1] == paired.tracks[2]
    assert all(sum(message.time for message in track) == 960 for track in solo.tracks)


@pytest.mark.parametrize(
    ("tempo", "length", "channel"),
    [(400_000, 960, 9), (500_000, 1920, 9), (500_000, 960, 0)],
)
def test_drum_only_midi_rejects_tempo_cycle_or_channel_difference(
    tmp_path: Path, tempo: int, length: int, channel: int
) -> None:
    _midi(tmp_path / "paired.mid", [0, 9])
    _midi(tmp_path / "solo.mid", [channel], tempo=tempo, length=length)

    with pytest.raises(ValueError):
        verify_paired_drum_midi(tmp_path / "paired.mid", tmp_path / "solo.mid")


def test_reloaded_source_drum_notes_must_match_paired_metadata() -> None:
    notes = [Note(120, 240, 36, 101), Note(480, 600, 42, 87)]
    metadata = {
        "drum_notes_used": [
            {"start_tick": 120, "end_tick": 240, "pitch": 36, "velocity": 101, "channel": 9},
            {"start_tick": 480, "end_tick": 600, "pitch": 42, "velocity": 87, "channel": 9},
        ]
    }

    verify_source_drum_notes(notes, metadata)
    metadata["drum_notes_used"][1]["velocity"] = 88
    with pytest.raises(ValueError, match="differ from the paired render"):
        verify_source_drum_notes(notes, metadata)


def test_extra_source_is_hash_checked_and_absence_is_an_error(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    extra = tmp_path / "extra"
    primary.mkdir()
    source = extra / "Tool" / "Schism.mid"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    expected = sha256(source.read_bytes()).hexdigest()

    assert resolve_verified_source(primary, (extra,), "Tool/Schism.mid", expected) == (
        source,
        expected,
        "extra:1",
    )
    with pytest.raises(ValueError, match="source hash changed"):
        resolve_verified_source(primary, (extra,), "Tool/Schism.mid", "0" * 64)
    with pytest.raises(FileNotFoundError, match="absent from all configured roots"):
        resolve_verified_source(primary, (extra,), "Tool/Missing.mid", expected)
