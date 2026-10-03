from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import mido
import pytest

from scripts.render_source_layers import (
    combine_aligned_tracks,
    referenced_phrases,
    resolve_source,
    resolve_verified_source,
    verify_source,
)


def _layer(
    path: Path,
    channel: int,
    *,
    ticks_per_beat: int = 480,
    length: int = 960,
    tempo: int = 500_000,
) -> mido.MidiFile:
    midi = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    midi.tracks.append(
        mido.MidiTrack(
            [
                mido.MetaMessage("set_tempo", tempo=tempo, time=0),
                mido.MetaMessage("time_signature", numerator=7, denominator=8, time=0),
                mido.MetaMessage("end_of_track", time=length),
            ]
        )
    )
    midi.tracks.append(
        mido.MidiTrack(
            [
                mido.Message("program_change", channel=channel, program=33, time=0),
                mido.Message("note_on", channel=channel, note=36, velocity=101, time=120),
                mido.Message("note_off", channel=channel, note=36, velocity=0, time=240),
                mido.MetaMessage("end_of_track", time=length - 360),
            ]
        )
    )
    midi.save(path)
    return midi


def test_combined_layers_preserve_identical_cycle_and_source_drum_events(tmp_path: Path) -> None:
    melody = _layer(tmp_path / "melody.mid", 0)
    drums = _layer(tmp_path / "drums.mid", 9)

    combine_aligned_tracks(
        tmp_path / "melody.mid", tmp_path / "drums.mid", tmp_path / "combined.mid"
    )

    combined = mido.MidiFile(tmp_path / "combined.mid", clip=False)
    assert combined.ticks_per_beat == melody.ticks_per_beat
    assert combined.tracks == [melody.tracks[0], melody.tracks[1], drums.tracks[1]]
    assert all(
        sum(message.time for message in track) == 960 for track in combined.tracks
    )
    assert [
        (message.channel, message.note, message.velocity)
        for message in combined.tracks[2]
        if message.type == "note_on"
    ] == [(9, 36, 101)]


@pytest.mark.parametrize(
    ("ticks_per_beat", "length", "tempo", "channel"),
    [
        (960, 960, 500_000, 9),
        (480, 1920, 500_000, 9),
        (480, 960, 400_000, 9),
        (480, 960, 500_000, 0),
    ],
)
def test_combiner_rejects_different_clock_cycle_tempo_or_non_drum_track(
    tmp_path: Path, ticks_per_beat: int, length: int, tempo: int, channel: int
) -> None:
    _layer(tmp_path / "melody.mid", 0)
    _layer(
        tmp_path / "drums.mid",
        channel,
        ticks_per_beat=ticks_per_beat,
        length=length,
        tempo=tempo,
    )

    with pytest.raises(ValueError):
        combine_aligned_tracks(
            tmp_path / "melody.mid", tmp_path / "drums.mid", tmp_path / "combined.mid"
        )


def test_source_resolution_distinguishes_absence_and_rejects_escape(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "artist" / "song.mid"
    source.parent.mkdir()
    source.write_bytes(b"source-midi")
    outside = tmp_path / "outside.mid"
    outside.write_bytes(b"outside")

    assert resolve_source(source_root, "artist/song.mid") == source
    assert resolve_source(source_root, "artist/missing.mid") is None
    with pytest.raises(ValueError, match="escapes"):
        resolve_source(source_root, "../outside.mid")


def test_source_hash_must_match_metadata(tmp_path: Path) -> None:
    source = tmp_path / "song.mid"
    source.write_bytes(b"verified source")
    expected = sha256(source.read_bytes()).hexdigest()

    assert verify_source(source, expected) == expected
    with pytest.raises(ValueError, match="source hash changed"):
        verify_source(source, "0" * 64)


def test_extra_source_is_a_hash_checked_fallback_and_missing_is_an_error(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    extra = tmp_path / "extra"
    primary.mkdir()
    source = extra / "Tool" / "Schism.mid"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"external source")
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


def test_supplemental_selection_is_unioned_with_catalog_and_atlas(tmp_path: Path) -> None:
    space = tmp_path / "space"
    (space / "atlas").mkdir(parents=True)
    (space / "catalog.json").write_text(
        '{"groups":{"motifs":{"rows":[{"phrase_id":"catalog-id"}]}}}'
    )
    (space / "atlas" / "analysis.json").write_text(
        '{"snippets":{"atlas-id":[]}}'
    )
    selection = tmp_path / "selection.json"
    selection.write_text('{"candidates":[{"phrase_id":"extra-id"}]}')

    assert referenced_phrases(space, (selection,)) == {
        "atlas-id": ["atlas"],
        "catalog-id": ["catalog:motifs"],
        "extra-id": ["supplemental_selection:selection.json"],
    }
