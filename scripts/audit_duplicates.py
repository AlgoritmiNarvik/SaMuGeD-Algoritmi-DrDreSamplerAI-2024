#!/usr/bin/env python3
"""Find bounded symbolic near-duplicate candidates without merging sources.

The reported thresholds are heuristic candidate-screening rules. They are not
labels and they do not establish that two songs or performances are identical.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version as package_version
import inspect
from itertools import combinations
import json
import math
import os
from pathlib import Path
import platform
import shutil
from statistics import median
import sys
from typing import Iterable

from samuged.dataset import canonical_json, digest, discover, file_digest, musical_digest, source_labels
from samuged.midi import load_midi
from samuged.metadata_recovery import recover_invalid_key_signatures
from samuged.phrases import skyline


@dataclass(frozen=True)
class DuplicateConfig:
    recover_invalid_keys: bool = False
    shingle_notes: int = 8
    rhythm_bins: int = 8
    onset_merge_beats: float = 1 / 24
    min_interval_diversity: int = 3
    min_pattern_shared: int = 4
    min_shared: int = 20
    min_jaccard: float = 0.60
    min_containment: float = 0.80
    max_document_frequency: int = 32
    max_document_fraction: float = 0.01
    max_bucket: int = 64
    max_sources: int = 50_000
    max_total_unique_shingles: int = 20_000_000
    max_shingle_attempts_per_source: int = 100_000
    max_unique_shingles_per_source: int = 50_000
    max_generated_pairs: int = 2_000_000
    max_verified_pairs: int = 250_000
    max_reported_candidates: int = 100_000

    def __post_init__(self) -> None:
        if not isinstance(self.recover_invalid_keys, bool):
            raise ValueError("recover_invalid_keys must be boolean")
        for name in (
            "shingle_notes", "rhythm_bins", "min_interval_diversity",
            "min_pattern_shared", "min_shared",
            "max_document_frequency", "max_bucket", "max_sources",
            "max_total_unique_shingles", "max_shingle_attempts_per_source",
            "max_unique_shingles_per_source", "max_generated_pairs", "max_verified_pairs",
            "max_reported_candidates",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.shingle_notes < 4:
            raise ValueError("shingle_notes must be at least 4")
        upper_bounds = {
            "max_generated_pairs": 20_000_000,
            "max_verified_pairs": 2_000_000,
            "max_reported_candidates": 400_000,
        }
        for name, upper_bound in upper_bounds.items():
            if getattr(self, name) > upper_bound:
                raise ValueError(f"{name} must not exceed {upper_bound}")
        for name in ("min_jaccard", "min_containment", "max_document_fraction"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if not math.isfinite(self.onset_merge_beats) or not 0 <= self.onset_merge_beats <= 1:
            raise ValueError("onset_merge_beats must be between zero and one")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical_json(row) + "\n")
    temporary.replace(path)


def _read_manifest(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                rows.append({"source_path": row["source_path"], "split": row.get("split")})
    return rows


def _shingle(pitches: list[int], starts: list[int], *, interval_diversity: int,
             rhythm_bins: int) -> str | None:
    intervals = tuple(right-left for left, right in zip(pitches, pitches[1:]))
    # Monotone scale fragments and one-pattern interval runs are too generic to
    # seed a candidate. Verification still uses all qualified shingles.
    if len(set(intervals)) < interval_diversity or not (
        any(value > 0 for value in intervals) and any(value < 0 for value in intervals)
    ):
        return None
    gaps = [right-left for left, right in zip(starts, starts[1:])]
    positive = [gap for gap in gaps if gap > 0]
    if len(positive) != len(gaps):
        return None
    scale = median(positive)
    if scale <= 0:
        return None
    rhythm = tuple(round(gap/scale*rhythm_bins) for gap in gaps)
    payload = (intervals, rhythm)
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()[:24]


def symbolic_fingerprint(song, cfg: DuplicateConfig) -> tuple[set[str], dict]:
    shingles: set[str] = set()
    attempts = 0
    eligible = 0
    truncated = False
    for part in sorted((part for part in song.parts if not part.is_drum),
                       key=lambda part: (part.index, part.track, part.channel, part.program)):
        notes = skyline(part, song.ticks_per_beat, cfg.onset_merge_beats)
        for index in range(max(0, len(notes)-cfg.shingle_notes+1)):
            if attempts >= cfg.max_shingle_attempts_per_source:
                truncated = True
                break
            attempts += 1
            selected = notes[index:index+cfg.shingle_notes]
            value = _shingle(
                [note.pitch for note in selected],
                [note.start for note in selected],
                interval_diversity=cfg.min_interval_diversity,
                rhythm_bins=cfg.rhythm_bins,
            )
            if value is None:
                continue
            eligible += 1
            shingles.add(value)
            if len(shingles) >= cfg.max_unique_shingles_per_source:
                truncated = True
                break
        if truncated:
            break
    return shingles, {"shingle_attempts": attempts, "eligible_shingle_windows": eligible,
                      "unique_shingles": len(shingles), "shingle_limit_reached": truncated}


def _cache_key(source_hash: str, method_key: str) -> str:
    return digest((source_hash, method_key))


def _fingerprint_task(task: tuple[str, str, str, dict, str]) -> dict:
    path_text, relative, cache_text, cfg_values, method_key = task
    path, cache = Path(path_text), Path(cache_text)
    cfg = DuplicateConfig(**cfg_values)
    source_hash = None
    source_bytes = None
    try:
        source_hash = file_digest(path)
        source_bytes = path.stat().st_size
        cache_path = cache / f"{_cache_key(source_hash, method_key)}.json"
        if cache_path.is_file():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (cached.get("source_sha256") == source_hash
                    and cached.get("method_key") == method_key):
                return {**cached, "source_path": relative, "cache_hit": True}
        song = load_midi(path, recover_invalid_keys=True) if cfg.recover_invalid_keys else load_midi(path)
        shingles, stats = symbolic_fingerprint(song, cfg)
        cached = {
            "status": "ok",
            "source_sha256": source_hash,
            "source_bytes": source_bytes,
            "method_key": method_key,
            "musical_sha256": musical_digest(song),
            "ticks_per_beat": song.ticks_per_beat,
            "part_count": len(song.parts),
            "note_count": sum(len(part.notes) for part in song.parts),
            "metadata_repairs": song.metadata_repairs,
            "shingles": sorted(shingles),
            **stats,
        }
        _atomic_json(cache_path, cached)
        return {**cached, "source_path": relative, "cache_hit": False}
    except Exception as exc:
        return {"status": "error", "source_path": relative,
                "source_sha256": source_hash, "source_bytes": source_bytes,
                "method_key": method_key, "cache_hit": False,
                "error_type": type(exc).__name__, "error": str(exc)}


def _bounded_group_pairs(groups: Iterable[list[int]], limit: int) -> tuple[list[tuple[int, int]], bool]:
    result: list[tuple[int, int]] = []
    for group in sorted((sorted(group) for group in groups), key=lambda values: values[0]):
        for pair in combinations(group, 2):
            if len(result) == limit:
                return result, True
            result.append(pair)
    return result, False


def find_candidates(fingerprints: list[dict], cfg: DuplicateConfig,
                    split_by_path: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    split_by_path = split_by_path or {}
    ok_indices = [index for index, row in enumerate(fingerprints) if row["status"] == "ok"]
    total_shingles = sum(len(fingerprints[index]["shingles"]) for index in ok_indices)
    if total_shingles > cfg.max_total_unique_shingles:
        raise ValueError(
            f"fingerprints contain {total_shingles} shingles, exceeding the "
            f"{cfg.max_total_unique_shingles} global limit"
        )
    document_frequency = Counter(shingle for index in ok_indices
                                 for shingle in fingerprints[index]["shingles"])
    df_limit = min(cfg.max_document_frequency,
                   max(2, int(len(ok_indices)*cfg.max_document_fraction)))
    eligible = {shingle for shingle, count in document_frequency.items()
                if 1 < count <= df_limit}
    ubiquitous = {shingle for shingle, count in document_frequency.items()
                  if count > df_limit}
    qualified_sets = {
        index: set(fingerprints[index]["shingles"])-ubiquitous
        for index in ok_indices
    }
    inverted: dict[str, list[int]] = defaultdict(list)
    for index in ok_indices:
        for shingle in fingerprints[index]["shingles"]:
            if shingle in eligible:
                inverted[shingle].append(index)

    shared: Counter[tuple[int, int]] = Counter()
    generated = 0
    saturated = 0
    generation_limited = False
    for shingle in sorted(inverted):
        bucket = sorted(set(inverted[shingle]))
        if len(bucket) > cfg.max_bucket:
            saturated += 1
            continue
        for pair in combinations(bucket, 2):
            if generated >= cfg.max_generated_pairs:
                generation_limited = True
                break
            generated += 1
            shared[pair] += 1
        if generation_limited:
            break

    hashes: dict[str, list[int]] = defaultdict(list)
    arrangements: dict[str, list[int]] = defaultdict(list)
    for index in ok_indices:
        row = fingerprints[index]
        hashes[row["source_sha256"]].append(index)
        if row.get("note_count", 0):
            arrangements[row["musical_sha256"]].append(index)
    exact_pairs, exact_limited = _bounded_group_pairs(
        (group for group in hashes.values() if len(group) > 1), cfg.max_verified_pairs
    )
    remaining = cfg.max_verified_pairs-len(exact_pairs)
    arrangement_pairs, arrangement_limited = _bounded_group_pairs(
        (group for group in arrangements.values() if len(group) > 1), remaining
    )
    ranked = sorted(shared, key=lambda pair: (-shared[pair], pair))
    verify_pairs = set(exact_pairs)
    verify_pairs.update(arrangement_pairs)
    symbolic_slots = cfg.max_verified_pairs-len(verify_pairs)
    verify_pairs.update(ranked[:symbolic_slots])
    verification_limited = (exact_limited or arrangement_limited
                            or len(ranked) > symbolic_slots)
    candidates = []
    for left_index, right_index in sorted(verify_pairs):
        left, right = fingerprints[left_index], fingerprints[right_index]
        # Candidate generation uses shared rare shingles. Verification must retain
        # source-unique qualified features in its denominator. Otherwise four
        # coincidental shared patterns can misleadingly produce containment 1.0.
        left_set = qualified_sets[left_index]
        right_set = qualified_sets[right_index]
        intersection = len(left_set & right_set)
        union = len(left_set | right_set)
        jaccard = intersection/union if union else 0.0
        containment = intersection/min(len(left_set), len(right_set)) if left_set and right_set else 0.0
        exact_bytes = left["source_sha256"] == right["source_sha256"]
        exact_arrangement = left["musical_sha256"] == right["musical_sha256"]
        symbolic = (intersection >= cfg.min_shared and
                    (jaccard >= cfg.min_jaccard or containment >= cfg.min_containment))
        shared_pattern = intersection >= cfg.min_pattern_shared and not symbolic
        if not (exact_bytes or exact_arrangement or symbolic or shared_pattern):
            continue
        left_labels, right_labels = source_labels(left["source_path"]), source_labels(right["source_path"])
        left_split, right_split = split_by_path.get(left["source_path"]), split_by_path.get(right["source_path"])
        candidates.append({
            "left_source_path": left["source_path"],
            "right_source_path": right["source_path"],
            "left_source_sha256": left["source_sha256"],
            "right_source_sha256": right["source_sha256"],
            "left_musical_sha256": left["musical_sha256"],
            "right_musical_sha256": right["musical_sha256"],
            "exact_bytes": exact_bytes,
            "exact_arrangement": exact_arrangement,
            "symbolic_near_duplicate": symbolic,
            "shared_pattern_candidate": shared_pattern,
            "shared_rare_shingles": intersection,
            "left_rare_shingles": len(left_set),
            "right_rare_shingles": len(right_set),
            "jaccard": round(jaccard, 8),
            "containment": round(containment, 8),
            "left_artist_key": left_labels["artist_key"],
            "right_artist_key": right_labels["artist_key"],
            "same_artist_key": left_labels["artist_key"] == right_labels["artist_key"],
            "left_title_from_path": left_labels["title_from_path"],
            "right_title_from_path": right_labels["title_from_path"],
            "left_song_key": left_labels["song_key"],
            "right_song_key": right_labels["song_key"],
            "same_song_key": left_labels["song_key"] == right_labels["song_key"],
            "left_split": left_split,
            "right_split": right_split,
            "cross_split": bool(left_split and right_split and left_split != right_split),
        })
    candidates.sort(key=lambda row: (not row["exact_bytes"], not row["exact_arrangement"],
                    not row["symbolic_near_duplicate"], not row["shared_pattern_candidate"],
                    -row["containment"], -row["jaccard"],
                    row["left_source_path"], row["right_source_path"]))
    reported_limited = len(candidates) > cfg.max_reported_candidates
    candidates = candidates[:cfg.max_reported_candidates]
    stats = {
        "documents": len(ok_indices),
        "source_unique_shingle_total": total_shingles,
        "unique_shingles": len(document_frequency),
        "eligible_rare_shingles": len(eligible),
        "ubiquitous_shingles_excluded": len(ubiquitous),
        "document_frequency_limit": df_limit,
        "saturated_inverted_buckets": saturated,
        "pair_events_generated": generated,
        "pairs_with_shared_shingles": len(shared),
        "pairs_verified": len(verify_pairs),
        "pair_generation_limit_reached": generation_limited,
        "pair_verification_limit_reached": verification_limited,
        "candidate_report_limit_reached": reported_limited,
    }
    return candidates, stats


def _snapshot_files(provenance: Path) -> dict:
    repository = Path(__file__).resolve().parents[1]
    sources = {
        "scripts/audit_duplicates.py": Path(__file__).resolve(),
        "samuged/dataset.py": Path(inspect.getsourcefile(file_digest)).resolve(),
        "samuged/midi.py": Path(inspect.getsourcefile(load_midi)).resolve(),
        "samuged/phrases.py": Path(inspect.getsourcefile(skyline)).resolve(),
        "samuged/metadata_recovery.py": Path(inspect.getsourcefile(recover_invalid_key_signatures)).resolve(),
        "samuged/__init__.py": Path(inspect.getsourcefile(load_midi)).resolve().with_name("__init__.py"),
    }
    dependency_files = {}
    for name in ("pyproject.toml", "requirements-research.lock"):
        path = repository/name
        if path.is_file():
            dependency_files[name] = path
    copied = {}
    for relative, source in {**sources, **dependency_files}.items():
        destination = provenance/"snapshot"/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied[relative] = file_digest(destination)
    return {
        "files": copied,
        "code_sha256": digest({key: copied[key] for key in sources}),
        "dependency_files_sha256": {key: copied[key] for key in dependency_files},
        "runtime": {"python": platform.python_version(), "mido": package_version("mido")},
    }


def _progress(stage: str, **values: object) -> None:
    print(canonical_json({"stage": stage, **values}), file=sys.stderr, flush=True)


def _provenance_directory(output: Path) -> Path:
    return output.with_name(f"{output.stem}_provenance")


def _relative_to_output(path: Path, output: Path) -> str:
    try:
        return path.relative_to(output.parent).as_posix()
    except ValueError:
        return str(path)


def audit_duplicates(source: Path, output: Path, *, manifest: Path | None = None,
                     cache: Path | None = None, workers: int = 1,
                     limit: int | None = None,
                     cfg: DuplicateConfig | None = None) -> dict:
    if workers not in {1, 2}:
        raise ValueError("workers must be 1 or 2")
    cfg = cfg or DuplicateConfig()
    output = output.resolve()
    provenance = _provenance_directory(output)
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if provenance.exists():
        raise ValueError(f"provenance directory already exists: {provenance}")
    source = source.resolve(strict=True)
    cache = (cache or output.parent/"duplicates_cache").resolve()
    manifest_path = manifest.resolve(strict=True) if manifest else None
    manifest_sha256 = file_digest(manifest_path) if manifest_path else None
    split_by_path: dict[str, str] = {}
    manifest_rows = _read_manifest(manifest_path) if manifest_path else []
    if manifest_path and file_digest(manifest_path) != manifest_sha256:
        raise ValueError("input manifest changed while it was being read")
    if manifest_path is not None:
        relative_paths = sorted({row["source_path"] for row in manifest_rows})
        split_by_path = {row["source_path"]: row.get("split") for row in manifest_rows}
        paths = []
        for relative in relative_paths:
            candidate = (source/relative).resolve()
            if not candidate.is_relative_to(source):
                raise ValueError(f"manifest source path escapes source root: {relative}")
            paths.append(candidate)
    else:
        paths = discover(source)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        paths = sorted(paths, key=lambda path: sha256(path.relative_to(source).as_posix().encode()).hexdigest())[:limit]
    if len(paths) > cfg.max_sources:
        raise ValueError(
            f"source contains {len(paths)} files, exceeding the {cfg.max_sources} limit"
        )
    script_path = Path(__file__).resolve()
    midi_path = Path(inspect.getsourcefile(load_midi)).resolve()
    phrases_path = Path(inspect.getsourcefile(skyline)).resolve()
    script_hash = file_digest(script_path)
    fingerprint_config = {
        key: value for key, value in asdict(cfg).items()
        if key in {"shingle_notes", "rhythm_bins", "onset_merge_beats",
                   "min_interval_diversity", "max_shingle_attempts_per_source",
                   "max_unique_shingles_per_source", "recover_invalid_keys"}
    }
    fingerprint_components = {
        "local": sha256(
            (inspect.getsource(_shingle) + inspect.getsource(symbolic_fingerprint)).encode()
        ).hexdigest(),
        "midi_module": file_digest(midi_path),
        "phrases_module": file_digest(phrases_path),
        "metadata_recovery_module": file_digest(Path(inspect.getsourcefile(recover_invalid_key_signatures))),
        "arrangement_digest": sha256(inspect.getsource(musical_digest).encode()).hexdigest(),
        "mido_version": package_version("mido"),
    }
    fingerprint_code = digest(fingerprint_components)
    method_key = digest({"fingerprint_code_sha256": fingerprint_code,
                         "config": fingerprint_config})

    provenance.mkdir(parents=True)
    snapshot = _snapshot_files(provenance)
    if (snapshot["files"]["scripts/audit_duplicates.py"] != script_hash
            or snapshot["files"]["samuged/midi.py"] != fingerprint_components["midi_module"]
            or snapshot["files"]["samuged/phrases.py"] != fingerprint_components["phrases_module"]
            or snapshot["files"]["samuged/metadata_recovery.py"] != fingerprint_components["metadata_recovery_module"]):
        raise RuntimeError("code changed while creating the run snapshot")
    selected_sources_path = provenance/"input_sources.jsonl"
    _atomic_jsonl(selected_sources_path, (
        {"source_path": path.relative_to(source).as_posix(),
         "split": split_by_path.get(path.relative_to(source).as_posix())}
        for path in paths
    ))
    selected_sources_sha256 = file_digest(selected_sources_path)
    design = {
        "schema_version": 1,
        "source_root": str(source),
        "input_manifest": str(manifest_path) if manifest_path else None,
        "input_manifest_sha256": manifest_sha256,
        "selected_sources": _relative_to_output(selected_sources_path, output),
        "selected_sources_sha256": selected_sources_sha256,
        "selected_source_count": len(paths),
        "cache": str(cache),
        "workers": workers,
        "limit": limit,
        "config": asdict(cfg),
        "fingerprint_config": fingerprint_config,
        "fingerprint_components_sha256": fingerprint_components,
        "fingerprint_code_sha256": fingerprint_code,
        "method_key": method_key,
        "script_sha256": script_hash,
        "snapshot": snapshot,
    }
    design_path = provenance/"design.json"
    _atomic_json(design_path, design)
    design_sha256 = file_digest(design_path)

    tasks = [(str(path), path.relative_to(source).as_posix(), str(cache),
              asdict(cfg), method_key) for path in paths]
    _progress("fingerprinting", completed=0, total=len(tasks))
    if workers == 1:
        iterator = map(_fingerprint_task, tasks)
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        iterator = pool.map(_fingerprint_task, tasks, chunksize=8)
    fingerprints = []
    try:
        for index, row in enumerate(iterator, 1):
            fingerprints.append(row)
            if index % 500 == 0 or index == len(tasks):
                _progress("fingerprinting", completed=index, total=len(tasks))
    finally:
        if workers != 1:
            pool.shutdown()
    fingerprints.sort(key=lambda row: row["source_path"])

    receipt_path = provenance/"fingerprint_receipt.jsonl"
    _atomic_jsonl(receipt_path, ({
        "source_path": row["source_path"],
        "status": row["status"],
        "source_sha256": row.get("source_sha256"),
        "source_bytes": row.get("source_bytes"),
        "method_key": row.get("method_key"),
        "cache_hit": bool(row.get("cache_hit")),
        "metadata_repairs": row.get("metadata_repairs", []),
    } for row in fingerprints))
    receipt_sha256 = file_digest(receipt_path)

    _progress("candidate_generation", status="started", documents=len(fingerprints))
    candidates, generation = find_candidates(fingerprints, cfg, split_by_path)
    _progress("candidate_generation", status="completed", candidates=len(candidates),
              pairs_verified=generation["pairs_verified"])
    cache_method_keys = Counter(row["method_key"] for row in fingerprints
                                if row["status"] == "ok" and row.get("method_key"))
    cache_hit_method_keys = Counter(row["method_key"] for row in fingerprints
                                    if row.get("cache_hit") and row.get("method_key"))
    fingerprint_method_keys = Counter(row["method_key"] for row in fingerprints
                                      if row.get("source_sha256") and row.get("method_key"))
    result = {
        "schema_version": 2,
        "method": "transposition-invariant interval and median-normalized rhythm shingles",
        "interpretation": "heuristic duplicate candidates for review, not known ground truth and not automatic merges",
        "source_root": str(source),
        "manifest": str(manifest_path) if manifest_path else None,
        "manifest_sha256": manifest_sha256,
        "provenance_directory": _relative_to_output(provenance, output),
        "design": _relative_to_output(design_path, output),
        "design_sha256": design_sha256,
        "selected_sources_sha256": selected_sources_sha256,
        "fingerprint_receipt": _relative_to_output(receipt_path, output),
        "fingerprint_receipt_sha256": receipt_sha256,
        "script_sha256": script_hash,
        "fingerprint_code_sha256": fingerprint_code,
        "method_key": method_key,
        "fingerprint_method_key_counts": dict(fingerprint_method_keys),
        "cache_method_key_counts": dict(cache_method_keys),
        "cache_hit_method_key_counts": dict(cache_hit_method_keys),
        "config": asdict(cfg),
        "input_files": len(paths),
        "status_counts": dict(Counter(row["status"] for row in fingerprints)),
        "cache_hits": sum(bool(row.get("cache_hit")) for row in fingerprints),
        "metadata_recovered_files": sum(bool(row.get("metadata_repairs")) for row in fingerprints),
        "metadata_recovered_events": sum(len(row.get("metadata_repairs", [])) for row in fingerprints),
        "shingle_limited_files": sum(bool(row.get("shingle_limit_reached")) for row in fingerprints),
        "generation": generation,
        "candidate_counts": {
            "reported": len(candidates),
            "exact_bytes": sum(row["exact_bytes"] for row in candidates),
            "exact_arrangement": sum(row["exact_arrangement"] for row in candidates),
            "symbolic_near_duplicate": sum(row["symbolic_near_duplicate"] for row in candidates),
            "shared_pattern_candidate": sum(row["shared_pattern_candidate"] for row in candidates),
            "cross_split": sum(row["cross_split"] for row in candidates),
            "near_duplicate_cross_split": sum(row["cross_split"] and row["symbolic_near_duplicate"] for row in candidates),
            "shared_pattern_cross_split": sum(row["cross_split"] and row["shared_pattern_candidate"] for row in candidates),
        },
        "candidates": candidates,
        "errors": [{key: row[key] for key in ("source_path", "error_type", "error")}
                   for row in fingerprints if row["status"] == "error"],
    }
    _atomic_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--recover-invalid-keys", action="store_true",
                        help="preserve invalid key metadata as ignored events with exact repair receipts")
    parser.add_argument("--max-generated-pairs", type=int,
                        default=DuplicateConfig.max_generated_pairs,
                        help="candidate pair event cap, at most 20000000")
    parser.add_argument("--max-verified-pairs", type=int,
                        default=DuplicateConfig.max_verified_pairs,
                        help="verification cap, at most 2000000")
    parser.add_argument("--max-reported-candidates", type=int,
                        default=DuplicateConfig.max_reported_candidates,
                        help="reported candidate cap, at most 400000")
    args = parser.parse_args()
    try:
        cfg = DuplicateConfig(
            recover_invalid_keys=args.recover_invalid_keys,
            max_generated_pairs=args.max_generated_pairs,
            max_verified_pairs=args.max_verified_pairs,
            max_reported_candidates=args.max_reported_candidates,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = audit_duplicates(args.source, args.output, manifest=args.manifest,
                              cache=args.cache, workers=args.workers, limit=args.limit,
                              cfg=cfg)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"candidates", "errors"}}, indent=2))


if __name__ == "__main__":
    main()
