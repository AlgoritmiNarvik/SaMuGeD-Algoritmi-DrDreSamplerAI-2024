"""Audit saved manifests and MIDI artifacts against source files and provenance."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from fractions import Fraction
import json
from pathlib import Path, PurePosixPath

import mido

from .aligned import AlignedConfig, extract_aligned
from .aligned_indexed import extract_indexed
from .closed_patterns import extract_closed_patterns
from .audit_closed import verify_closed_trace
from .audit_part_ranking import verify_part_ranking
from .audit_alignment import (
    EXPECTED_MATCHER_FLAGS,
    validate_aligned_config,
    verify_alignment,
)
from .dataset import (atomic_json, canonical_json, digest, discover, file_digest,
                      musical_digest, runtime_metadata, source_labels)
from .drums import drum_part, extract_drums
from .midi import Note, load_midi
from .phrases import Config, extract, signature, skyline, window
from .part_ranking import ALGORITHM_NAME, PART_PRIOR_VERSION, extract_part_ranked


_SOURCE_COLUMNS = ("source_id", "source_sha256", "source_path",
                   "artist_from_path", "title_from_path", "song_key", "split",
                   "split_group", "ticks_per_beat")
_ALIGNED_ALGORITHMS = frozenset({"aligned", "aligned_indexed", "aligned_closed", "aligned_melody"})


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class _Union:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, left: str, right: str) -> None:
        left_root, right_root = sorted((self.find(left), self.find(right)))
        self.parent[right_root] = left_root


def _expected_source_splits(records: list[dict]) -> dict[str, tuple[str, str]]:
    """Reproduce finalize's grouping without mutating dataset state."""
    union = _Union([row["source_id"] for row in records])
    links: dict[tuple[str, str], str] = {}
    for row in records:
        keys = [("artist", row["artist_key"]), ("song", row["song_key"])]
        if row.get("source_sha256"):
            keys.append(("sha", row["source_sha256"]))
        if row.get("note_count", 0):
            keys.append(("musical", row["musical_sha256"]))
        for key in keys:
            if key in links:
                union.join(row["source_id"], links[key])
            else:
                links[key] = row["source_id"]
    result = {}
    for row in records:
        group = union.find(row["source_id"])
        bucket = int(sha256(("samuged-split-v1:" + group).encode()).hexdigest()[:8], 16) % 100
        split = "train" if bucket < 80 else "validation" if bucket < 90 else "test"
        result[row["source_id"]] = (group, split)
    return result


def _expected_rows(records: list[dict], splits: dict[str, tuple[str, str]]) -> list[dict]:
    families: dict[tuple[str, str], set[str]] = defaultdict(set)
    rows = []
    for source in records:
        group, split = splits[source["source_id"]]
        finalized = {**source, "split_group": group, "split": split}
        for phrase in source.get("phrases", []):
            row = {key: finalized[key] for key in _SOURCE_COLUMNS}
            row.update(phrase)
            rows.append(row)
            families[(phrase["kind"], phrase["family_id"])].add(split)
    for row in rows:
        preferred = next(split for split in ("train", "validation", "test")
                         if split in families[(row["kind"], row["family_id"])])
        if row["split"] != preferred:
            row["source_split"] = row["split"]
            row["split"] = "overlap_excluded"
    return rows


