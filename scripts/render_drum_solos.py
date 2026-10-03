"""Render source drum-only cycles for selected Tool melodic phrases."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

import mido

from samuged.audio_loops import (
    RENDER_REPETITIONS,
    SAMPLE_RATE,
    STEADY_REPETITION,
    VERSION,
    _optional_audio,
    _render_audio,
    _renderer_provenance,
    seconds_between,
    source_cycle_notes,
    write_repeated_midi,
)
from samuged.drums import drum_part
from samuged.midi import Note, export_phrase, load_midi


MANIFEST_VERSION = "samuged-drum-solos-v1"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _resolve_source(source_root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        raise ValueError("source_path must be a nonempty string")
    resolved_root = source_root.resolve(strict=True)
    try:
        source = (resolved_root / relative).resolve(strict=True)
    except FileNotFoundError:
        return None
    if not source.is_relative_to(resolved_root) or not source.is_file():
        raise ValueError(f"source_path escapes or is not a file: {relative!r}")
    return source


def _verify_source(path: Path, expected_sha256: object) -> str:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"source hash changed: {path}")
    return actual


def selected_phrases(selection_paths: tuple[Path, ...]) -> dict[str, dict[str, Any]]:
    """Union selection candidates while retaining their source selection labels."""

    selected: dict[str, dict[str, Any]] = {}
    for selection_path in selection_paths:
        selection = _json(selection_path)
        candidates = selection.get("candidates") if isinstance(selection, dict) else None
        if not isinstance(candidates, list):
            raise ValueError(f"selection has no candidates: {selection_path}")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError(f"selection has a non-object candidate: {selection_path}")
            phrase_id = candidate.get("phrase_id")
            kind = candidate.get("kind")
            if not isinstance(phrase_id, str) or not phrase_id:
                raise ValueError(f"selection has an invalid phrase ID: {selection_path}")
            if kind not in {"melodic", "percussion"}:
                raise ValueError(f"selection has an invalid phrase kind: {selection_path}")
            row = selected.setdefault(phrase_id, {"kind": kind, "selections": []})
            if row["kind"] != kind:
                raise ValueError(f"phrase kind differs between selections: {phrase_id}")
            row["selections"].append(str(selection_path))
    return dict(sorted(selected.items()))


def _verify_artifacts(root: Path, entry: dict[str, Any]) -> None:
    for artifact in entry["artifacts"]:
        path = root / artifact["path"]
        if (
            not path.resolve().is_relative_to(root.resolve())
            or not path.is_file()
            or path.stat().st_size != artifact["bytes"]
            or _sha256_file(path) != artifact["sha256"]
        ):
            raise ValueError(f"artifact does not match its receipt: {path}")


def paired_variants(
    combined_roots: tuple[Path, ...],
) -> tuple[dict[str, tuple[Path, dict[str, Any]]], list[dict[str, str]]]:
    """Index verified combined variants by their melodic base phrase ID."""

    variants: dict[str, tuple[Path, dict[str, Any]]] = {}
    inputs: list[dict[str, str]] = []
    for root in combined_roots:
        manifest_path = root / "manifest.json"
        manifest = _json(manifest_path)
        inputs.append({"path": str(manifest_path), "sha256": _sha256_file(manifest_path)})
        for entry in manifest["entries"]:
            base_phrase_id = entry.get("base_phrase_id")
            phrase_id = entry.get("phrase_id")
            if not isinstance(base_phrase_id, str) or phrase_id != f"{base_phrase_id}-with-drums":
                raise ValueError(f"combined manifest has an invalid paired entry: {root}")
            if base_phrase_id in variants:
                raise ValueError(f"duplicate combined variant for {base_phrase_id}")
            variants[base_phrase_id] = (root, entry)
    return variants, inputs


def resolve_verified_source(
    source_root: Path,
    extra_source_roots: tuple[Path, ...],
    relative: object,
    expected_sha256: object,
) -> tuple[Path, str, str]:
    """Resolve and hash-check the first present source in ordered roots."""

    roots = (("primary", source_root),) + tuple(
        (f"extra:{index}", root) for index, root in enumerate(extra_source_roots, 1)
    )
    for label, root in roots:
        source = _resolve_source(root, relative)
        if source is not None:
            return source, _verify_source(source, expected_sha256), label
    raise FileNotFoundError(f"source MIDI is absent from all configured roots: {relative!r}")


def _track_end(track: mido.MidiTrack) -> int:
    return sum(message.time for message in track)


def verify_paired_drum_midi(paired_path: Path, solo_path: Path) -> None:
    """Require a drum solo to equal the combined variant's aligned drum cycle."""

    paired = mido.MidiFile(paired_path, clip=False)
    solo = mido.MidiFile(solo_path, clip=False)
    if paired.ticks_per_beat != solo.ticks_per_beat:
        raise ValueError("paired and drum-only tick resolutions differ")
    if len(paired.tracks) != 3 or len(solo.tracks) != 2:
        raise ValueError("paired or drum-only MIDI has an unexpected track count")
    if paired.tracks[0] != solo.tracks[0]:
        raise ValueError("paired and drum-only tempo or meter tracks differ")
    if paired.tracks[2] != solo.tracks[1]:
        raise ValueError("drum-only events differ from the paired source drum track")
    cycle_ticks = _track_end(solo.tracks[0])
    if any(_track_end(track) != cycle_ticks for track in (*paired.tracks, *solo.tracks)):
        raise ValueError("paired and drum-only cycle lengths differ")
    if any(
        not message.is_meta and getattr(message, "channel", None) != 9
        for message in solo.tracks[1]
    ):
        raise ValueError("drum-only notes are not on the percussion channel")


