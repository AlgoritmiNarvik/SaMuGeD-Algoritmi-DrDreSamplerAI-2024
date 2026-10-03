"""Render source drum accompaniment for every referenced melodic source cycle."""
from __future__ import annotations

import argparse
from copy import deepcopy
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
from samuged.midi import export_phrase, load_midi


MIN_DRUM_HITS = 4
MIN_DRUM_ONSETS = 2
MANIFEST_VERSION = "samuged-source-layers-v1"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def referenced_phrases(
    space: Path, supplemental_selections: tuple[Path, ...] = ()
) -> dict[str, list[str]]:
    """Return the catalog and atlas scopes for each referenced base phrase."""

    references: dict[str, set[str]] = {}
    catalog = _json(space / "catalog.json")
    for group_name, group in catalog["groups"].items():
        for row in group["rows"]:
            references.setdefault(row["phrase_id"], set()).add(f"catalog:{group_name}")
    atlas_path = space / "atlas" / "analysis.json"
    if atlas_path.exists():
        for phrase_id in _json(atlas_path)["snippets"]:
            references.setdefault(phrase_id, set()).add("atlas")
    for selection_path in supplemental_selections:
        selection = _json(selection_path)
        candidates = selection.get("candidates") if isinstance(selection, dict) else None
        if not isinstance(candidates, list):
            raise ValueError(f"supplemental selection has no candidates: {selection_path}")
        for candidate in candidates:
            phrase_id = candidate.get("phrase_id") if isinstance(candidate, dict) else None
            if not isinstance(phrase_id, str) or not phrase_id:
                raise ValueError(
                    f"supplemental selection has an invalid phrase ID: {selection_path}"
                )
            references.setdefault(phrase_id, set()).add(
                f"supplemental_selection:{selection_path.name}"
            )
    return {phrase_id: sorted(scopes) for phrase_id, scopes in sorted(references.items())}


def resolve_source(source_root: Path, relative: object) -> Path | None:
    """Resolve a source inside its root, returning ``None`` when it is absent."""

    if not isinstance(relative, str) or not relative:
        raise ValueError("source_path must be a nonempty string")
    resolved_root = source_root.resolve(strict=True)
    candidate = resolved_root / relative
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError(f"source_path escapes or is not a file: {relative!r}")
    return resolved


def verify_source(path: Path, expected_sha256: object) -> str:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"source hash changed: {path}")
    return actual


def resolve_verified_source(
    source_root: Path,
    extra_source_roots: tuple[Path, ...],
    relative: object,
    expected_sha256: object,
) -> tuple[Path, str, str]:
    """Find and hash-check a source, using the extra root only as a fallback."""

    roots = (("primary", source_root),) + tuple(
        (f"extra:{index}", root) for index, root in enumerate(extra_source_roots, 1)
    )
    for source_set, root in roots:
        source = resolve_source(root, relative)
        if source is not None:
            return source, verify_source(source, expected_sha256), source_set
    raise FileNotFoundError(f"source MIDI is absent from all configured roots: {relative!r}")


def _track_end(track: mido.MidiTrack) -> int:
    return sum(message.time for message in track)


def combine_aligned_tracks(melody_path: Path, drums_path: Path, target: Path) -> None:
    """Append an exact source drum track to an aligned melodic cycle."""

    melody = mido.MidiFile(melody_path, clip=False)
    percussion = mido.MidiFile(drums_path, clip=False)
    if melody.ticks_per_beat != percussion.ticks_per_beat:
        raise ValueError("layer tick resolutions differ")
    if len(melody.tracks) != 2 or len(percussion.tracks) != 2:
        raise ValueError("layers must contain metadata and one note track")
    if melody.tracks[0] != percussion.tracks[0]:
        raise ValueError("layer tempo and meter tracks differ")
    cycle_ticks = _track_end(melody.tracks[0])
    if any(_track_end(track) != cycle_ticks for track in (*melody.tracks, *percussion.tracks)):
        raise ValueError("layer cycle lengths differ")
    if any(
        not message.is_meta and getattr(message, "channel", None) == 9
        for message in melody.tracks[1]
    ):
        raise ValueError("melodic layer uses the percussion channel")
    if any(
        not message.is_meta and getattr(message, "channel", None) != 9
        for message in percussion.tracks[1]
    ):
        raise ValueError("drum layer is not on the percussion channel")
    melody.tracks.append(percussion.tracks[1])
    melody.save(target)


def _skip(
    skipped: list[dict[str, Any]], phrase_id: str, scopes: list[str], reason: str,
    metadata: dict[str, Any] | None = None, **details: Any,
) -> None:
    row: dict[str, Any] = {"phrase_id": phrase_id, "references": scopes, "reason": reason}
    if metadata is not None:
        row["kind"] = metadata.get("kind")
        row["source_path"] = metadata.get("source_path")
    row.update(details)
    skipped.append(row)


