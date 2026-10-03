"""Render source-verified melodic and percussion recurrence examples."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from hashlib import sha256
import json
from pathlib import Path
import sys
import textwrap
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from samuged.dataset import atomic_json
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    verify_completed_experiment,
)
from scripts.make_review import _file_sha256, _review_candidate, _source_path


VERSION = "recurrence-example-figures-v1"
SEED = "samuged-recurrence-figure-v1"
KINDS = ("melodic", "percussion")
PRINCIPAL_FILES = (
    "sources.jsonl",
    "phrases.jsonl",
    "summary.json",
    "build_config.json",
    "audit.json",
)
AUDIT_BINDINGS = {
    "source_manifest_sha256": "sources.jsonl",
    "phrase_manifest_sha256": "phrases.jsonl",
    "summary_sha256": "summary.json",
    "build_config_sha256": "build_config.json",
}
FIGURE_FILES = tuple(
    f"{kind}_recurrence.{suffix}" for kind in KINDS for suffix in ("png", "svg")
)
RESULT_FILES = ("aggregate.json", "selection.json", *FIGURE_FILES)
REQUIRED_FILES = (
    "scripts/plot_recurrence_examples.py",
    "scripts/make_review.py",
    "samuged/dataset.py",
    "samuged/experiment.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "samuged/drums.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _hash_file(path: Path) -> dict[str, Any]:
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": _file_sha256(path)}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _dataset_inventory(dataset: Path) -> list[dict[str, Any]]:
    entries = []
    for name in PRINCIPAL_FILES:
        path = dataset / name
        if not path.is_file():
            raise FileNotFoundError(f"missing dataset artifact: {path}")
        entries.append(_hash_file(path))
    return entries


def _verify_dataset(dataset: Path, inventory: list[dict[str, Any]]) -> tuple[dict, dict]:
    hashes = {entry["path"]: entry["sha256"] for entry in inventory}
    audit = _load_object(dataset / "audit.json")
    if audit.get("passed") is not True or audit.get("failure_count") != 0 or audit.get("failures") != []:
        raise ValueError("dataset audit did not pass cleanly")
    if audit.get("full_source_coverage_required") is not True:
        raise ValueError("dataset audit lacks full source coverage")
    for field, filename in AUDIT_BINDINGS.items():
        if audit.get(field) != hashes[filename]:
            raise ValueError(f"dataset audit binding mismatch: {filename}")
    summary = _load_object(dataset / "summary.json")
    if summary.get("source_manifest_sha256") != hashes["sources.jsonl"]:
        raise ValueError("dataset summary source manifest binding mismatch")
    if summary.get("phrase_manifest_sha256") != hashes["phrases.jsonl"]:
        raise ValueError("dataset summary phrase manifest binding mismatch")
    return summary, audit


def distinct_occurrence_intervals(row: dict[str, Any]) -> list[tuple[int, int]]:
    """Return saved intervals in manifest order, with exact duplicates removed."""
    phrase_id = row.get("phrase_id", "unknown")
    occurrences = row.get("occurrences")
    if not isinstance(occurrences, list) or len(occurrences) < 3:
        raise ValueError(f"phrase {phrase_id} requires at least three saved occurrences")
    intervals: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError(f"phrase {phrase_id} has an invalid occurrence")
        start, end = occurrence.get("start_tick"), occurrence.get("end_tick")
        if (isinstance(start, bool) or not isinstance(start, int) or start < 0
                or isinstance(end, bool) or not isinstance(end, int) or end <= start):
            raise ValueError(f"phrase {phrase_id} has an invalid occurrence interval")
        interval = (start, end)
        if interval not in seen:
            intervals.append(interval)
            seen.add(interval)
    prototype = (row.get("start_tick"), row.get("end_tick"))
    if prototype not in seen:
        raise ValueError(f"phrase {phrase_id} prototype is absent from saved occurrences")
    if len(intervals) < 3:
        raise ValueError(f"phrase {phrase_id} requires three distinct saved occurrences")
    return intervals


def select_rows(rows: Iterable[dict[str, Any]], seed: str = SEED) -> dict[str, dict[str, Any]]:
    """Choose one eligible row per kind by a declared content hash rank."""
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a nonempty string")
    ranked: dict[str, list[tuple[str, str, dict[str, Any]]]] = {kind: [] for kind in KINDS}
    phrase_ids: set[str] = set()
    for row in rows:
        kind = row.get("kind")
        if kind not in ranked:
            continue
        phrase_id = row.get("phrase_id")
        if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_ids:
            raise ValueError("phrase manifest has an invalid or duplicate phrase ID")
        phrase_ids.add(phrase_id)
        occurrences = row.get("occurrences")
        if not isinstance(occurrences, list):
            raise ValueError(f"phrase {phrase_id} has invalid occurrences")
        if len(occurrences) < 3:
            continue
        try:
            distinct_occurrence_intervals(row)
        except ValueError as exc:
            if "requires three distinct saved occurrences" in str(exc):
                continue
            raise
        fields = (seed, kind, row.get("source_id"), row.get("family_id"), phrase_id)
        if any(not isinstance(value, str) or not value for value in fields):
            raise ValueError(f"phrase {phrase_id} lacks deterministic selection identity")
        rank = sha256("\0".join(fields).encode("utf-8")).hexdigest()
        ranked[kind].append((rank, phrase_id, row))
    selected = {}
    for kind in KINDS:
        if not ranked[kind]:
            raise ValueError(f"no eligible {kind} phrase has three distinct occurrences")
        selected[kind] = min(ranked[kind], key=lambda item: (item[0], item[1]))[2]
    return selected


def _read_selected_rows(path: Path, expected_hash: str) -> dict[str, dict[str, Any]]:
    digest = sha256()
    rows = []
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("phrase manifest row must be an object")
                rows.append(value)
    if digest.hexdigest() != expected_hash:
        raise ValueError("phrase manifest changed while selecting examples")
    return select_rows(rows)


def _read_source_records(
    path: Path, expected_hash: str, source_ids: set[str]
) -> dict[str, dict[str, Any]]:
    digest = sha256()
    selected: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            source_id = row.get("source_id")
            if not isinstance(source_id, str) or not source_id or source_id in seen:
                raise ValueError("source manifest has an invalid or duplicate source ID")
            seen.add(source_id)
            if source_id in source_ids:
                selected[source_id] = row
    if digest.hexdigest() != expected_hash:
        raise ValueError("source manifest changed while locating examples")
    if set(selected) != source_ids:
        raise ValueError("selected phrase references an unavailable source record")
    if any(row.get("status") != "ok" for row in selected.values()):
        raise ValueError("selected phrase references an unsuccessful source record")
    return selected


def _row_sha256(row: dict[str, Any]) -> str:
    payload = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def verified_example(
    row: dict[str, Any],
    source_record: dict[str, Any],
    source_root: Path,
    song_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the declared source and recover exactly three verified note slices."""
    distinct = distinct_occurrence_intervals(row)
    cache = {} if song_cache is None else song_cache
    candidate = _review_candidate(
        row,
        source_record,
        source_root,
        f"figure-{row['kind']}",
        cache,
    )
    if len(candidate["snippets"]) != 3:
        raise ValueError("source verifier did not recover three distinct occurrence slices")
    snippet_intervals = [
        (snippet["start_tick"], snippet["end_tick"])
        for snippet in candidate["snippets"]
    ]
    if len(set(snippet_intervals)) != 3 or any(interval not in distinct for interval in snippet_intervals):
        raise ValueError("source verifier returned unexpected occurrence coordinates")
    song = cache[row["source_id"]]
    source_end_tick = max(
        (note.end for part in song.parts for note in part.notes),
        default=max(end for _, end in distinct),
    )
    if source_end_tick < max(end for _, end in distinct):
        raise ValueError("saved occurrence extends beyond source note content")
    return {
        **candidate,
        "occurrence_count": row["occurrence_count"],
        "ticks_per_beat": song.ticks_per_beat,
        "source_end_tick": source_end_tick,
        "tempos": [
            {"tick": tick, "microseconds_per_beat": tempo, "bpm": 60_000_000 / tempo}
            for tick, tempo in song.tempos
        ],
        "all_occurrence_intervals": [
            {"start_tick": start, "end_tick": end} for start, end in distinct
        ],
    }


