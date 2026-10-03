"""Render aligned Tool riff and drum layers from the same source cycle."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile

import mido

from samuged.audio_loops import (
    RENDER_REPETITIONS, _optional_audio, _render_audio, _resolve_source,
    source_cycle_notes, write_repeated_midi,
)
from samuged.drums import drum_part
from samuged.midi import export_phrase, load_midi


def file_record(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest()}


def combine_tracks(riff: Path, drums: Path, target: Path) -> None:
    """Keep the riff tempo track and append the aligned source drum note track."""
    melody, percussion = mido.MidiFile(riff), mido.MidiFile(drums)
    if melody.ticks_per_beat != percussion.ticks_per_beat:
        raise ValueError("layer tick resolutions differ")
    if len(melody.tracks) != 2 or len(percussion.tracks) != 2:
        raise ValueError("layers must contain metadata and note tracks")
    if sum(m.time for m in melody.tracks[0]) != sum(m.time for m in percussion.tracks[0]):
        raise ValueError("layer cycle lengths differ")
    if any(not m.is_meta and getattr(m, "channel", None) == 9 for m in melody.tracks[1]):
        raise ValueError("riff layer uses the percussion channel")
    if any(not m.is_meta and getattr(m, "channel", None) != 9 for m in percussion.tracks[1]):
        raise ValueError("drum layer is not on the percussion channel")
    melody.tracks.append(percussion.tracks[1])
    melody.save(target)


def render(base: Path, source_root: Path, soundfont: Path, output: Path,
           fluidsynth: Path, ffmpeg: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    selection = json.loads((base / "tool_selection_expanded.json").read_text())
    solos = base / "tool_audio_expanded"
    solo_manifest = json.loads((solos / "manifest.json").read_text())
    entries, diagrams = [], {}
    for candidate in selection["candidates"]:
        pid = candidate["phrase_id"]
        metadata_path = solos / pid / "metadata.json"
        metadata = json.loads(metadata_path.read_text())
        source = _resolve_source(source_root, metadata["source_path"])
        if sha256(source.read_bytes()).hexdigest() != metadata["source_sha256"]:
            raise ValueError("source hash changed")
        song = load_midi(source, recover_invalid_keys=True)
        start = metadata["cycle_start_tick"]
        period = metadata["period"]["period_ticks"]
        drums = drum_part(song)
        hits = source_cycle_notes(drums, start, period)
        # The overlay visualizes source events, it does not infer meter or polyrhythm.
        diagrams[pid] = {
            "ticks_per_beat": song.ticks_per_beat,
            "period_ticks": period,
            "source_meter": metadata["meter_changes"][0],
            "part_name": metadata["part"]["name"] or "Source part",
            "riff_onsets": [{"tick": n["relative_start_tick"], "pitch": n["pitch"], "velocity": n["velocity"]}
                            for n in metadata["source_notes_used"]],
            "drum_onsets": [{"tick": n.start - start, "pitch": n.pitch, "velocity": n.velocity} for n in hits],
        }
        if candidate["kind"] != "melodic" or len(hits) < 4 or len({n.start for n in hits}) < 2:
            continue
        mixed_id = pid + "-with-drums"
        destination = output / mixed_id
        destination.mkdir()
        part = next(p for p in song.parts if p.index == metadata["part"]["index"])
        notes = source_cycle_notes(part, start, period)
        with tempfile.TemporaryDirectory(prefix="samuged-tool-layers-") as temporary:
            temp = Path(temporary)
            # Both layers use identical start, length, source tempo and repetition offsets.
            export_phrase(song, drums, hits, start, start + period, temp / "drums_one.mid")
            combine_tracks(solos / pid / "loop.mid", temp / "drums_one.mid", destination / "loop.mid")
            write_repeated_midi(song, part, notes, start, period, RENDER_REPETITIONS, temp / "riff_repeated.mid")
            write_repeated_midi(song, drums, hits, start, period, RENDER_REPETITIONS, temp / "drums_repeated.mid")
            combine_tracks(temp / "riff_repeated.mid", temp / "drums_repeated.mid", temp / "combined.mid")
            audio = _render_audio(temp / "combined.mid", soundfont, fluidsynth,
                                  destination / "loop.wav", metadata["cycle_seconds"])
        _optional_audio(destination / "loop.wav", make_mp3=False, make_flac=True, ffmpeg=ffmpeg)
        shutil.copyfile(solos / pid / "source.mid", destination / "source.mid")
        mixed = deepcopy(metadata)
        mixed.update(phrase_id=mixed_id, base_phrase_id=pid, arrangement="riff_with_source_drums", audio=audio)
        mixed["source_export_policy"] += "; the combined loop adds source drums from the identical time window, their joint recurrence is not independently verified"
        mixed["drum_notes_used"] = [{"start_tick": n.start, "end_tick": n.end, "pitch": n.pitch,
                                      "velocity": n.velocity, "channel": 9} for n in hits]
        (destination / "metadata.json").write_text(json.dumps(mixed, indent=2) + "\n")
        artifacts = [file_record(destination / name, output) for name in
                     ("source.mid", "loop.mid", "loop.wav", "loop.flac", "metadata.json")]
        (destination / "hashes.json").write_text(json.dumps({"phrase_id": mixed_id, "artifacts": artifacts}, indent=2) + "\n")
        artifacts.append(file_record(destination / "hashes.json", output))
        entries.append({"phrase_id": mixed_id, "base_phrase_id": pid, "kind": "melodic",
                        "source_sha256": metadata["source_sha256"], "artifacts": artifacts})
    manifest = {"version": "samuged-tool-layers-v1", "entries": entries,
                "renderer_provenance": solo_manifest["renderer_provenance"],
                "inputs": {"soundfont_sha256": sha256(soundfont.read_bytes()).hexdigest(),
                           "solo_manifest_sha256": sha256((solos / "manifest.json").read_bytes()).hexdigest(),
                           "selection_sha256": sha256((base / "tool_selection_expanded.json").read_bytes()).hexdigest(),
                           "generator_sha256": sha256(Path(__file__).read_bytes()).hexdigest()},
                "claim": "same source passage with aligned drum layer, no independent joint recurrence claim"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "receipt.json").write_text(json.dumps({"inputs": manifest["inputs"], "entries": len(entries)}, indent=2) + "\n")
    (output / "rhythm_diagrams.json").write_text(json.dumps(diagrams, indent=2) + "\n")
    print(f"Rendered {len(entries)} aligned riff and drum variants")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "source", "soundfont", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--fluidsynth", type=Path, default=Path("/opt/homebrew/bin/fluidsynth"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg"))
    args = parser.parse_args()
    render(args.base, args.source, args.soundfont, args.output, args.fluidsynth, args.ffmpeg)