def _contained(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        return None
    candidate = root.joinpath(*pure.parts).resolve()
    return candidate if candidate.is_relative_to(root.resolve()) else None


def _code_digest(root: Path) -> str:
    return digest({path.name: sha256(path.read_bytes()).hexdigest()
                   for path in sorted(root.glob("*.py"))})


def _cropped_changes(changes: list[tuple], start: int, end: int) -> list[tuple]:
    active = max((change for change in changes if change[0] <= start), key=lambda x: x[0])
    return [(0, *active[1:])] + [(change[0]-start, *change[1:])
                                for change in changes if start < change[0] < end]


def _matched_strikes(left: list[float], right: list[float], tolerance: float) -> int:
    """Maximum cardinality order-preserving match for sorted strike times.

    Nearest-neighbour removal can steal the only feasible match of a later
    strike. Pair the earliest mutually feasible strikes instead.
    """
    i = j = matched = 0
    while i < len(left) and j < len(right):
        if abs(left[i]-right[j]) <= tolerance:
            matched += 1
            i += 1
            j += 1
        elif left[i] < right[j]:
            i += 1
        else:
            j += 1
    return matched


def _drum_window_meter(song, start: int, end: int, bars: int) -> tuple[int, int] | None:
    """Verify a rounded bar interval without calling the detector's window maker."""
    active = max(i for i, item in enumerate(song.meters) if item[0] <= start)
    origin, numerator, denominator = song.meters[active]
    bar = Fraction(song.ticks_per_beat*numerator*4, denominator)
    half = Fraction(1, 2)
    # A source tick t represents [t-.5,t+.5) under half-up rounding.
    lower = max(Fraction(0), (start-origin-half)/bar, (end-origin-half)/bar-bars)
    upper = min((start-origin+half)/bar, (end-origin+half)/bar-bars)
    offset = -(-lower.numerator // lower.denominator)
    if offset >= upper:
        return None
    if active+1 < len(song.meters) and origin+bar*(offset+bars) > song.meters[active+1][0]:
        return None
    return numerator, denominator


def _expected_summary(
    config: dict, records: list[dict], rows: list[dict], saved_summary: dict
) -> dict:
    values = {
        "source_files": len(records),
        "source_status": dict(Counter(row["status"] for row in records)),
        "source_outcomes": dict(Counter(row.get("outcome", row["status"]) for row in records)),
        "source_files_with_melodic_phrases": sum(any(p["kind"] == "melodic" for p in row.get("phrases", [])) for row in records),
        "source_files_with_percussion_phrases": sum(any(p["kind"] == "percussion" for p in row.get("phrases", [])) for row in records),
        "phrase_counts": dict(Counter(row["kind"] for row in rows)),
        "split_counts": dict(Counter(row["split"] for row in rows)),
        "search_limited_files": sum(bool(row.get("search_limited")) for row in records),
        "curation_truncated_files": sum(bool(row.get("curation_truncated")) for row in records),
        "drum_search_limited_files": sum(bool(row.get("drum_stats", {}).get("search_limited")) for row in records),
        "warning_files": sum(bool(row.get("warnings")) for row in records),
        "exact_arrangement_fingerprints": len({row["musical_sha256"] for row in records if row.get("note_count", 0)}),
        "family_split_conflict_rows": sum(row["split"] == "overlap_excluded" for row in rows),
        "unique_phrase_families": len({(row["kind"], row["family_id"]) for row in rows}),
        "worker_seconds": round(sum(row["elapsed_seconds"] for row in records), 3),
    }
    if "metadata_recovered_files" in saved_summary:
        values["metadata_recovered_files"] = sum(
            bool(row.get("metadata_repairs")) for row in records
        )
    if "metadata_repair_events" in saved_summary:
        values["metadata_repair_events"] = sum(
            len(row.get("metadata_repairs", [])) for row in records
        )
    values.update(config)
    return values


def _without_artifact(phrase: dict) -> dict:
    return {key: value for key, value in phrase.items()
            if key not in {"midi_path", "midi_sha256"}}


def _reextract_record(song, record: dict, config: dict) -> list[str]:
    problems = []
    algorithm = config.get("algorithm", "reference")
    if algorithm == "aligned":
        found = extract_aligned(song, AlignedConfig(**config["config"]))
    elif algorithm == "aligned_indexed":
        found = extract_indexed(song, AlignedConfig(**config["config"]))
    elif algorithm == "aligned_closed":
        found = extract_closed_patterns(song, AlignedConfig(**config["config"]), algorithm="aligned_indexed")
        found["algorithm"] = algorithm
    elif algorithm == "aligned_melody":
        found = extract_part_ranked(song, AlignedConfig(**config["config"]))
    else:
        found = extract(song, Config(**config["config"]))
    phrases = [{**phrase, "kind": "melodic"} for phrase in found.pop("phrases")]
    for key, value in found.items():
        if canonical_json(record.get(key)) != canonical_json(value):
            problems.append(f"re-extracted {key} differs")
    if config.get("percussion"):
        drums = extract_drums(song)
        phrases.extend(drums["phrases"])
        if canonical_json(record.get("drum_stats")) != canonical_json(drums["stats"]):
            problems.append("re-extracted drum_stats differs")
    for rank, phrase in enumerate(phrases, 1):
        phrase["phrase_id"] = digest((record["source_id"], phrase["kind"],
            phrase["part_index"], phrase["family_id"], phrase["start_tick"],
            config["run_key"]))[:32]
        phrase["rank_in_file"] = rank
    saved = [_without_artifact(phrase) for phrase in record.get("phrases", [])]
    if canonical_json(saved) != canonical_json(phrases):
        problems.append("re-extracted phrases differ")
    return problems


def audit(source: Path, output: Path, *, require_full: bool = False,
          reextract: bool = False) -> dict:
    source, output = source.resolve(), output.resolve()
    binding_paths = {
        "source_manifest_sha256": output / "sources.jsonl",
        "phrase_manifest_sha256": output / "phrases.jsonl",
        "build_config_sha256": output / "build_config.json",
        "summary_sha256": output / "summary.json",
    }
    binding_hashes = {
        key: file_digest(path) for key, path in binding_paths.items()
    }
    records = _read(output / "sources.jsonl")
    rows = _read(output / "phrases.jsonl")
    config = json.loads((output / "build_config.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    source_manifest_sha256 = binding_hashes["source_manifest_sha256"]
    phrase_manifest_sha256 = binding_hashes["phrase_manifest_sha256"]
    errors: list[dict[str, str]] = []
    counts: Counter = Counter()

    def require(condition: bool, where: object, reason: str) -> None:
        if not condition:
            errors.append({"where": str(where), "reason": reason})

    require(source_manifest_sha256 == summary.get("source_manifest_sha256"),
            "sources.jsonl", "manifest hash mismatch")
    require(phrase_manifest_sha256 == summary.get("phrase_manifest_sha256"),
            "phrases.jsonl", "manifest hash mismatch")
    for key, value in config.items():
        require(summary.get(key) == value, "summary.json", f"{key} differs from build config")
    run_fields = {"config", "code_sha256", "version", "export", "percussion"}
    new_fingerprint_fields = {"algorithm", "recover_invalid_keys"}
    if run_fields | new_fingerprint_fields | {"runtime"} <= config.keys():
        runtime = config.get("runtime")
        valid_runtime = (
            isinstance(runtime, dict)
            and set(runtime) == {"python_implementation", "python_version", "mido_version"}
            and all(isinstance(value, str) and value for value in runtime.values())
        )
        require(valid_runtime, "build_config.json", "runtime fingerprint is invalid")
        require(runtime == runtime_metadata(), "build_config.json",
                "runtime fingerprint differs from current environment")
        run_key = digest({"config": config["config"], "code": config["code_sha256"],
                          "version": config["version"], "export": config["export"],
                          "percussion": config["percussion"],
                          "algorithm": config["algorithm"],
                          "recover_invalid_keys": config["recover_invalid_keys"],
                          "runtime": runtime})
        require(config.get("run_key") == run_key, "build_config.json",
                "run key differs from build inputs")
    elif run_fields <= config.keys() and not (new_fingerprint_fields & config.keys()):
        run_key = digest({"config": config["config"], "code": config["code_sha256"],
                          "version": config["version"], "export": config["export"],
                          "percussion": config["percussion"]})
        require(config.get("run_key") == run_key, "build_config.json",
                "run key differs from build inputs")
    elif run_fields | new_fingerprint_fields <= config.keys():
        run_key = digest({"config": config["config"], "code": config["code_sha256"],
                          "version": config["version"], "export": config["export"],
                          "percussion": config["percussion"],
                          "algorithm": config["algorithm"],
                          "recover_invalid_keys": config["recover_invalid_keys"]})
        require(config.get("run_key") == run_key, "build_config.json",
                "run key differs from build inputs")
    else:
        require(False, "build_config.json", "build fingerprint fields missing")
    algorithm = config.get("algorithm", "reference")
    recover_invalid_keys = config.get("recover_invalid_keys", False)
    recovery_explicitly_enabled = (
        "recover_invalid_keys" in config and recover_invalid_keys is True
    )
    require(algorithm == "reference" or algorithm in _ALIGNED_ALGORITHMS,
            "build_config.json",
            "invalid extraction algorithm")
    require(type(recover_invalid_keys) is bool, "build_config.json",
            "recover_invalid_keys is not a boolean")
    if algorithm in _ALIGNED_ALGORITHMS:
        for problem in validate_aligned_config(config.get("config")):
            require(False, "build_config.json", problem)
    snapshot = output/"provenance"/"samuged"
    require(snapshot.is_dir(), "provenance/samuged", "code provenance snapshot missing")
    if snapshot.is_dir() and config.get("code_sha256"):
        require(_code_digest(snapshot) == config["code_sha256"], "provenance/samuged",
                "code fingerprint mismatch")

    ids = [row.get("source_id") for row in records]
    paths = [row.get("source_path") for row in records]
    require(len(ids) == len(set(ids)), "sources.jsonl", "duplicate source ID")
    require(len(paths) == len(set(paths)), "sources.jsonl", "duplicate source path")
    splits: dict[str, tuple[str, str]] = {}
    expected_rows: list[dict] = []
    if all(isinstance(value, str) for value in ids):
        try:
            splits = _expected_source_splits(records)
            expected_rows = _expected_rows(records, splits)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"where": "sources.jsonl",
                           "reason": f"cannot reconstruct finalized rows: {exc}"})
    expected_by_id = {row["phrase_id"]: row for row in expected_rows
                      if isinstance(row.get("phrase_id"), str)}
    actual_by_id: dict[str, dict] = {}
    source_id_set = set(ids)
    for row in rows:
        phrase_id = row.get("phrase_id")
        require(isinstance(phrase_id, str), "phrases.jsonl", "phrase ID missing")
        if not isinstance(phrase_id, str):
            continue
        require(phrase_id not in actual_by_id, phrase_id, "duplicate phrase ID")
        actual_by_id[phrase_id] = row
        require(row.get("source_id") in source_id_set, phrase_id,
                "phrase references unknown source ID")
    require(set(actual_by_id) == set(expected_by_id), "phrases.jsonl",
            "phrase membership differs from source records")
    for phrase_id in sorted(set(actual_by_id) & set(expected_by_id)):
        require(canonical_json(actual_by_id[phrase_id]) == canonical_json(expected_by_id[phrase_id]),
                phrase_id, "phrase row differs from source record or finalized split")
    for record in records:
        if record.get("source_id") in splits:
            group, split = splits[record["source_id"]]
            require(record.get("split_group") == group, record["source_id"],
                    "split group differs from recomputed assignment")
            require(record.get("split") == split, record["source_id"],
                    "split differs from recomputed assignment")
        for rank, phrase in enumerate(record.get("phrases", []), 1):
            require(phrase.get("rank_in_file") == rank,
                    phrase.get("phrase_id", record.get("source_id")),
                    "phrase rank differs from saved order")

    expected_summary = _expected_summary(config, records, rows, summary)
    for key, value in expected_summary.items():
        require(summary.get(key) == value, "summary.json", f"{key} count or value mismatch")
    if require_full:
        actual_paths = {path.relative_to(source).as_posix() for path in discover(source)}
        require(set(paths) == actual_paths, "sources.jsonl",
                "source coverage differs from discovered corpus")

    by_source: dict[str, list[dict]] = defaultdict(list)
    families: dict[tuple[str, str], set[str]] = defaultdict(set)
    artists: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if isinstance(row.get("source_id"), str):
            by_source[row["source_id"]].append(row)
        if all(key in row for key in ("kind", "family_id", "split")) and row["split"] != "overlap_excluded":
            families[(row["kind"], row["family_id"])].add(row["split"])

    for record in records:
        source_id, location = record.get("source_id", "unknown"), record.get("source_path", "unknown")
        path = _contained(source, location)
        require(path is not None, location, "source path escapes source root")
        if path is None:
            continue
        require(path.is_file(), location, "source missing")
        if not path.is_file():
            continue
        try:
            source_bytes, source_hash = path.stat().st_size, file_digest(path)
        except OSError as exc:
            errors.append({"where": str(location), "reason": f"source read failed: {exc}"})
            continue
        require(record.get("source_bytes") == source_bytes, location, "source byte count mismatch")
        require(record.get("source_sha256") == source_hash, location, "source hash mismatch")
        require(record.get("source_id") == digest((source_hash, location))[:24], location,
                "source ID differs from path and content")
        for key, value in source_labels(location).items():
            require(record.get(key) == value, location, f"{key} differs from source path")
        require(record.get("run_key") == config.get("run_key"), location, "source run key mismatch")
        if isinstance(record.get("artist_key"), str) and isinstance(record.get("split"), str):
            artists[record["artist_key"]].add(record["split"])
        status, outcome = record.get("status"), record.get("outcome")
        require(status in {"ok", "error"}, location, "invalid source status")
        if status == "ok":
            expected_outcome = "matched" if record.get("phrases") else "no_match"
            require(outcome == expected_outcome, location,
                    "source outcome differs from saved phrases")
        else:
            require(not record.get("phrases"), location, "error source contains phrases")
            counts["reported_input_errors"] += 1
            if outcome == "read_error":
                require(False, location, "reported read error is not reproducible")
                continue
            try:
                error_song = (
                    load_midi(path, recover_invalid_keys=True)
                    if recovery_explicitly_enabled
                    else load_midi(path)
                )
            except Exception:
                require(outcome == "parse_error", location,
                        "reported source error stage differs from current parse failure")
                continue
            if outcome == "parse_error":
                require(False, location, "reported parse error is not reproducible")
                continue
            require(outcome == "extraction_error", location,
                    "unknown source error outcome")
            if reextract and outcome == "extraction_error":
                try:
                    if algorithm == "aligned":
                        extract_aligned(error_song, AlignedConfig(**config["config"]))
                    elif algorithm == "aligned_indexed":
                        extract_indexed(error_song, AlignedConfig(**config["config"]))
                    elif algorithm == "aligned_closed":
                        extract_closed_patterns(error_song, AlignedConfig(**config["config"]), algorithm="aligned_indexed")
                    elif algorithm == "aligned_melody":
                        extract_part_ranked(error_song, AlignedConfig(**config["config"]))
                    else:
                        extract(error_song, Config(**config["config"]))
                    if config.get("percussion"):
                        extract_drums(error_song)
                except Exception:
                    pass
                else:
                    require(False, location,
                            "reported extraction error is not reproducible")
            continue
        try:
            song = (
                load_midi(path, recover_invalid_keys=True)
                if recovery_explicitly_enabled
                else load_midi(path)
            )
            ppq = song.ticks_per_beat
            require(record.get("ticks_per_beat") == ppq, location, "source PPQ mismatch")
            require(record.get("part_count") == len(song.parts), location, "source part count mismatch")
            require(record.get("note_count") == sum(len(part.notes) for part in song.parts), location,
                    "source note count mismatch")
            require(record.get("warnings") == song.warnings, location, "source warnings mismatch")
            require(record.get("metadata_repairs", []) == song.metadata_repairs,
                    location, "source metadata repairs differ from current loader")
            require(("metadata_repairs" in record) == bool(song.metadata_repairs),
                    location, "source metadata repair presence differs from current loader")
            require(record.get("musical_sha256") == musical_digest(song), location,
                    "source musical fingerprint mismatch")
            if algorithm == "aligned_closed":
                require(record.get("algorithm") == algorithm, location,
                        "closed source algorithm differs from build")
                require(record.get("selection") == "closed-exact-extension-v1", location,
                        "closed source selection policy differs")
                trace = record.get("selection_trace")
                require(isinstance(trace, list), location, "closed selection trace is missing")
                require(type(record.get("closed_extension_count")) is int
                        and isinstance(trace, list)
                        and record["closed_extension_count"] == len(trace), location,
                        "closed extension count differs from trace")
                last_tick = max((note.end for part in song.parts for note in part.notes), default=0)
                for problem in verify_closed_trace(record, config["config"], last_tick):
                    require(False, location, problem)
            elif algorithm == "aligned_melody":
                require(record.get("algorithm") == ALGORITHM_NAME, location,
                        "part-ranked source algorithm differs from build")
                require(record.get("selection") == PART_PRIOR_VERSION, location,
                        "part-ranked source selection policy differs")
                for problem in verify_part_ranking(
                    record, song, config.get("config", {}).get("top_k")
                ):
                    require(False, location, problem)
            if reextract:
                for problem in _reextract_record(song, record, config):
                    require(False, location, problem)
            parts = {part.index: part for part in song.parts}
            streams: dict[int, list[Note]] = {}
            for row in by_source[source_id]:
                where, kind = row.get("phrase_id", location), row.get("kind")
                counts[str(kind)] += 1
                occurrences = row.get("occurrences", [])
                require(row.get("occurrence_count") == len(occurrences) >= 2, where,
                        "invalid support count")
                require(all(a["end_tick"] <= b["start_tick"] for a, b in zip(occurrences, occurrences[1:])),
                        where, "overlapping independent occurrences")
                require(all(o["start_tick"] >= 0 and o["end_tick"] > o["start_tick"] for o in occurrences),
                        where, "invalid occurrence bounds")
                if kind == "melodic":
                    part = parts.get(row.get("part_index"))
                    require(part is not None, where, "source part absent")
                    if part is None:
                        continue
                    require(row.get("source_track") == part.track, where, "source track mismatch")
                    require(row.get("channel") == part.channel, where, "source channel mismatch")
                    require(row.get("program") == part.program, where, "source program mismatch")
                    require(row.get("part_name") == part.name, where, "source part name mismatch")
                    if part.index not in streams:
                        streams[part.index] = skyline(part, ppq, config["config"]["onset_merge_beats"])
                    stream = streams[part.index]
                    note_count = row.get("note_count")
                    index = row.get("prototype_note_index")
                    valid_prototype_index = type(index) is int and index >= 0
                    valid_prototype_count = type(note_count) is int and note_count > 0
                    require(valid_prototype_index, where, "invalid prototype note index")
                    require(valid_prototype_count, where, "invalid prototype note count")
                    if algorithm in _ALIGNED_ALGORITHMS and valid_prototype_count:
                        require(config["config"]["min_notes"] <= note_count
                                <= config["config"]["max_notes"], where,
                                "prototype note count is outside aligned config bounds")
                    proto = (stream[index:index+note_count]
                             if valid_prototype_index and valid_prototype_count else [])
                    require(len(proto) == note_count, where, "prototype absent in source")
                    if not proto:
                        continue
                    prototype = window(stream, index, note_count, ppq)
                    require((row.get("start_tick"), row.get("end_tick")) == (prototype.start, prototype.end),
                            where, "prototype bounds differ from source")
                    require(row.get("duration_beats") == round((prototype.end-prototype.start)/ppq, 8),
                            where, "prototype duration differs from source")
                    require(row.get("pitches") == list(prototype.pitches), where,
                            "prototype pitches differ from source")
                    require(row.get("onsets_beats") == [round(value, 8) for value in prototype.onsets],
                            where, "prototype onsets differ from source")
                    require(row.get("durations_beats") == [round(value, 8) for value in prototype.durations],
                            where, "prototype durations differ from source")
                    require(row.get("velocities") == [note.velocity for note in prototype.notes],
                            where, "prototype velocities differ from source")
                    transpose_family = (True if algorithm in _ALIGNED_ALGORITHMS
                                        else config["config"]["mode"] != "exact")
                    require(row.get("family_id") == signature(prototype, transpose=transpose_family),
                            where, "phrase family differs from prototype")
                    if algorithm in _ALIGNED_ALGORITHMS:
                        require(row.get("matcher_flags") == EXPECTED_MATCHER_FLAGS,
                                where, "aligned matcher flags differ")
                        raw_count = row.get("raw_occurrence_count")
                        require(type(raw_count) is int and raw_count >= len(occurrences),
                                where, "invalid raw aligned support count")
                        for occurrence in occurrences:
                            occurrence_count = occurrence.get("note_count")
                            occurrence_index = occurrence.get("note_index")
                            valid_occurrence_count = (
                                type(occurrence_count) is int
                                and config["config"]["min_notes"] <= occurrence_count
                                <= config["config"]["max_notes"]
                            )
                            valid_occurrence_index = (
                                type(occurrence_index) is int and occurrence_index >= 0
                            )
                            require(valid_occurrence_count, where,
                                    "occurrence note count is outside aligned config bounds")
                            require(valid_occurrence_index, where,
                                    "invalid occurrence note index")
                            notes = (stream[occurrence_index:occurrence_index+occurrence_count]
                                     if valid_occurrence_count and valid_occurrence_index
                                     else [])
                            require(len(notes) == occurrence_count, where,
                                    "occurrence absent in source")
                            if notes:
                                for problem in verify_alignment(
                                    proto, notes, occurrence, ppq, config["config"]
                                ):
                                    require(False, where, problem)
                    else:
                        for occurrence in occurrences:
                            notes = stream[occurrence["note_index"]:occurrence["note_index"]+note_count]
                            require(len(notes) == note_count, where, "occurrence absent in source")
                            if len(notes) == note_count:
                                require(notes[0].start == occurrence["start_tick"] and
                                        max(note.end for note in notes) == occurrence["end_tick"],
                                        where, "occurrence coordinates differ from source")
                                pitch_errors = sum(
                                    candidate.pitch-reference.pitch
                                    != occurrence["transpose_semitones"]
                                    for reference, candidate in zip(proto, notes)
                                )
                                onsets = [(note.start-notes[0].start)/ppq for note in notes]
                                durations = [(note.end-note.start)/ppq for note in notes]
                                cfg = config["config"]
                                if cfg["mode"] == "approximate":
                                    require(pitch_errors <= int(note_count*cfg["pitch_error_fraction"]),
                                            where, "pitch tolerance violated")
                                    require(max(abs(left-right) for left, right in
                                                zip(onsets, row["onsets_beats"]))
                                            <= cfg["timing_tolerance"]+1e-7,
                                            where, "onset tolerance violated")
                                    duration_errors = [abs(left-right) for left, right in
                                                       zip(durations, row["durations_beats"])]
                                    require(sum(value > cfg["duration_tolerance"]+1e-7
                                                for value in duration_errors)
                                            <= int(note_count*cfg["duration_error_fraction"]),
                                            where, "duration count tolerance violated")
                                    require(sum(duration_errors)/note_count
                                            <= cfg["duration_tolerance"]+1e-7,
                                            where, "mean duration tolerance violated")
                                else:
                                    require(pitch_errors == 0, where, "exact pitch mismatch")
                                    require(all(round(left*24) == round(right*24)
                                                for left, right in zip(onsets, row["onsets_beats"])),
                                            where, "exact onset mismatch")
                                    require(all(round(left*24) == round(right*24)
                                                for left, right in zip(durations, row["durations_beats"])),
                                            where, "exact duration mismatch")
                                    if cfg["mode"] == "exact":
                                        require(occurrence["transpose_semitones"] == 0, where,
                                                "absolute pitch mode transposed")
                    selected_notes = [Note(row["start_tick"]+round(onset*ppq),
                                           row["start_tick"]+round((onset+duration)*ppq),
                                           pitch, velocity)
                                      for onset, duration, pitch, velocity in zip(
                                          row["onsets_beats"], row["durations_beats"],
                                          row["pitches"], row["velocities"])]
                elif kind == "percussion":
                    part = drum_part(song)
                    source_parts = [p for p in song.parts if p.is_drum]
                    require(row.get("source_part_indices") == sorted(p.index for p in source_parts),
                            where, "drum source parts differ")
                    require(row.get("source_tracks") == sorted({p.track for p in source_parts}),
                            where, "drum source tracks differ")
                    require(row.get("kit_programs") == sorted({p.program for p in source_parts}),
                            where, "drum kit programs differ")
                    require(row.get("duration_policy") == "clip_at_next_same_pitch_hit",
                            where, "drum duration policy differs")
                    bars = row.get("bar_count")
                    require(bars in (1, 2, 4), where, "invalid drum bar count")
                    meter = (row.get("meter_numerator"), row.get("meter_denominator"))
                    if bars in (1, 2, 4):
                        for interval in [row, *occurrences]:
                            require(_drum_window_meter(song, interval["start_tick"], interval["end_tick"], bars) == meter,
                                    where, "drum interval differs from source meter and bar grid")
                    require(row.get("duration_beats") == round((row["end_tick"]-row["start_tick"])/ppq, 8),
                            where, "drum duration differs from source bounds")
                    selected_notes = [note for note in part.notes
                                      if row["start_tick"] <= note.start < row["end_tick"]]
                    proto = selected_notes
                    require(len(proto) >= 8 and len({note.pitch for note in proto}) >= 2,
                            where, "drum prototype lacks required hits or instruments")
                    require(row.get("part_index") == -1, where, "percussion part index mismatch")
                    require(row.get("channel") == 9, where, "percussion channel mismatch")
                    require(row.get("note_count") == len(proto), where, "drum prototype count differs")
                    require(row.get("pitches") == [note.pitch for note in proto], where,
                            "drum prototype pitches differ")
                    require(row.get("onsets_beats") == [round((note.start-row["start_tick"])/ppq, 8) for note in proto],
                            where, "drum prototype onsets differ")
                    require(row.get("durations_beats") == [round((note.end-note.start)/ppq, 8) for note in proto],
                            where, "drum prototype durations differ")
                    require(row.get("velocities") == [note.velocity for note in proto], where,
                            "drum prototype velocities differ")
                    span = Fraction(row["end_tick"]-row["start_tick"], ppq)
                    hits = []
                    for note in proto:
                        onset = Fraction(note.start-row["start_tick"], ppq)
                        hits.append((note.pitch, onset.numerator, onset.denominator))
                    require(row.get("family_id") == digest({"window_beats": (span.numerator, span.denominator),
                                                            "hits": hits}), where,
                            "drum family differs from prototype")
                    require(all(o.get("transpose_semitones") == 0 for o in occurrences), where,
                            "percussion was transposed")
                    reference: dict[int, list[float]] = defaultdict(list)
                    for note in proto:
                        reference[note.pitch].append((note.start-row["start_tick"])/ppq)
                    for occurrence in occurrences:
                        notes = [note for note in part.notes
                                 if occurrence["start_tick"] <= note.start < occurrence["end_tick"]]
                        candidate: dict[int, list[float]] = defaultdict(list)
                        for note in notes:
                            candidate[note.pitch].append(
                                (note.start-occurrence["start_tick"])/ppq
                            )
                        matched = 0
                        for pitch, reference_onsets in reference.items():
                            matched += _matched_strikes(reference_onsets, candidate[pitch], 1/12+1e-7)
                        require(len(proto)+len(notes)-2*matched
                                <= int(max(len(proto), len(notes))*.10), where,
                                "percussion hit tolerance violated")
                else:
                    require(False, where, "unknown phrase kind")
                    continue
                arrays = (row.get("pitches", []), row.get("onsets_beats", []),
                          row.get("durations_beats", []), row.get("velocities", []))
                require(all(len(values) == len(proto) for values in arrays), where,
                        "inconsistent note arrays")
                expected_id = digest((source_id, kind, row["part_index"], row["family_id"],
                                      row["start_tick"], config["run_key"]))[:32]
                require(row.get("phrase_id") == expected_id, where,
                        "phrase ID differs from defining fields")
                has_artifact = "midi_path" in row or "midi_sha256" in row
                require(has_artifact == bool(config.get("export")), where,
                        "artifact presence differs from export configuration")
                if not has_artifact:
                    continue
                expected_path = f"midi/{kind}/{row['phrase_id']}.mid"
                require(row.get("midi_path") == expected_path, where,
                        "MIDI artifact path differs from phrase ID")
                artifact = _contained(output, row.get("midi_path"))
                require(artifact is not None, where, "MIDI artifact path escapes output root")
                if artifact is None:
                    continue
                require(artifact.is_file(), where, "MIDI artifact missing")
                if not artifact.is_file():
                    continue
                artifact_hash = file_digest(artifact)
                require(artifact_hash == row.get("midi_sha256"), where, "MIDI hash mismatch")
                if artifact_hash != row.get("midi_sha256"):
                    continue
                rendered = load_midi(artifact)
                start, end = row["start_tick"], row["end_tick"]
                expected_notes = sorted((max(note.start, start)-start, min(note.end, end)-start,
                                         note.pitch, note.velocity) for note in selected_notes
                                        if max(note.start, start) < min(note.end, end))
                actual_notes = sorted((note.start, note.end, note.pitch, note.velocity)
                                      for rendered_part in rendered.parts for note in rendered_part.notes)
                require(actual_notes == expected_notes, where,
                        "export differs from original selected notes")
                require(len(rendered.parts) == 1, where, "export part count differs")
                if len(rendered.parts) == 1:
                    rendered_part = rendered.parts[0]
                    require(rendered_part.channel == part.channel, where, "export channel differs")
                    require(rendered_part.program == part.program, where, "export program differs")
                    require(rendered_part.name == part.name, where, "export part name differs")
                midi = mido.MidiFile(artifact, clip=False)
                lengths = [sum(message.time for message in track) for track in midi.tracks]
                require(bool(lengths) and all(length == end-start for length in lengths), where,
                        "export track length differs from requested clip")
                require(rendered.ticks_per_beat == ppq, where, "export PPQ differs")
                require(rendered.tempos == _cropped_changes(song.tempos, start, end), where,
                        "export tempo map differs")
                require(rendered.meters == _cropped_changes(song.meters, start, end), where,
                        "export meter map differs")
                counts["midi_verified"] += 1
        except Exception as exc:
            errors.append({"where": str(location), "reason": f"{type(exc).__name__}: {exc}"})
        counts["sources_verified"] += 1

    require(all(len(values) == 1 for values in families.values()), "splits",
            "canonical family crosses splits")
    require(all(len(values) == 1 for values in artists.values()), "splits",
            "artist crosses splits")
    for key, path in binding_paths.items():
        try:
            unchanged = file_digest(path) == binding_hashes[key]
        except OSError as exc:
            errors.append({"where": path.name,
                           "reason": f"audit input unavailable at final check: {exc}"})
        else:
            require(unchanged, path.name, "audit input changed while audit was running")
    result = {"passed": not errors, "source_files": len(records),
              "phrase_rows": len(rows), "counts": dict(counts),
              "failure_count": len(errors), "failures": errors,
              "run_key": summary.get("run_key"),
              **binding_hashes,
              "full_source_coverage_required": require_full,
              "reextraction_required": reextract,
              "scope": "manifest, provenance, source reconstruction and exported MIDI semantics"}
    atomic_json(output/"audit.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--reextract", action="store_true")
    args = parser.parse_args()
    result = audit(args.source, args.output, require_full=args.require_full,
                   reextract=args.reextract)
    print(json.dumps({key: value for key, value in result.items() if key != "failures"}, indent=2))
    if result["failures"]:
        print(json.dumps(result["failures"][:10], indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