def _tempo_step(example: dict[str, Any]) -> tuple[list[float], list[float]]:
    ppq = example["ticks_per_beat"]
    end = example["source_end_tick"]
    changes = [row for row in example["tempos"] if row["tick"] <= end]
    if not changes:
        changes = [{"tick": 0, "bpm": 120.0}]
    x = [row["tick"] / ppq for row in changes]
    y = [row["bpm"] for row in changes]
    x.append(end / ppq)
    y.append(y[-1])
    return x, y


def _pitch_ticks(pitches: list[int]) -> list[int]:
    unique = sorted(set(pitches))
    if len(unique) <= 12:
        return unique
    step = max(1, len(unique) // 8)
    ticks = unique[::step]
    if ticks[-1] != unique[-1]:
        ticks.append(unique[-1])
    return ticks


def render_figure(example: dict[str, Any], method: str, output_base: Path) -> dict[str, Any]:
    """Render one timeline and three aligned source-note piano rolls."""
    kind = example["kind"]
    ppq = example["ticks_per_beat"]
    snippets = example["snippets"]
    pitch_values = [note["pitch"] for snippet in snippets for note in snippet["notes"]]
    low_pitch, high_pitch = min(pitch_values), max(pitch_values)
    maximum_beats = max(snippet["duration_beats"] for snippet in snippets)
    colors = ("#1769aa", "#d97706", "#6b7280")

    matplotlib.rcParams["svg.hashsalt"] = "samuged-recurrence-example-v1"
    fig = plt.figure(figsize=(11.0, 8.2), facecolor="white", layout="constrained")
    grid = fig.add_gridspec(5, 1, height_ratios=(1.15, 1.7, 1.7, 1.7, 0.3))
    timeline = fig.add_subplot(grid[0])
    source_end_beats = example["source_end_tick"] / ppq
    shown = {
        (snippet["start_tick"], snippet["end_tick"]): colors[index]
        for index, snippet in enumerate(snippets)
    }
    for interval in example["all_occurrence_intervals"]:
        pair = (interval["start_tick"], interval["end_tick"])
        start = pair[0] / ppq
        width = (pair[1] - pair[0]) / ppq
        timeline.add_patch(Rectangle(
            (start, 0.25), width, 0.5,
            facecolor=shown.get(pair, "#aab4c3"), edgecolor="white", linewidth=0.5,
        ))
    timeline.set_xlim(0, max(source_end_beats, 1))
    timeline.set_ylim(0, 1)
    timeline.set_yticks([])
    timeline.set_xlabel("Source position (quarter-note beats)")
    timeline.set_title(
        f"All {example['occurrence_count']} saved family occurrences on the source timeline",
        fontsize=10, loc="left", pad=4,
    )
    timeline.grid(axis="x", color="#d8dee8", linewidth=0.6)
    tempo_x, tempo_y = _tempo_step(example)
    minimum_tempo, maximum_tempo = min(tempo_y), max(tempo_y)
    if maximum_tempo == minimum_tempo:
        tempo_plot = [0.12 for _ in tempo_y]
    else:
        tempo_plot = [
            0.06 + 0.14 * (value - minimum_tempo) / (maximum_tempo - minimum_tempo)
            for value in tempo_y
        ]
    timeline.step(tempo_x, tempo_plot, where="post", color="#374151", alpha=0.65, linewidth=0.9)
    timeline.text(
        0.995,
        0.03,
        f"source tempo {minimum_tempo:.1f}–{maximum_tempo:.1f} BPM",
        transform=timeline.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        color="#374151",
    )
    timeline.legend(
        handles=[
            Patch(facecolor=colors[0], label="Prototype"),
            Patch(facecolor=colors[1], label="Displayed occurrence 2"),
            Patch(facecolor=colors[2], label="Displayed occurrence 3 / other saved"),
            Line2D([0], [0], color="#374151", linewidth=0.9, label="Source tempo"),
        ],
        loc="upper left", frameon=False, fontsize=7, ncol=3,
    )

    for index, snippet in enumerate(snippets):
        axis = fig.add_subplot(grid[index + 1])
        for note in snippet["notes"]:
            width = max(note["duration_beats"], maximum_beats / 1200)
            axis.add_patch(Rectangle(
                (note["onset_beats"], note["pitch"] - 0.38),
                width,
                0.76,
                facecolor=colors[index],
                edgecolor="white",
                linewidth=0.35,
            ))
        axis.set_xlim(0, maximum_beats)
        axis.set_ylim(low_pitch - 1, high_pitch + 1)
        axis.set_yticks(_pitch_ticks(pitch_values))
        axis.set_ylabel("MIDI pitch")
        axis.grid(axis="x", color="#e2e7ee", linewidth=0.6)
        axis.set_title(
            f"{snippet['label']}: source ticks [{snippet['start_tick']}, {snippet['end_tick']})",
            fontsize=9, loc="left", pad=3,
        )
        if index == len(snippets) - 1:
            axis.set_xlabel("Beats from occurrence start")

    fig.suptitle(f"{kind.capitalize()} recurrence example", fontsize=15, fontweight="bold")
    metadata = (
        f"Source: {example['source_path']}  |  source SHA256: {example['source_sha256'][:16]}…  |  "
        f"family: {example['family_id'][:16]}…\n"
        f"Occurrences: {example['occurrence_count']}  |  method: {method}  |  "
        "notes and tempo loaded from the hash-verified source MIDI; no perceptual-quality claim"
    )
    footer = fig.add_subplot(grid[4])
    footer.axis("off")
    footer.text(
        0,
        0.5,
        textwrap.fill(metadata, 150),
        fontsize=7.4,
        color="#374151",
        va="center",
    )

    png = output_base.with_suffix(".png")
    svg = output_base.with_suffix(".svg")
    fig.savefig(png, dpi=180, facecolor="white", metadata={"Software": VERSION})
    fig.savefig(
        svg,
        facecolor="white",
        metadata={"Creator": VERSION, "Date": None, "Title": f"{kind} recurrence example"},
    )
    plt.close(fig)
    return {
        "png": _hash_file(png),
        "svg": _hash_file(svg),
    }


def run(source: Path, dataset: Path, output: Path) -> dict[str, Any]:
    source = source.resolve(strict=True)
    dataset = dataset.resolve(strict=True)
    if not source.is_dir() or not dataset.is_dir():
        raise ValueError("source and dataset must be directories")
    inventory = _dataset_inventory(dataset)
    hashes = {entry["path"]: entry["sha256"] for entry in inventory}
    summary, audit = _verify_dataset(dataset, inventory)
    selected = _read_selected_rows(dataset / "phrases.jsonl", hashes["phrases.jsonl"])
    source_ids = {row["source_id"] for row in selected.values()}
    source_records = _read_source_records(
        dataset / "sources.jsonl", hashes["sources.jsonl"], source_ids
    )
    source_files = {}
    for source_id in sorted(source_ids):
        record = source_records[source_id]
        path = _source_path(source, record["source_path"])
        actual = _hash_file(path)
        if actual["sha256"] != record.get("source_sha256"):
            raise ValueError(f"source hash mismatch for {record['source_path']!r}")
        source_files[source_id] = {
            "path": record["source_path"],
            "bytes": actual["bytes"],
            "sha256": actual["sha256"],
        }
    method = f"{summary.get('algorithm')}/{summary.get('config', {}).get('mode', 'unspecified')}"
    cases = [
        {
            "kind": kind,
            "source_id": row["source_id"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_bytes": source_files[row["source_id"]]["bytes"],
            "phrase_id": row["phrase_id"],
            "family_id": row["family_id"],
            "phrase_row_sha256": _row_sha256(row),
            "occurrence_count": row["occurrence_count"],
            "occurrence_intervals": distinct_occurrence_intervals(row),
            "metadata_repairs": source_records[row["source_id"]].get("metadata_repairs", []),
        }
        for kind, row in sorted(selected.items())
    ]
    design = {
        "version": VERSION,
        "purpose": "source-verified scientific recurrence example figures",
        "selection": "minimum SHA256 rank independently by kind among rows with three distinct saved occurrences",
        "seed": SEED,
        "seed_sha256": sha256(SEED.encode("utf-8")).hexdigest(),
        "dataset": str(dataset),
        "source_root": str(source),
        "dataset_inventory": inventory,
        "dataset_audit_sha256": hashes["audit.json"],
        "dataset_audit_passed": audit["passed"],
        "result_artifacts": list(RESULT_FILES),
        "claim_boundary": "source-coordinate illustration only; no human quality or memorability claim",
    }
    config = {
        "method": method,
        "timeline_units": "quarter-note beats converted from exact source ticks and PPQ",
        "piano_roll_alignment": "occurrence start",
        "displayed_occurrences_per_kind": 3,
        "retain_midi_pitch_ids": True,
        "retain_simultaneous_percussion_strikes": True,
        "png_dpi": 180,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=cases,
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    song_cache: dict[str, Any] = {}
    examples = {
        kind: verified_example(row, source_records[row["source_id"]], source, song_cache)
        for kind, row in selected.items()
    }
    figure_hashes = {
        kind: render_figure(examples[kind], method, output / f"{kind}_recurrence")
        for kind in KINDS
    }
    selection = {
        **links,
        "version": VERSION,
        "seed": SEED,
        "method": method,
        "examples": {
            kind: {
                "phrase_row": selected[kind],
                "phrase_row_sha256": _row_sha256(selected[kind]),
                "source_file": source_files[selected[kind]["source_id"]],
                "metadata_repairs": source_records[selected[kind]["source_id"]].get("metadata_repairs", []),
                "source_verified_excerpt": examples[kind],
            }
            for kind in KINDS
        },
    }
    aggregate = {
        **links,
        "version": VERSION,
        "dataset": str(dataset),
        "source_root": str(source),
        "method": method,
        "dataset_audit_sha256": hashes["audit.json"],
        "dataset_bindings": {
            field: hashes[filename] for field, filename in AUDIT_BINDINGS.items()
        },
        "selection_seed": SEED,
        "selection_policy": design["selection"],
        "examples": {
            kind: {
                "source_id": selected[kind]["source_id"],
                "source_path": selected[kind]["source_path"],
                "source_sha256": selected[kind]["source_sha256"],
                "phrase_id": selected[kind]["phrase_id"],
                "family_id": selected[kind]["family_id"],
                "occurrence_count": selected[kind]["occurrence_count"],
                "displayed_intervals": [
                    [snippet["start_tick"], snippet["end_tick"]]
                    for snippet in examples[kind]["snippets"]
                ],
                "figure_files": figure_hashes[kind],
            }
            for kind in KINDS
        },
        "claim_boundary": "source-coordinate illustration only; no human quality or memorability claim",
    }
    atomic_json(output / "selection.json", selection)
    atomic_json(output / "aggregate.json", aggregate)
    if _dataset_inventory(dataset) != inventory:
        raise ValueError("dataset artifacts changed while rendering figures")
    for source_id, expected in source_files.items():
        path = _source_path(source, expected["path"])
        if _hash_file(path) != {"path": path.name, "bytes": expected["bytes"], "sha256": expected["sha256"]}:
            raise ValueError(f"selected source changed while rendering: {source_id}")
    complete_experiment(output)
    verify_completed_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="original source MIDI corpus")
    parser.add_argument("--dataset", type=Path, required=True, help="completed audited dataset")
    parser.add_argument("--output", type=Path, required=True, help="new figure experiment directory")
    args = parser.parse_args()
    result = run(args.source, args.dataset, args.output)
    print(json.dumps({
        "output": str(args.output),
        "method": result["method"],
        "examples": {
            kind: result["examples"][kind]["phrase_id"] for kind in KINDS
        },
    }, indent=2))


if __name__ == "__main__":
    main()