def _validate_part(song: Any, metadata: dict[str, Any]) -> Any:
    part_metadata = metadata["part"]
    matches = [part for part in song.parts if part.index == part_metadata["index"]]
    if len(matches) != 1 or matches[0].is_drum:
        raise ValueError(f"phrase {metadata['phrase_id']} references an unavailable melodic part")
    part = matches[0]
    for field in ("track", "channel", "program"):
        if part_metadata[field] != getattr(part, field):
            raise ValueError(f"phrase {metadata['phrase_id']} source part {field} changed")
    return part


def render(
    space: Path,
    source_root: Path,
    extra_source_roots: tuple[Path, ...],
    supplemental_selections: tuple[Path, ...],
    soundfont: Path,
    output: Path,
    fluidsynth: Path,
    ffmpeg: Path,
) -> dict[str, Any]:
    """Render qualifying source drum layers and record every excluded reference."""

    prior_entries: dict[str, dict[str, Any]] = {}
    if output.exists():
        manifest_path = output / "manifest.json"
        if not manifest_path.exists():
            raise FileExistsError(f"output exists without a resumable manifest: {output}")
        prior_manifest = _json(manifest_path)
        if prior_manifest.get("version") != MANIFEST_VERSION:
            raise ValueError("existing output uses a different manifest version")
        prior_entries = {entry["base_phrase_id"]: entry for entry in prior_manifest["entries"]}
        if len(prior_entries) != len(prior_manifest["entries"]):
            raise ValueError("existing manifest has duplicate base phrase entries")
        for entry in prior_entries.values():
            for artifact in entry["artifacts"]:
                path = output / artifact["path"]
                if (
                    not path.resolve().is_relative_to(output.resolve())
                    or not path.is_file()
                    or _sha256_file(path) != artifact["sha256"]
                ):
                    raise ValueError(
                        f"existing output artifact does not match its receipt: {path}"
                    )
    else:
        output.mkdir(parents=True)
    audio_root = space / "audio"
    references = referenced_phrases(space, supplemental_selections)
    existing_pairs = {
        path.name.removesuffix("-with-drums") for path in audio_root.glob("*-with-drums")
    }
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    loaded_sources: dict[Path, Any] = {}

    for phrase_id, scopes in references.items():
        base = audio_root / phrase_id
        metadata_path = base / "metadata.json"
        if not metadata_path.exists():
            _skip(skipped, phrase_id, scopes, "base_metadata_missing")
            continue
        metadata = _json(metadata_path)
        if metadata.get("phrase_id") != phrase_id:
            raise ValueError(f"base metadata phrase ID differs for {phrase_id}")
        if metadata.get("kind") != "melodic":
            _skip(skipped, phrase_id, scopes, "percussion", metadata)
            continue
        if phrase_id in prior_entries:
            entries.append(prior_entries[phrase_id])
            continue
        if phrase_id in existing_pairs:
            _skip(skipped, phrase_id, scopes, "existing_source_drum_variant", metadata)
            continue
        try:
            source, source_hash, source_set = resolve_verified_source(
                source_root,
                extra_source_roots,
                metadata.get("source_path"),
                metadata.get("source_sha256"),
            )
        except FileNotFoundError as error:
            raise FileNotFoundError(f"phrase {phrase_id}: {error}") from error
        song = loaded_sources.get(source)
        if song is None:
            song = load_midi(source, recover_invalid_keys=True)
            loaded_sources[source] = song
        part = _validate_part(song, metadata)
        start_tick = metadata["cycle_start_tick"]
        period_ticks = metadata["period"]["period_ticks"]
        if metadata.get("version") != VERSION:
            raise ValueError(f"phrase {phrase_id} is not a frozen {VERSION} render")
        cycle_seconds = seconds_between(song, start_tick, start_tick + period_ticks)
        if abs(cycle_seconds - metadata["cycle_seconds"]) * SAMPLE_RATE > 0.5:
            raise ValueError(f"phrase {phrase_id} cycle duration differs from source")

        drums = drum_part(song)
        hits = source_cycle_notes(drums, start_tick, period_ticks)
        onset_count = len({note.start for note in hits})
        if len(hits) < MIN_DRUM_HITS or onset_count < MIN_DRUM_ONSETS:
            _skip(
                skipped, phrase_id, scopes, "insufficient_source_drums", metadata,
                drum_hit_count=len(hits), drum_onset_count=onset_count,
            )
            continue

        notes = source_cycle_notes(part, start_tick, period_ticks)
        destination = output / f"{phrase_id}-with-drums"
        destination.mkdir()
        with tempfile.TemporaryDirectory(prefix="samuged-source-layers-") as temporary:
            temporary_root = Path(temporary)
            drums_one = temporary_root / "drums_one.mid"
            export_phrase(
                song, drums, hits, start_tick, start_tick + period_ticks, drums_one
            )
            combine_aligned_tracks(base / "loop.mid", drums_one, destination / "loop.mid")
            riff_repeated = temporary_root / "riff_repeated.mid"
            drums_repeated = temporary_root / "drums_repeated.mid"
            combined_repeated = temporary_root / "combined_repeated.mid"
            write_repeated_midi(
                song, part, notes, start_tick, period_ticks, RENDER_REPETITIONS,
                riff_repeated,
            )
            write_repeated_midi(
                song, drums, hits, start_tick, period_ticks, RENDER_REPETITIONS,
                drums_repeated,
            )
            combine_aligned_tracks(riff_repeated, drums_repeated, combined_repeated)
            audio = _render_audio(
                combined_repeated, soundfont, fluidsynth, destination / "loop.wav",
                metadata["cycle_seconds"],
            )
        _optional_audio(
            destination / "loop.wav", make_mp3=False, make_flac=True, ffmpeg=ffmpeg
        )
        shutil.copyfile(base / "source.mid", destination / "source.mid")

        mixed_id = f"{phrase_id}-with-drums"
        mixed = deepcopy(metadata)
        mixed.update(
            phrase_id=mixed_id,
            base_phrase_id=phrase_id,
            arrangement="melody_with_source_drums",
            audio=audio,
            drum_threshold={
                "minimum_hits": MIN_DRUM_HITS,
                "minimum_distinct_onsets": MIN_DRUM_ONSETS,
            },
            joint_recurrence_verified=False,
            joint_recurrence_statement=(
                "The melody and drums use the identical source cycle. Their joint "
                "recurrence is not independently verified."
            ),
        )
        mixed["source_export_policy"] += (
            "; the combined loop adds source drum onsets, pitches and velocities from "
            "the identical time window and does not invent drum notes"
        )
        mixed["drum_notes_used"] = [
            {
                "start_tick": note.start,
                "end_tick": note.end,
                "relative_start_tick": note.start - start_tick,
                "relative_end_tick": note.end - start_tick,
                "pitch": note.pitch,
                "velocity": note.velocity,
                "channel": 9,
            }
            for note in hits
        ]
        _write_json(destination / "metadata.json", mixed)
        artifact_paths = [
            destination / name
            for name in ("source.mid", "loop.mid", "loop.wav", "loop.flac", "metadata.json")
        ]
        artifacts = [_file_record(path, output) for path in artifact_paths]
        _write_json(destination / "hashes.json", {"phrase_id": mixed_id, "artifacts": artifacts})
        artifacts.append(_file_record(destination / "hashes.json", output))
        entries.append(
            {
                "phrase_id": mixed_id,
                "base_phrase_id": phrase_id,
                "references": scopes,
                "kind": "melodic",
                "source_path": metadata["source_path"],
                "source_set": source_set,
                "source_sha256": source_hash,
                "base_metadata_sha256": _sha256_file(metadata_path),
                "base_loop_midi_sha256": _sha256_file(base / "loop.mid"),
                "period_ticks": period_ticks,
                "cycle_seconds": metadata["cycle_seconds"],
                "drum_hit_count": len(hits),
                "drum_onset_count": onset_count,
                "artifacts": artifacts,
            }
        )
        print(f"Rendered {len(entries)}: {mixed_id}", flush=True)

    reason_counts: dict[str, int] = {}
    for row in skipped:
        reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1
    manifest = {
        "version": MANIFEST_VERSION,
        "base_render_version": VERSION,
        "claim": (
            "same source cycle with aligned source drums; independent joint recurrence "
            "is not verified"
        ),
        "selection": {
            "referenced_phrase_count": len(references),
            "rendered_count": len(entries),
            "skipped_count": len(skipped),
            "skip_reason_counts": reason_counts,
            "minimum_drum_hits": MIN_DRUM_HITS,
            "minimum_distinct_drum_onsets": MIN_DRUM_ONSETS,
        },
        "inputs": {
            "space_catalog": {
                "path": str(space / "catalog.json"),
                "sha256": _sha256_file(space / "catalog.json"),
            },
            "atlas_analysis": {
                "path": str(space / "atlas" / "analysis.json"),
                "sha256": _sha256_file(space / "atlas" / "analysis.json"),
            },
            "source_root": str(source_root.resolve()),
            "extra_source_roots": [
                str(path.resolve()) for path in extra_source_roots
            ],
            "supplemental_selections": [
                {"path": str(path), "sha256": _sha256_file(path)}
                for path in supplemental_selections
            ],
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
        f"Rendered {len(entries)} aligned source drum variants; skipped {len(skipped)}",
        flush=True,
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--extra-source", type=Path, action="append", default=[])
    parser.add_argument("--selection", type=Path, action="append", default=[])
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
        arguments.soundfont,
        arguments.output,
        arguments.fluidsynth,
        arguments.ffmpeg,
    )
