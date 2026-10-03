"""Resumable local corpus extraction with per-file accounting and provenance."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
import unicodedata

from . import __version__
from .midi import Note, export_phrase, load_midi
from .phrases import Config, extract


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def file_digest(path: Path) -> str:
    result = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(canonical_json(value)+"\n", encoding="utf-8")
    temp.replace(path)


def code_digest() -> str:
    root = Path(__file__).parent
    return digest({p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))})


def discover(root: Path) -> list[Path]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source must be a directory")
    # Include hidden artist folders (.38 Special); do not follow external symlinks.
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                  and p.suffix.lower() in {".mid", ".midi"} and p.resolve().is_relative_to(root))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())


def source_labels(rel: str) -> dict:
    p = Path(rel)
    artist = p.parts[0] if len(p.parts) > 1 else "unknown"
    title = re.sub(r"\.\d+$", "", p.stem)
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", artist).encode("ascii", "ignore").decode().lower())
    # Conservative split grouping joins word-order aliases such as Michael
    # Jackson / Jackson Michael. This is not an assertion of artist identity.
    artist_key = "".join(sorted(t for t in tokens if t != "the")) or digest(artist)[:16]
    return {"artist_from_path": artist, "title_from_path": title,
            "artist_key": artist_key,
            "song_key": digest((artist_key, _normalize(title)))[:24]}


def musical_digest(song) -> str:
    """Exact normalized arrangement fingerprint, not a cover-song detector."""
    all_notes = [n for p in song.parts for n in p.notes]
    if not all_notes:
        return digest([])
    start = min(n.start for n in all_notes)
    pitched = [n.pitch for p in song.parts if not p.is_drum for n in p.notes]
    anchor = min(pitched, default=0)
    ppq = song.ticks_per_beat
    parts = []
    for part in song.parts:
        if part.notes:
            parts.append((part.is_drum, tuple(sorted((round((n.start-start)*24/ppq),
                round((n.end-n.start)*24/ppq), n.pitch if part.is_drum else n.pitch-anchor)
                for n in part.notes))))
    return digest(sorted(parts))


def _work(task):
    path_string, rel, output_string, config, run_key, export, percussion, *options = task
    algorithm = options[0] if options else "reference"
    recover_invalid_keys = options[1] if len(options) > 1 else False
    start = time.monotonic()
    path, output = Path(path_string), Path(output_string)
    try:
        source_hash = file_digest(path)
        source_bytes = path.stat().st_size
    except OSError as exc:
        record = {"source_id": digest(("unreadable", rel))[:24], "source_path": rel,
                  "source_sha256": None, "source_bytes": None, "run_key": run_key,
                  **source_labels(rel), "status": "error", "outcome": "read_error",
                  "error_type": type(exc).__name__, "error": str(exc), "phrases": [],
                  "elapsed_seconds": round(time.monotonic()-start, 6)}
        atomic_json(output / "records" / f"{record['source_id']}.json", record)
        return record
    source_id = digest((source_hash, rel))[:24]
    cache = output / "records" / f"{source_id}.json"
    if cache.exists():
        try:
            saved = json.loads(cache.read_text())
        except (ValueError, OSError):
            saved = {}
        if (saved.get("run_key") == run_key and saved.get("source_sha256") == source_hash
                and saved.get("status") == "ok"):
            try:
                midi_ok = all((output / p["midi_path"]).is_file()
                              and file_digest(output/p["midi_path"]) == p.get("midi_sha256")
                              for p in saved.get("phrases", []) if "midi_path" in p)
            except OSError:
                midi_ok = False
            if midi_ok:
                saved["source_path"] = rel
                return saved
    record = {"source_id": source_id, "source_path": rel, "source_sha256": source_hash,
              "source_bytes": source_bytes, "run_key": run_key, **source_labels(rel)}
    stage = "parse"
    try:
        song = (load_midi(path, recover_invalid_keys=True) if recover_invalid_keys
                else load_midi(path))
        stage = "extraction"
        if algorithm in {"aligned", "aligned_indexed", "aligned_closed"}:
            from .aligned import AlignedConfig, extract_aligned
            if algorithm == "aligned_closed":
                from .closed_patterns import extract_closed_patterns
                found = extract_closed_patterns(song, AlignedConfig(**config), algorithm="aligned_indexed")
                found["algorithm"] = algorithm
            elif algorithm == "aligned_indexed":
                from .aligned_indexed import extract_indexed
                found = extract_indexed(song, AlignedConfig(**config))
            else:
                found = extract_aligned(song, AlignedConfig(**config))
        else:
            found = extract(song, Config(**config))
        phrases = [{**p, "kind": "melodic"} for p in found.pop("phrases")]
        record.update(found)
        if percussion:
            from .drums import extract_drums
            drums = extract_drums(song)
            phrases.extend(drums["phrases"])
            record["drum_stats"] = drums["stats"]
        record.update(status="ok", outcome="matched" if phrases else "no_match", ticks_per_beat=song.ticks_per_beat,
                      part_count=len(song.parts), note_count=sum(len(p.notes) for p in song.parts),
                      warnings=song.warnings, musical_sha256=musical_digest(song),
                      phrases=phrases)
        if getattr(song, "metadata_repairs", None):
            record["metadata_repairs"] = song.metadata_repairs
        for rank, phrase in enumerate(phrases, 1):
            phrase["phrase_id"] = digest((source_id, phrase["kind"], phrase["part_index"],
                                           phrase["family_id"], phrase["start_tick"], run_key))[:32]
            phrase["rank_in_file"] = rank
            if export:
                # ASVS 5.3.2: output filenames come only from internally generated hex IDs.
                target = Path("midi") / phrase["kind"] / f"{phrase['phrase_id']}.mid"
                (output / target).parent.mkdir(parents=True, exist_ok=True)
                if phrase["kind"] == "melodic":
                    part = next(p for p in song.parts if p.index == phrase["part_index"])
                    notes = [Note(phrase["start_tick"]+round(t*song.ticks_per_beat),
                                  phrase["start_tick"]+round((t+d)*song.ticks_per_beat), p, v)
                             for t, d, p, v in zip(phrase["onsets_beats"], phrase["durations_beats"],
                                                   phrase["pitches"], phrase["velocities"])]
                else:
                    from .drums import drum_part
                    part = drum_part(song)
                    notes = [n for n in part.notes if phrase["start_tick"] <= n.start < phrase["end_tick"]]
                export_phrase(song, part, notes, phrase["start_tick"], phrase["end_tick"], output / target)
                phrase["midi_path"] = target.as_posix()
                phrase["midi_sha256"] = sha256((output / target).read_bytes()).hexdigest()
        record["elapsed_seconds"] = round(time.monotonic()-start, 6)
    except Exception as exc:
        record.update(status="error", outcome=f"{stage}_error", error_type=type(exc).__name__, error=str(exc), phrases=[],
                      elapsed_seconds=round(time.monotonic()-start, 6))
    atomic_json(cache, record)
    return json.loads(canonical_json(record))


class _Union:
    def __init__(self, keys):
        self.parent = {k:k for k in keys}

    def find(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a, b):
        x, y = sorted((self.find(a), self.find(b)))
        self.parent[y] = x


def finalize(records: list[dict], output: Path, metadata: dict) -> dict:
    records.sort(key=lambda r: r["source_path"])
    uf = _Union(r["source_id"] for r in records)
    links = {}
    for row in records:
        keys = [("artist", row["artist_key"]), ("song", row["song_key"])]
        if row["source_sha256"]:
            keys.append(("sha", row["source_sha256"]))
        if row.get("note_count", 0):
            keys.append(("musical", row["musical_sha256"]))
        for key in keys:
            if key in links:
                uf.join(row["source_id"], links[key])
            else:
                links[key] = row["source_id"]
    for row in records:
        row["split_group"] = uf.find(row["source_id"])
        bucket = int(sha256(("samuged-split-v1:"+row["split_group"]).encode()).hexdigest()[:8], 16) % 100
        row["split"] = "train" if bucket < 80 else "validation" if bucket < 90 else "test"
    families = {}
    rows = []
    for source in records:
        for p in source.get("phrases", []):
            row = {k:source[k] for k in ("source_id", "source_sha256", "source_path", "artist_from_path",
                   "title_from_path", "song_key", "split", "split_group", "ticks_per_beat")}
            row.update(p)
            rows.append(row)
            families.setdefault((p["kind"], p["family_id"]), set()).add(source["split"])
    conflict = 0
    for row in rows:
        seen = families[(row["kind"], row["family_id"])]
        preferred = next(split for split in ("train", "validation", "test") if split in seen)
        if row["split"] != preferred:
            row["source_split"] = row["split"]
            row["split"] = "overlap_excluded"
            conflict += 1
    manifest = output / "sources.jsonl"
    manifest.write_text("".join(canonical_json(r)+"\n" for r in records), encoding="utf-8")
    phrases = output / "phrases.jsonl"
    phrases.write_text("".join(canonical_json(r)+"\n" for r in rows), encoding="utf-8")
    from collections import Counter
    summary = {**metadata, "source_files": len(records), "source_status": dict(Counter(r["status"] for r in records)),
               "source_outcomes": dict(Counter(r.get("outcome", r["status"]) for r in records)),
               "source_files_with_melodic_phrases": sum(any(p["kind"] == "melodic" for p in r.get("phrases", [])) for r in records),
               "source_files_with_percussion_phrases": sum(any(p["kind"] == "percussion" for p in r.get("phrases", [])) for r in records),
               "phrase_counts": dict(Counter(r["kind"] for r in rows)),
               "split_counts": dict(Counter(r["split"] for r in rows)),
               "search_limited_files": sum(bool(r.get("search_limited")) for r in records),
               "curation_truncated_files": sum(bool(r.get("curation_truncated")) for r in records),
               "drum_search_limited_files": sum(bool(r.get("drum_stats", {}).get("search_limited")) for r in records),
               "warning_files": sum(bool(r.get("warnings")) for r in records),
               "metadata_recovered_files": sum(bool(r.get("metadata_repairs")) for r in records),
               "metadata_repair_events": sum(len(r.get("metadata_repairs", [])) for r in records),
               "exact_arrangement_fingerprints": len({r["musical_sha256"] for r in records if r.get("note_count", 0)}),
               "family_split_conflict_rows": conflict,
               "unique_phrase_families": len(families),
               "source_manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
               "phrase_manifest_sha256": sha256(phrases.read_bytes()).hexdigest(),
               "worker_seconds": round(sum(r["elapsed_seconds"] for r in records), 3)}
    atomic_json(output / "summary.json", summary)
    return summary


def build(source: Path, output: Path, cfg, *, workers=4, limit=None, export=True,
          percussion=False, algorithm="reference", recover_invalid_keys=False):
    if algorithm not in {"reference", "aligned", "aligned_indexed", "aligned_closed"}:
        raise ValueError("algorithm must be reference, aligned, aligned_indexed or aligned_closed")
    if algorithm in {"aligned", "aligned_indexed", "aligned_closed"}:
        from .aligned import AlignedConfig
        if not isinstance(cfg, AlignedConfig):
            raise TypeError("aligned algorithm requires AlignedConfig")
    elif not isinstance(cfg, Config):
        raise TypeError("reference algorithm requires Config")
    if not isinstance(recover_invalid_keys, bool):
        raise TypeError("recover_invalid_keys must be a boolean")
    if not 1 <= workers <= 32:
        raise ValueError("workers must be between 1 and 32")
    source = source.resolve(strict=True)
    output = output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("output must be outside the source corpus")
    paths = discover(source)
    discovered_count = len(paths)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        # Content-independent deterministic cohort; do not choose early alphabet only.
        paths = sorted(paths, key=lambda p: sha256(p.relative_to(source).as_posix().encode()).hexdigest())[:limit]
    if not paths:
        raise ValueError("source contains no MIDI files")
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".build.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"build lock exists: {lock}; check its PID before removing a stale lock") from exc
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    try:
        cfg_dict = asdict(cfg)
        frozen_code = {p.name:p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))}
        code = digest({name:sha256(payload).hexdigest() for name,payload in frozen_code.items()})
        run_key = digest({"config":cfg_dict, "code":code, "version":__version__,
                          "export":export, "percussion":percussion,
                          "algorithm":algorithm, "recover_invalid_keys":recover_invalid_keys})
        config_path = output / "build_config.json"
        metadata = {"version":__version__, "config":cfg_dict, "code_sha256":code, "run_key":run_key,
                    "python":platform.python_version(), "percussion":percussion, "export":export,
                    "algorithm":algorithm, "recover_invalid_keys":recover_invalid_keys,
                    "discovered_source_files":discovered_count, "cohort_limit":limit,
                    "selected_source_files":len(paths)}
        if config_path.exists() and json.loads(config_path.read_text()).get("run_key") != run_key:
            raise ValueError("output has another code/config fingerprint; choose a new output directory")
        try:
            metadata["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            metadata["git_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        except subprocess.CalledProcessError:
            metadata["git_head"] = None
        atomic_json(config_path, metadata)
        snapshot = output / "provenance" / "samuged"
        snapshot.mkdir(parents=True, exist_ok=True)
        for name, payload in frozen_code.items():
            (snapshot / name).write_bytes(payload)
        for name in ("pyproject.toml", "requirements-research.lock"):
            project_file = Path(__file__).parent.parent / name
            if project_file.exists():
                shutil.copyfile(project_file, snapshot.parent / name)
        tasks = [(str(p), p.relative_to(source).as_posix(), str(output), cfg_dict, run_key,
                  export, percussion, algorithm, recover_invalid_keys) for p in paths]
        records = []
        started = time.monotonic()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for record in pool.map(_work, tasks, chunksize=4):
                records.append(record)
                if len(records) % 100 == 0 or len(records) == len(tasks):
                    print(canonical_json({"processed":len(records), "total":len(tasks),
                          "errors":sum(r["status"] == "error" for r in records),
                          "elapsed_seconds":round(time.monotonic()-started, 1)}), flush=True)
        metadata["wall_seconds"] = round(time.monotonic()-started, 3)
        return finalize(records, output, metadata)
    finally:
        lock.unlink(missing_ok=True)