def _note_rows(notes: list[Note], start_tick: int) -> list[dict[str, int]]:
    return [
        {
            "start_tick": note.start,
            "end_tick": note.end,
            "relative_start_tick": note.start - start_tick,
            "relative_end_tick": note.end - start_tick,
            "pitch": note.pitch,
            "velocity": note.velocity,
            "channel": 9,
        }
        for note in notes
    ]


def verify_source_drum_notes(notes: list[Note], paired_metadata: dict[str, Any]) -> None:
    """Require reloaded source strikes to match paired-render provenance."""

    actual = [
        (note.start, note.end, note.pitch, note.velocity, 9)
        for note in notes
    ]
    expected = [
        (
            row["start_tick"],
            row["end_tick"],
            row["pitch"],
            row["velocity"],
            row["channel"],
        )
        for row in paired_metadata["drum_notes_used"]
    ]
    if actual != expected:
        raise ValueError("source drum notes differ from the paired render metadata")


def _load_prior_entries(output: Path) -> dict[str, dict[str, Any]]:
    if not output.exists():
        output.mkdir(parents=True)
        return {}
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        raise FileExistsError(f"output exists without a resumable manifest: {output}")
    manifest = _json(manifest_path)
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("existing output uses a different manifest version")
    entries = {entry["base_phrase_id"]: entry for entry in manifest["entries"]}
    if len(entries) != len(manifest["entries"]):
        raise ValueError("existing manifest has duplicate base phrase entries")
    for entry in entries.values():
        _verify_artifacts(output, entry)
    return entries


