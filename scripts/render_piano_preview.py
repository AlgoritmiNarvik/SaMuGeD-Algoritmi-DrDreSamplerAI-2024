"""Render a labelled piano timbre alternative without changing source notes."""
from dataclasses import replace
from hashlib import sha256
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from samuged.audio_loops import (
    RENDER_REPETITIONS, _optional_audio, _render_audio, _renderer_provenance, _resolve_source,
    source_cycle_notes, write_repeated_midi,
)
from samuged.midi import export_phrase, load_midi
from scripts.render_tool_layers import file_record


def render(audio: Path, source_root: Path, soundfont: Path, output: Path,
           fluidsynth: Path, ffmpeg: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((audio / "metadata.json").read_text())
    source = _resolve_source(source_root, original["source_path"])
    if sha256(source.read_bytes()).hexdigest() != original["source_sha256"]:
        raise ValueError("source hash changed")
    song = load_midi(source, recover_invalid_keys=True)
    source_part = next(p for p in song.parts if p.index == original["part"]["index"])
    if source_part.is_drum:
        raise ValueError("piano preview requires a melodic part")
    part = replace(source_part, program=0)
    start = original["cycle_start_tick"]
    period = original["period"]["period_ticks"]
    notes = source_cycle_notes(part, start, period)
    pid = original["phrase_id"] + "-piano"
    target = output / pid
    target.mkdir()
    export_phrase(song, part, notes, start, start + period, target / "loop.mid")
    with tempfile.TemporaryDirectory(prefix="samuged-piano-") as temporary:
        repeated = Path(temporary) / "repeated.mid"
        write_repeated_midi(song, part, notes, start, period, RENDER_REPETITIONS, repeated)
        audio_details = _render_audio(repeated, soundfont, fluidsynth, target / "loop.wav", original["cycle_seconds"])
    _optional_audio(target / "loop.wav", make_mp3=False, make_flac=True, ffmpeg=ffmpeg)
    shutil.copyfile(audio / "source.mid", target / "source.mid")
    metadata = dict(original)
    metadata.update(phrase_id=pid, base_phrase_id=original["phrase_id"],
                    preview_program=0, source_program=source_part.program, audio=audio_details,
                    arrangement="piano_timbre_preview")
    metadata["part"] = {**original["part"], "program": 0}
    metadata["source_export_policy"] += "; labelled piano preview changes the loop instrument program to 0, source.mid retains the original detector export"
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    artifacts = [file_record(target / name, output) for name in
                 ("source.mid", "loop.mid", "loop.wav", "loop.flac", "metadata.json")]
    (target / "hashes.json").write_text(json.dumps({"phrase_id": pid, "artifacts": artifacts}, indent=2) + "\n")
    artifacts.append(file_record(target / "hashes.json", output))
    manifest = {"version": "samuged-piano-preview-v1", "entries": [{"phrase_id": pid, "base_phrase_id": original["phrase_id"], "artifacts": artifacts}],
                "renderer_provenance": _renderer_provenance(fluidsynth, ffmpeg),
                "inputs": {"source_metadata_sha256": sha256((audio / "metadata.json").read_bytes()).hexdigest(),
                           "soundfont_sha256": sha256(soundfont.read_bytes()).hexdigest(),
                           "generator_sha256": sha256(Path(__file__).read_bytes()).hexdigest()},
                "claim": "same source notes and tempo with explicitly changed timbre, not a correction of source musical content"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "receipt.json").write_text(json.dumps({"inputs": manifest["inputs"]}, indent=2) + "\n")
    print("Rendered labelled piano preview", pid)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audio", "source", "soundfont", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--fluidsynth", type=Path, default=Path("/opt/homebrew/bin/fluidsynth"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg"))
    args = parser.parse_args()
    render(args.audio, args.source, args.soundfont, args.output, args.fluidsynth, args.ffmpeg)
