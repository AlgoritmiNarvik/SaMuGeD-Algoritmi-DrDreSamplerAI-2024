"""Frozen metamorphic invariance diagnostic on a fixed real MIDI cohort."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import time
from typing import Any, Callable

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.dataset import atomic_json, file_digest
from samuged.drums import DrumConfig, extract_drums
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links
from samuged.midi import MidiSong, Note, Part, load_midi
from samuged.phrases import Config, extract


VERSION = "metamorphic-real-v1"
TRANSFORMS = ("tempo_change", "ppq_x2", "melodic_transpose_plus5")
DETECTOR_NAMES = ("reference_approximate", "aligned_indexed", "drums_tolerant")
TRANSPOSE_SEMITONES = 5
PPQ_FACTOR = 2
REQUIRED_FILES = (
    "scripts/evaluate_metamorphic.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/dataset.py",
    "samuged/drums.py",
    "samuged/experiment.py",
    "samuged/metadata_recovery.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _clone_part(part: Part, notes: list[Note]) -> Part:
    return Part(
        index=part.index,
        track=part.track,
        channel=part.channel,
        program=part.program,
        name=part.name,
        is_drum=part.is_drum,
        notes=notes,
    )


def _changed_tempo(value: int) -> int:
    changed = value * 2 if value <= 0x7FFFFF else value // 2
    return max(1, min(0xFFFFFF, changed))


def tempo_changed(song: MidiSong) -> MidiSong:
    """Change only tempo values while retaining every symbolic tick."""
    return MidiSong(
        ticks_per_beat=song.ticks_per_beat,
        parts=[_clone_part(part, [Note(n.start, n.end, n.pitch, n.velocity) for n in part.notes]) for part in song.parts],
        tempos=[(tick, _changed_tempo(tempo)) for tick, tempo in song.tempos],
        meters=list(song.meters),
        warnings=list(song.warnings),
        metadata_repairs=deepcopy(song.metadata_repairs),
    )


def ppq_doubled(song: MidiSong) -> MidiSong:
    """Double PPQ and every absolute musical tick exactly."""
    return MidiSong(
        ticks_per_beat=song.ticks_per_beat * PPQ_FACTOR,
        parts=[
            _clone_part(
                part,
                [
                    Note(
                        note.start * PPQ_FACTOR,
                        note.end * PPQ_FACTOR,
                        note.pitch,
                        note.velocity,
                    )
                    for note in part.notes
                ],
            )
            for part in song.parts
        ],
        tempos=[(tick * PPQ_FACTOR, tempo) for tick, tempo in song.tempos],
        meters=[
            (tick * PPQ_FACTOR, numerator, denominator)
            for tick, numerator, denominator in song.meters
        ],
        warnings=list(song.warnings),
        metadata_repairs=deepcopy(song.metadata_repairs),
    )


def can_transpose_plus5(song: MidiSong) -> bool:
    return all(
        note.pitch <= 127 - TRANSPOSE_SEMITONES
        for part in song.parts
        if not part.is_drum
        for note in part.notes
    )


def melodic_transposed_plus5(song: MidiSong) -> MidiSong:
    """Transpose non-drum notes by five semitones and retain drum kit IDs."""
    if not can_transpose_plus5(song):
        raise ValueError("melodic transpose would exceed MIDI pitch 127")
    return MidiSong(
        ticks_per_beat=song.ticks_per_beat,
        parts=[
            _clone_part(
                part,
                [
                    Note(
                        note.start,
                        note.end,
                        note.pitch if part.is_drum else note.pitch + TRANSPOSE_SEMITONES,
                        note.velocity,
                    )
                    for note in part.notes
                ],
            )
            for part in song.parts
        ],
        tempos=list(song.tempos),
        meters=list(song.meters),
        warnings=list(song.warnings),
        metadata_repairs=deepcopy(song.metadata_repairs),
    )


def transform_song(song: MidiSong, transform: str) -> MidiSong | None:
    if transform == "tempo_change":
        return tempo_changed(song)
    if transform == "ppq_x2":
        return ppq_doubled(song)
    if transform == "melodic_transpose_plus5":
        return melodic_transposed_plus5(song) if can_transpose_plus5(song) else None
    raise ValueError(f"unknown metamorphic transform: {transform}")


def _scale_tick(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value % PPQ_FACTOR:
        raise ValueError("PPQ-scaled output tick is not exactly divisible by two")
    return value // PPQ_FACTOR


def canonical_phrase(phrase: dict[str, Any], transform: str, detector: str) -> dict[str, Any]:
    """Map a transformed output back to the baseline musical coordinate system."""
    row = deepcopy(phrase)
    row.pop("family_id", None)
    if transform == "ppq_x2":
        for key in ("start_tick", "end_tick"):
            if key in row:
                row[key] = _scale_tick(row[key])
        for occurrence in row.get("occurrences", []):
            for key in ("start_tick", "end_tick"):
                if key in occurrence:
                    occurrence[key] = _scale_tick(occurrence[key])
    elif transform == "melodic_transpose_plus5" and detector != "drums_tolerant":
        row["pitches"] = [pitch - TRANSPOSE_SEMITONES for pitch in row.get("pitches", [])]
    return row


def _difference_paths(left: Any, right: Any, *, limit: int = 200) -> list[str]:
    paths: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if len(paths) >= limit or a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                child = f"{path}.{key}" if path else str(key)
                if key not in a or key not in b:
                    paths.append(child)
                else:
                    walk(a[key], b[key], child)
                if len(paths) >= limit:
                    return
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                paths.append(f"{path}.length")
            for index, (first, second) in enumerate(zip(a, b)):
                walk(first, second, f"{path}[{index}]")
                if len(paths) >= limit:
                    return
            return
        paths.append(path or "$")

    walk(left, right, "")
    return paths


def compare_result(
    baseline: dict[str, Any], variant: dict[str, Any], transform: str, detector: str
) -> dict[str, Any]:
    baseline_phrases = baseline["phrases"]
    variant_phrases = variant["phrases"]
    normalized = [canonical_phrase(row, transform, detector) for row in variant_phrases]
    expected = [canonical_phrase(row, "tempo_change", detector) for row in baseline_phrases]
    baseline_ids = [row.get("family_id") for row in baseline_phrases]
    variant_ids = [row.get("family_id") for row in variant_phrases]
    musical_equal = expected == normalized
    family_order_equal = baseline_ids == variant_ids
    baseline_telemetry = {key: value for key, value in baseline.items() if key not in {"phrases", "config"}}
    variant_telemetry = {key: value for key, value in variant.items() if key not in {"phrases", "config"}}
    return {
        "invariant": musical_equal and family_order_equal,
        "musical_payload_equal": musical_equal,
        "family_id_order_equal": family_order_equal,
        "phrase_count_equal": len(baseline_phrases) == len(variant_phrases),
        "baseline_phrase_count": len(baseline_phrases),
        "variant_phrase_count": len(variant_phrases),
        "baseline_family_ids": baseline_ids,
        "variant_family_ids": variant_ids,
        "difference_paths": _difference_paths(expected, normalized),
        "telemetry_equal": baseline_telemetry == variant_telemetry,
        "telemetry_difference_paths": _difference_paths(baseline_telemetry, variant_telemetry),
    }


def _detectors() -> tuple[dict[str, Callable], dict[str, Any]]:
    configs = {
        "reference_approximate": Config(),
        "aligned_indexed": AlignedConfig(),
        "drums_tolerant": DrumConfig(),
    }
    functions = {
        "reference_approximate": lambda song: extract(song, configs["reference_approximate"]),
        "aligned_indexed": lambda song: extract_indexed(song, configs["aligned_indexed"]),
        "drums_tolerant": lambda song: extract_drums(song, configs["drums_tolerant"]),
    }
    return functions, configs


def _limited(result: dict[str, Any], detector: str) -> bool:
    if detector == "drums_tolerant":
        return bool(result["stats"].get("search_limited"))
    return bool(result.get("search_limited"))


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    for detector in DETECTOR_NAMES:
        groups[detector] = {}
        for transform in TRANSFORMS:
            selected = [
                row for row in rows
                if row["detector"] == detector and row["transform"] == transform
            ]
            eligible = [row for row in selected if not row["skipped"]]
            runtimes = [row["variant_runtime_seconds"] for row in eligible]
            groups[detector][transform] = {
                "sources": len(selected),
                "eligible_sources": len(eligible),
                "skipped_sources": sum(row["skipped"] for row in selected),
                "invariant_sources": sum(row.get("comparison", {}).get("invariant", False) for row in eligible),
                "failed_sources": sum(not row["comparison"]["invariant"] for row in eligible),
                "failure_source_ids": [
                    row["source_id"] for row in eligible if not row["comparison"]["invariant"]
                ],
                "musical_payload_failures": sum(
                    not row["comparison"]["musical_payload_equal"] for row in eligible
                ),
                "family_order_failures": sum(
                    not row["comparison"]["family_id_order_equal"] for row in eligible
                ),
                "telemetry_changes": sum(
                    not row["comparison"]["telemetry_equal"] for row in eligible
                ),
                "baseline_search_limited": sum(row["baseline_search_limited"] for row in eligible),
                "variant_search_limited": sum(row["variant_search_limited"] for row in eligible),
                "runtime_seconds": {
                    "total": round(sum(runtimes), 8),
                    "mean": round(statistics.mean(runtimes), 8) if runtimes else 0.0,
                    "median": round(statistics.median(runtimes), 8) if runtimes else 0.0,
                    "maximum": round(max(runtimes), 8) if runtimes else 0.0,
                },
            }
    return groups


def run(
    source: Path,
    manifest: Path,
    output: Path,
    *,
    expected_sources: int = 128,
    detector_functions: dict[str, Callable] | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    manifest = manifest.resolve()
    manifest_sha256 = file_digest(manifest)
    source_rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").split("\n") if line]
    if len(source_rows) != expected_sources:
        raise ValueError(f"expected {expected_sources} fixed real sources")
    if len({row["source_path"] for row in source_rows}) != len(source_rows):
        raise ValueError("source manifest contains duplicate paths")
    cohort = []
    for row in source_rows:
        path = source / row["source_path"]
        if row.get("status") != "ok" or not path.is_file() or file_digest(path) != row["source_sha256"]:
            raise ValueError(f"fixed source is unavailable or changed: {row['source_path']}")
        cohort.append({
            "source_id": row["source_id"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "metadata_repairs": row.get("metadata_repairs", []),
        })

    default_functions, configs = _detectors()
    functions = detector_functions or default_functions
    if set(functions) != set(DETECTOR_NAMES):
        raise ValueError("detector function set does not match the frozen design")
    design = {
        "version": VERSION,
        "purpose": "real-source metamorphic invariance diagnostic",
        "source_manifest": str(manifest),
        "source_manifest_sha256": manifest_sha256,
        "source_count": len(cohort),
        "cohort_bound": (
            "full fixed 128-source pilot retained because prior paired detector timings "
            "implied a run below the predeclared 90-minute reduction threshold"
        ),
        "detectors": list(DETECTOR_NAMES),
        "transforms": {
            "tempo_change": "change every tempo value only; retain all event ticks and PPQ",
            "ppq_x2": "double PPQ and all note, tempo and meter ticks exactly",
            "melodic_transpose_plus5": (
                "add five to every non-drum pitch; retain drum pitches; skip a source if any "
                "non-drum pitch exceeds 122"
            ),
        },
        "comparison": (
            "selected phrase order and all musical fields after inverse tick or pitch normalization; "
            "family identity order checked separately"
        ),
        "claim_boundary": "symbolic detector invariance only; no perceptual or musical-quality claim",
    }
    frozen_config = {name: asdict(configs[name]) for name in DETECTOR_NAMES}
    receipt = prepare_experiment(
        output,
        design=design,
        config=frozen_config,
        cases=cohort,
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    rows = []
    for source_index, cohort_row in enumerate(cohort):
        path = source / cohort_row["source_path"]
        song = load_midi(path, recover_invalid_keys=bool(cohort_row["metadata_repairs"]))
        if song.metadata_repairs != cohort_row["metadata_repairs"]:
            raise ValueError(f"metadata repair receipt changed: {cohort_row['source_path']}")
        baselines = {}
        baseline_runtime = {}
        for detector in DETECTOR_NAMES:
            started = time.monotonic()
            baselines[detector] = functions[detector](song)
            baseline_runtime[detector] = time.monotonic() - started
        for transform in TRANSFORMS:
            transformed = transform_song(song, transform)
            for detector in DETECTOR_NAMES:
                row = {
                    "source_id": cohort_row["source_id"],
                    "source_path": cohort_row["source_path"],
                    "source_sha256": cohort_row["source_sha256"],
                    "detector": detector,
                    "transform": transform,
                    "baseline_runtime_seconds": round(baseline_runtime[detector], 8),
                    "baseline_search_limited": _limited(baselines[detector], detector),
                    "skipped": transformed is None,
                }
                if transformed is not None:
                    started = time.monotonic()
                    variant = functions[detector](transformed)
                    row["variant_runtime_seconds"] = round(time.monotonic() - started, 8)
                    row["variant_search_limited"] = _limited(variant, detector)
                    row["comparison"] = compare_result(
                        baselines[detector], variant, transform, detector
                    )
                else:
                    row["skip_reason"] = "non-drum pitch above 122 would exceed MIDI pitch 127"
                rows.append(row)
        if (source_index + 1) % 8 == 0:
            print(json.dumps({"sources_processed": source_index + 1, "total": len(cohort)}), flush=True)

    for row in cohort:
        if file_digest(source / row["source_path"]) != row["source_sha256"]:
            raise ValueError(f"fixed source changed during experiment: {row['source_path']}")
    if file_digest(manifest) != manifest_sha256:
        raise ValueError("source manifest changed during experiment")
    raw = {**links, "version": VERSION, "rows": rows}
    aggregate = {
        **links,
        "version": VERSION,
        "source_count": len(cohort),
        "groups": _aggregate(rows),
        "total_failures": sum(
            not row["comparison"]["invariant"] for row in rows if not row["skipped"]
        ),
        "evaluated_rows": sum(not row["skipped"] for row in rows),
        "skipped_rows": sum(row["skipped"] for row in rows),
    }
    atomic_json(output / "raw_results.json", raw)
    atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