def render(
    space: Path,
    source_root: Path,
    extra_source_roots: tuple[Path, ...],
    selection_paths: tuple[Path, ...],
    combined_roots: tuple[Path, ...],
    soundfont: Path,
    output: Path,
    fluidsynth: Path,
    ffmpeg: Path,
) -> dict[str, Any]:
    """Render exact source drum tracks for selected phrases with paired variants."""

    if not selection_paths:
        raise ValueError("at least one selection is required")
    if not combined_roots:
        raise ValueError("at least one combined render root is required")
    prior_entries = _load_prior_entries(output)
    selected = selected_phrases(selection_paths)
    paired, combined_inputs = paired_variants(combined_roots)
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    loaded_sources: dict[Path, Any] = {}

    for phrase_id, selection in selected.items():
        if selection["kind"] != "melodic":
            skipped.append(
                {
                    "phrase_id": phrase_id,
                    "kind": selection["kind"],
                    "selections": selection["selections"],
                    "reason": "percussion_selection",
                }
            )
            continue
        paired_record = paired.get(phrase_id)
        if paired_record is None:
            skipped.append(
                {
                    "phrase_id": phrase_id,
                    "kind": "melodic",
                    "selections": selection["selections"],
                    "reason": "no_combined_source_drum_variant",
                }
            )
            continue
        paired_root, paired_entry = paired_record
        _verify_artifacts(paired_root, paired_entry)
        paired_directory = paired_root / paired_entry["phrase_id"]
        paired_metadata_path = paired_directory / "metadata.json"
        paired_loop_path = paired_directory / "loop.mid"
        paired_metadata_hash = _sha256_file(paired_metadata_path)
        paired_loop_hash = _sha256_file(paired_loop_path)

        if phrase_id in prior_entries:
            prior = prior_entries[phrase_id]
            if (
                prior["paired_metadata_sha256"] != paired_metadata_hash
                or prior["paired_loop_midi_sha256"] != paired_loop_hash
            ):
                raise ValueError(f"paired source changed for resumed phrase {phrase_id}")
            entries.append(prior)
            continue

        paired_metadata = _json(paired_metadata_path)
        if paired_metadata.get("base_phrase_id") != phrase_id:
            raise ValueError(f"paired metadata base phrase differs for {phrase_id}")
        try:
            source, source_hash, source_set = resolve_verified_source(
                source_root,
                extra_source_roots,
                paired_metadata.get("source_path"),
                paired_metadata.get("source_sha256"),
            )
        except FileNotFoundError as error:
            raise FileNotFoundError(f"phrase {phrase_id}: {error}") from error
        song = loaded_sources.get(source)
        if song is None:
            song = load_midi(source, recover_invalid_keys=True)
            loaded_sources[source] = song
        start_tick = paired_metadata["cycle_start_tick"]
        period_ticks = paired_metadata["period"]["period_ticks"]
        if paired_metadata.get("version") != VERSION:
            raise ValueError(f"paired phrase {phrase_id} is not a frozen {VERSION} render")
        cycle_seconds = seconds_between(song, start_tick, start_tick + period_ticks)
        if abs(cycle_seconds - paired_metadata["cycle_seconds"]) * SAMPLE_RATE > 0.5:
            raise ValueError(f"phrase {phrase_id} cycle duration differs from source")
        drums = drum_part(song)
        hits = source_cycle_notes(drums, start_tick, period_ticks)
        verify_source_drum_notes(hits, paired_metadata)

        solo_id = f"{phrase_id}-drums-only"
        destination = output / solo_id
        if destination.exists():
            raise FileExistsError(f"unrecorded drum-only output already exists: {destination}")
        destination.mkdir()
        loop_midi = destination / "loop.mid"
        export_phrase(
            song, drums, hits, start_tick, start_tick + period_ticks, loop_midi
        )
        verify_paired_drum_midi(paired_loop_path, loop_midi)
        shutil.copyfile(loop_midi, destination / "source.mid")
        with tempfile.TemporaryDirectory(prefix="samuged-drum-solos-") as temporary:
            repeated_midi = Path(temporary) / "drums_repeated.mid"
            write_repeated_midi(
                song,
                drums,
                hits,
                start_tick,
                period_ticks,
                RENDER_REPETITIONS,
                repeated_midi,
            )
            audio = _render_audio(
                repeated_midi,
                soundfont,
                fluidsynth,
                destination / "loop.wav",
                paired_metadata["cycle_seconds"],
            )
        _optional_audio(
            destination / "loop.wav", make_mp3=False, make_flac=True, ffmpeg=ffmpeg
        )
        note_rows = _note_rows(hits, start_tick)
        metadata = {
            "version": VERSION,
            "phrase_id": solo_id,
            "base_phrase_id": phrase_id,
            "paired_phrase_id": paired_metadata["phrase_id"],
            "kind": "percussion",
            "arrangement": "source_drums_only",
            "source_path": paired_metadata["source_path"],
            "source_sha256": source_hash,
            "source_set": source_set,
            "source_drums_midi_sha256": _sha256_file(destination / "source.mid"),
            "source_export_policy": (
                "source.mid and loop.mid export only the source drum accompaniment from "
                "the paired melody cycle; source onsets, pitches and velocities are "
                "preserved and no drum notes are invented"
            ),
            "recognition_claim": False,
            "recognition_statement": (
                "The drum accompaniment is not claimed to recur independently."
            ),
            "joint_recurrence_verified": False,
            "joint_recurrence_statement": (
                "The drum accompaniment uses the identical source cycle as the paired "
                "melody. Independent drum or joint recurrence is not verified."
            ),
            "cycle_start_tick": start_tick,
            "cycle_end_tick": start_tick + period_ticks,
            "cycle_seconds": paired_metadata["cycle_seconds"],
            "period": paired_metadata["period"],
            "part": {
                "index": drums.index,
                "track": drums.track,
                "channel": 9,
                "program": drums.program,
                "name": drums.name,
                "is_drum": True,
                "percussion_merge": True,
            },
            "source_note_count_used": len(hits),
            "source_notes_used": note_rows,
            "drum_notes_used": note_rows,
            "tempo_changes": paired_metadata["tempo_changes"],
            "meter_changes": paired_metadata["meter_changes"],
            "metadata_repairs": paired_metadata.get("metadata_repairs", []),
            "source_loader_warnings": paired_metadata.get("source_loader_warnings", []),
            "audio": audio,
        }
        _write_json(destination / "metadata.json", metadata)
        artifact_paths = [
            destination / name
            for name in ("source.mid", "loop.mid", "loop.wav", "loop.flac", "metadata.json")
        ]
        artifacts = [_file_record(path, output) for path in artifact_paths]
        _write_json(destination / "hashes.json", {"phrase_id": solo_id, "artifacts": artifacts})
        artifacts.append(_file_record(destination / "hashes.json", output))
        entries.append(
            {
                "phrase_id": solo_id,
                "base_phrase_id": phrase_id,
                "paired_phrase_id": paired_metadata["phrase_id"],
                "selections": selection["selections"],
                "source_path": paired_metadata["source_path"],
                "source_set": source_set,
                "source_sha256": source_hash,
                "paired_manifest": str(paired_root / "manifest.json"),
                "paired_metadata_sha256": paired_metadata_hash,
                "paired_loop_midi_sha256": paired_loop_hash,
                "period_ticks": period_ticks,
                "cycle_seconds": paired_metadata["cycle_seconds"],
                "drum_hit_count": len(hits),
                "drum_onset_count": len({note.start for note in hits}),
                "artifacts": artifacts,
            }
        )
        print(f"Rendered {len(entries)}: {solo_id}", flush=True)

    reason_counts: dict[str, int] = {}
    for row in skipped:
        reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1
    manifest = {
        "version": MANIFEST_VERSION,
        "base_render_version": VERSION,
        "claim": (
            "source drums from the identical paired melody cycle; independent drum or "
            "joint recurrence is not verified"
        ),
        "selection": {
            "referenced_phrase_count": len(selected),
            "paired_melodic_count": len(entries),
            "skipped_count": len(skipped),
            "skip_reason_counts": reason_counts,
        },
        "inputs": {
            "space": str(space.resolve()),
            "source_root": str(source_root.resolve()),
            "extra_source_roots": [str(path.resolve()) for path in extra_source_roots],
            "selections": [
                {"path": str(path), "sha256": _sha256_file(path)}
                for path in selection_paths
            ],
            "combined_manifests": combined_inputs,
            "soundfont": {"path": str(soundfont), "sha256": _sha256_file(soundfont)},
            "generator": {
                "path": str(Path(__file__).resolve()),
                "sha256": _sha256_file(Path(__file__)),
            },
        },
        "render": {
            "sample_rate_hz": SAMPLE_RATE,
            "sample_format": "PCM signed 24-bit little-endian",
            "channels": 2,
            "repetitions": RENDER_REPETITIONS,
            "steady_repetition_index": STEADY_REPETITION,
            "flac": True,
            "mp3": False,
        },
        "renderer_provenance": _renderer_provenance(fluidsynth, ffmpeg),
        "entries": entries,
        "skipped": skipped,
    }
    _write_json(output / "manifest.json", manifest)
    receipt_files = [artifact for entry in entries for artifact in entry["artifacts"]]
    receipt_files.append(_file_record(output / "manifest.json", output))
    _write_json(
        output / "receipt.json",
        {
            "version": MANIFEST_VERSION,
            "file_count": len(receipt_files),
            "files": receipt_files,
            "manifest_sha256": _sha256_file(output / "manifest.json"),
        },
    )
    print(
        f"Rendered {len(entries)} source drum-only variants; skipped {len(skipped)}",
        flush=True,
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--extra-source", type=Path, action="append", default=[])
    parser.add_argument("--selection", type=Path, action="append", required=True)
    parser.add_argument("--combined-root", type=Path, action="append", required=True)
    parser.add_argument("--soundfont", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fluidsynth", type=Path, default=Path("/opt/homebrew/bin/fluidsynth")
    )
    parser.add_argument("--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg"))
    arguments = parser.parse_args()
    render(
        arguments.space,
        arguments.source,
        tuple(arguments.extra_source),
        tuple(arguments.selection),
        tuple(arguments.combined_root),
        arguments.soundfont,
        arguments.output,
        arguments.fluidsynth,
        arguments.ffmpeg,
    )
