"""Frozen note-domain diagnostic for the Theme Transformer annotations.

This adapter evaluates recurring-phrase outputs against three human note-label
views for six POP909 songs.  It is not a reproduction of the authors' reported
beat-domain evaluation and does not measure occurrence-family recovery.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import random
import time
from typing import Any, Iterable
from zipfile import ZipFile

import mido

from .aligned import AlignedConfig
from .aligned_indexed import extract_indexed
from .experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
)
from .midi import MidiSong, Note, Part
from .phrases import Config, extract, skyline


EVALUATION_VERSION = "theme-note-domain-v1"
OFFICIAL_SOURCE = "https://atosystem.github.io/ThemeTransformer/themeRetrieval.html"
SONG_IDS = ("065", "284", "310", "422", "449", "464")
ANNOTATORS = (0, 1, 2)
METHODS = ("reference_exact", "reference_transposed", "reference_approximate", "aligned_indexed")
VIEWS = ("top1", "top3")
BOOTSTRAP_SEED = 20261003
BOOTSTRAP_SAMPLES = 10_000
_DEFAULT_TEMPO = 500_000
_DEFAULT_METER = (4, 4)


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    path.write_text(payload + "\n", encoding="utf-8")


def _change_map(changes: Iterable[tuple], default: tuple) -> list[tuple]:
    by_tick = {int(row[0]): tuple(row[1:]) for row in sorted(changes)}
    by_tick.setdefault(0, default)
    return [(tick, *by_tick[tick]) for tick in sorted(by_tick)]


@dataclass(frozen=True)
class _ParsedAnnotation:
    ppq: int
    track_notes: tuple[tuple[Note, ...], ...]
    tempos: tuple[tuple[int, int], ...]
    meters: tuple[tuple[int, int, int], ...]
    midi_type: int


@dataclass
class ThemeCase:
    song_id: str
    song: MidiSong
    labels: dict[str, set[int]]
    archive_sha256: str
    annotation_member_sha256: dict[str, str]
    canonical_universe_sha256: str
    label_sha256: dict[str, str]
    metadata: dict[str, Any]
    baseline_input_coverage: list[dict[str, Any]]
    download_url: str

    def receipt_metadata(self) -> dict[str, Any]:
        return {
            "song_id": self.song_id,
            "archive_sha256": self.archive_sha256,
            "download_url": self.download_url,
            "annotation_member_sha256": self.annotation_member_sha256,
            "canonical_universe_sha256": self.canonical_universe_sha256,
            "label_sha256": self.label_sha256,
            "canonical_note_count": len(self.song.parts[0].notes),
            "metadata": self.metadata,
            "baseline_input_coverage": self.baseline_input_coverage,
        }


def _parse_annotation(data: bytes, *, member: str) -> _ParsedAnnotation:
    try:
        midi = mido.MidiFile(file=BytesIO(data), clip=False)
    except Exception as exc:
        raise ValueError(f"invalid annotation MIDI {member}: {exc}") from exc
    if midi.type not in (0, 1) or midi.ticks_per_beat <= 0:
        raise ValueError(f"unsupported MIDI framing in {member}")
    track_notes: list[tuple[Note, ...]] = []
    tempos: list[tuple[int, int]] = []
    meters: list[tuple[int, int, int]] = []
    for track_index, track in enumerate(midi.tracks):
        tick = 0
        active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
        notes: list[Note] = []
        for message in track:
            tick += message.time
            if message.type == "set_tempo":
                tempos.append((tick, message.tempo))
            elif message.type == "time_signature":
                meters.append((tick, message.numerator, message.denominator))
            if message.type == "note_on" and message.velocity > 0:
                active[(message.channel, message.note)].append((tick, message.velocity))
            elif message.type == "note_off" or (
                message.type == "note_on" and message.velocity == 0
            ):
                pending = active[(message.channel, message.note)]
                if not pending:
                    raise ValueError(
                        f"unmatched note end in {member}, track {track_index}"
                    )
                start, velocity = pending.popleft()
                if tick <= start:
                    raise ValueError(f"nonpositive note duration in {member}")
                notes.append(Note(start, tick, message.note, velocity))
        if any(pending for pending in active.values()):
            raise ValueError(f"unmatched note start in {member}, track {track_index}")
        track_notes.append(tuple(sorted(notes, key=_note_sort_key)))
    return _ParsedAnnotation(
        midi.ticks_per_beat,
        tuple(track_notes),
        tuple(_change_map(tempos, (_DEFAULT_TEMPO,))),
        tuple(_change_map(meters, _DEFAULT_METER)),
        midi.type,
    )


def _note_sort_key(note: Note) -> tuple[int, int, int, int]:
    return note.start, note.pitch, note.end, note.velocity


def note_identity(note: Note, ppq: int) -> tuple[Fraction, Fraction, int, int]:
    """Return the exact beat-normalized identity used for labels and joins."""
    if ppq <= 0:
        raise ValueError("PPQ must be positive")
    return Fraction(note.start, ppq), Fraction(note.end, ppq), note.pitch, note.velocity


def _identity_json(identity: tuple[Fraction, Fraction, int, int]) -> list[Any]:
    start, end, pitch, velocity = identity
    return [[start.numerator, start.denominator], [end.numerator, end.denominator], pitch, velocity]


def _identities(notes: Iterable[Note], ppq: int) -> list[tuple[Fraction, Fraction, int, int]]:
    return sorted(note_identity(note, ppq) for note in notes)


def _identity_hash(identities: Iterable[tuple[Fraction, Fraction, int, int]]) -> str:
    return sha256_json([_identity_json(identity) for identity in identities])


def _normalized_changes(rows: Iterable[tuple], ppq: int) -> list[list[Any]]:
    return [
        [[Fraction(row[0], ppq).numerator, Fraction(row[0], ppq).denominator], *row[1:]]
        for row in rows
    ]


def _annotation_member_hashes(audit_song: dict[str, Any]) -> dict[str, str]:
    return {
        row["name"]: row["sha256"]
        for row in audit_song["midi_members"]
        if "_Annotator_" in row["name"]
    }


def _archive_case(
    input_root: Path,
    song_id: str,
    audit_song: dict[str, Any],
    receipt: dict[str, Any],
) -> ThemeCase:
    archive_path = input_root / f"{song_id}.zip"
    archive_data = archive_path.read_bytes()
    archive_sha256 = _digest(archive_data)
    expected_archive = audit_song["archive_sha256"]
    if archive_sha256 != expected_archive or archive_sha256 != receipt["sha256"]:
        raise ValueError(f"archive hash mismatch for song {song_id}")
    if len(archive_data) != receipt["bytes"]:
        raise ValueError(f"archive byte count mismatch for song {song_id}")

    expected_members = _annotation_member_hashes(audit_song)
    parsed: dict[int, _ParsedAnnotation] = {}
    member_hashes: dict[str, str] = {}
    with ZipFile(BytesIO(archive_data)) as archive:
        names = set(archive.namelist())
        for annotator in ANNOTATORS:
            member = f"{song_id}/{song_id}_Annotator_{annotator}.mid"
            if member not in names or member not in expected_members:
                raise ValueError(f"missing audited annotation member {member}")
            data = archive.read(member)
            member_hashes[member] = _digest(data)
            if member_hashes[member] != expected_members[member]:
                raise ValueError(f"annotation member hash mismatch: {member}")
            parsed[annotator] = _parse_annotation(data, member=member)

        baseline_rows = []
        canonical_parsed = parsed[0]
        canonical_all = tuple(canonical_parsed.track_notes[1] + canonical_parsed.track_notes[2])
        canonical_identities = _identities(canonical_all, canonical_parsed.ppq)
        canonical_counter = Counter(canonical_identities)
        for suffix in ("Cl", "Cl_wo_NoteDur", "Cl_wo_PthSft", "Cm", "Cosiatec"):
            member = f"{song_id}/{song_id}_{suffix}.mid"
            if member not in names:
                raise ValueError(f"missing published baseline member {member}")
            data = archive.read(member)
            baseline = _parse_annotation(data, member=member)
            if len(baseline.track_notes) != 3:
                raise ValueError(f"unexpected track layout in {member}")
            identities = _identities(
                baseline.track_notes[1] + baseline.track_notes[2], baseline.ppq
            )
            counter = Counter(identities)
            shared = sum((canonical_counter & counter).values())
            baseline_rows.append({
                "method": suffix,
                "member": member,
                "member_sha256": _digest(data),
                "canonical_note_count": sum(canonical_counter.values()),
                "baseline_input_note_count": sum(counter.values()),
                "shared_exact_note_count": shared,
                "canonical_note_coverage": shared / sum(canonical_counter.values()),
                "baseline_note_coverage": shared / sum(counter.values()),
                "exact_universe_match": counter == canonical_counter,
            })

    if any(len(item.track_notes) != 3 for item in parsed.values()):
        raise ValueError(f"song {song_id} does not have metadata plus two musical tracks")
    if any(item.track_notes[0] for item in parsed.values()):
        raise ValueError(f"song {song_id} has notes in the metadata track")
    if any(not item.track_notes[1] or not item.track_notes[2] for item in parsed.values()):
        raise ValueError(f"song {song_id} has an empty annotation partition")
    if len({item.ppq for item in parsed.values()}) != 1:
        raise ValueError(f"annotator PPQ mismatch for song {song_id}")
    ppq = parsed[0].ppq
    unions = {
        annotator: Counter(_identities(item.track_notes[1] + item.track_notes[2], ppq))
        for annotator, item in parsed.items()
    }
    if any(unions[annotator] != unions[0] for annotator in ANNOTATORS[1:]):
        raise ValueError(f"annotator note universe mismatch for song {song_id}")
    if any(count != 1 for count in unions[0].values()):
        raise ValueError(
            f"song {song_id} contains duplicate exact note identities; source-index labels are ambiguous"
        )
    for annotator, item in parsed.items():
        first = Counter(_identities(item.track_notes[1], ppq))
        second = Counter(_identities(item.track_notes[2], ppq))
        if first & second:
            raise ValueError(f"annotation partitions overlap for song {song_id}, annotator {annotator}")

    canonical_notes = sorted(parsed[0].track_notes[1] + parsed[0].track_notes[2], key=_note_sort_key)
    canonical_keys = [note_identity(note, ppq) for note in canonical_notes]
    index_by_identity = {identity: index for index, identity in enumerate(canonical_keys)}
    labels: dict[str, set[int]] = {}
    label_hashes: dict[str, str] = {}
    for annotator, item in parsed.items():
        positives = {
            index_by_identity[note_identity(note, ppq)] for note in item.track_notes[2]
        }
        labels[str(annotator)] = positives
        label_hashes[str(annotator)] = sha256_json(sorted(positives))

    meters = {_identity_hash_for_json(_normalized_changes(item.meters, ppq)) for item in parsed.values()}
    if len(meters) != 1:
        raise ValueError(f"annotator meter metadata mismatch for song {song_id}")
    tempos = {
        str(annotator): _normalized_changes(item.tempos, ppq)
        for annotator, item in parsed.items()
    }
    metadata = {
        "ppq": ppq,
        "midi_types": {str(key): value.midi_type for key, value in parsed.items()},
        "meters_equal": True,
        "canonical_meters": [list(row) for row in parsed[0].meters],
        "tempos_equal": len({_identity_hash_for_json(value) for value in tempos.values()}) == 1,
        "annotator_tempos_beat_normalized": tempos,
        "canonical_metadata_source": f"{song_id}_Annotator_0.mid",
    }
    song = MidiSong(
        ticks_per_beat=ppq,
        parts=[Part(0, 0, 0, 0, "canonical_melody", False, canonical_notes)],
        tempos=[tuple(row) for row in parsed[0].tempos],
        meters=[tuple(row) for row in parsed[0].meters],
        warnings=[],
    )
    return ThemeCase(
        song_id,
        song,
        labels,
        archive_sha256,
        member_hashes,
        _identity_hash(canonical_keys),
        label_hashes,
        metadata,
        baseline_rows,
        receipt["url"],
    )


def _identity_hash_for_json(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_cases(input_root: Path, audit_path: Path) -> tuple[list[ThemeCase], dict[str, Any]]:
    """Load and independently verify the six audited archive inputs."""
    input_root = input_root.resolve(strict=True)
    audit_path = audit_path.resolve(strict=True)
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    if audit.get("schema_version") != "samuged-theme-annotation-input-audit-v1":
        raise ValueError("unsupported theme input audit")
    if tuple(audit["scope"]["songs"]) != SONG_IDS:
        raise ValueError("theme audit song cohort differs from frozen design")
    receipts_path = input_root / "download_receipts.json"
    receipts_bytes = receipts_path.read_bytes()
    if _digest(receipts_bytes) != audit["download_receipts"]["sha256"]:
        raise ValueError("download receipt hash differs from input audit")
    receipts = {row["song"]: row for row in json.loads(receipts_bytes)}
    audit_songs = {row["song_id"]: row for row in audit["songs"]}
    if set(receipts) != set(SONG_IDS) or set(audit_songs) != set(SONG_IDS):
        raise ValueError("input manifests do not contain exactly the six frozen songs")
    cases = [
        _archive_case(input_root, song_id, audit_songs[song_id], receipts[song_id])
        for song_id in SONG_IDS
    ]
    if any(row["exact_universe_match"] for case in cases for row in case.baseline_input_coverage):
        raise ValueError("published baseline unexpectedly shares the canonical full note universe")
    return cases, {
        "input_audit_path": audit_path.name,
        "input_audit_sha256": _digest(audit_bytes),
        "download_receipts_path": receipts_path.name,
        "download_receipts_sha256": _digest(receipts_bytes),
        "official_source_comparison_sha256": sha256_json(audit["official_source_comparison"]),
        "official_source_comparison": {
            key: audit["official_source_comparison"][key]
            for key in (
                "source_receipt_sha256",
                "source_track_selected",
                "canonical_track_selected",
                "all_official_melody_unions_exact_match_canonical",
                "all_official_melody_pitch_velocity_rank_matches",
                "interpretation",
            )
        },
    }


def classification_metrics(truth: set[int], predicted: set[int]) -> dict[str, Any]:
    """Exact set classification metrics with explicit empty-set behavior."""
    tp = len(truth & predicted)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = tp / len(predicted) if predicted else float(not truth)
    recall = tp / len(truth) if truth else float(not predicted)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def agreement(left: set[int], right: set[int], universe_size: int) -> dict[str, Any]:
    """Pairwise raw agreement and Cohen kappa over the complete note universe."""
    if universe_size <= 0 or any(index < 0 or index >= universe_size for index in left | right):
        raise ValueError("labels must belong to a nonempty note universe")
    both_positive = len(left & right)
    both_negative = universe_size - len(left | right)
    observed = (both_positive + both_negative) / universe_size
    left_rate = len(left) / universe_size
    right_rate = len(right) / universe_size
    expected = left_rate * right_rate + (1 - left_rate) * (1 - right_rate)
    kappa = None if math.isclose(expected, 1.0) else (observed - expected) / (1 - expected)
    return {"raw_agreement": observed, "cohen_kappa": kappa}


def prediction_indices(
    song: MidiSong,
    phrases: list[dict[str, Any]],
    *,
    top_n: int,
    onset_merge_beats: float,
    require_source_verified: bool,
) -> set[int]:
    """Join verified phrase occurrences back to exact canonical source notes."""
    if top_n not in (1, 3):
        raise ValueError("top_n must be 1 or 3")
    part = song.parts[0]
    stream = skyline(part, song.ticks_per_beat, onset_merge_beats)
    source_index = {id(note): index for index, note in enumerate(part.notes)}
    predicted: set[int] = set()
    for phrase in phrases[:top_n]:
        if phrase.get("part_index") != part.index:
            raise ValueError("prediction refers to a noncanonical part")
        for occurrence in phrase.get("occurrences", []):
            if require_source_verified and occurrence.get("source_verified") is not True:
                raise ValueError("aligned occurrence is not source verified")
            start = occurrence.get("note_index")
            count = occurrence.get("note_count", phrase.get("note_count"))
            if isinstance(start, bool) or not isinstance(start, int) or start < 0:
                raise ValueError("invalid occurrence source index")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError("invalid occurrence note count")
            selected = stream[start : start + count]
            if len(selected) != count:
                raise ValueError("occurrence exceeds the canonical skyline")
            if occurrence.get("start_tick") != selected[0].start:
                raise ValueError("occurrence start does not match source notes")
            if occurrence.get("end_tick") != max(note.end for note in selected):
                raise ValueError("occurrence end does not match source notes")
            predicted.update(source_index[id(note)] for note in selected)
    return predicted


def _configs() -> dict[str, dict[str, Any]]:
    return {
        "reference_exact": asdict(Config(mode="exact", top_k=3)),
        "reference_transposed": asdict(Config(mode="transposed", top_k=3)),
        "reference_approximate": asdict(Config(mode="approximate", top_k=3)),
        "aligned_indexed": asdict(AlignedConfig(top_k=3)),
    }


def _detect(method: str, song: MidiSong, config: dict[str, Any]) -> dict[str, Any]:
    if method.startswith("reference_"):
        return extract(song, Config(**config))
    if method == "aligned_indexed":
        return extract_indexed(song, AlignedConfig(**config))
    raise ValueError(f"unknown method {method}")


def _telemetry(found: dict[str, Any]) -> dict[str, Any]:
    flags = (
        "note_limit_reached",
        "window_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
        "candidate_limit_reached",
    )
    return {
        "search_limited": bool(found.get("search_limited")),
        "curation_truncated": bool(found.get("curation_truncated")),
        "candidate_count": found.get("candidate_count"),
        "part_limit_counts": {
            flag: sum(bool(part.get(flag, False)) for part in found.get("part_stats", []))
            for flag in flags
        },
        "part_stats": found.get("part_stats", []),
    }


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(probability * (len(ordered) - 1))))
    return ordered[index]


def bootstrap_song_macro(
    per_song: dict[str, dict[str, float]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float]]:
    """Cluster bootstrap songs, retaining all annotators within sampled songs."""
    if samples <= 0 or not per_song:
        raise ValueError("bootstrap requires songs and a positive sample count")
    songs = sorted(per_song)
    metrics = tuple(next(iter(per_song.values())))
    random_source = random.Random(seed)
    draws = {metric: [] for metric in metrics}
    for _ in range(samples):
        selected = [random_source.choice(songs) for _ in songs]
        for metric in metrics:
            draws[metric].append(sum(per_song[song][metric] for song in selected) / len(selected))
    return {
        metric: {
            "estimate": sum(per_song[song][metric] for song in songs) / len(songs),
            "ci95_low": _percentile(draws[metric], 0.025),
            "ci95_high": _percentile(draws[metric], 0.975),
        }
        for metric in metrics
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for method in METHODS:
        for view in VIEWS:
            selected = [row for row in rows if row["method"] == method and row["view"] == view]
            per_song = {}
            for song_id in SONG_IDS:
                song_rows = [row for row in selected if row["song_id"] == song_id]
                per_song[song_id] = {
                    metric: sum(row["metrics"][metric] for row in song_rows) / len(song_rows)
                    for metric in ("precision", "recall", "f1")
                }
            by_annotator = {
                str(annotator): {
                    metric: sum(
                        row["metrics"][metric]
                        for row in selected
                        if row["annotator"] == annotator
                    ) / len(SONG_IDS)
                    for metric in ("precision", "recall", "f1")
                }
                for annotator in ANNOTATORS
            }
            groups[f"{method}/{view}"] = {
                "song_count": len(SONG_IDS),
                "annotation_views": len(selected),
                "per_song_mean_over_annotators": per_song,
                "macro_over_songs": {
                    metric: sum(per_song[song][metric] for song in SONG_IDS) / len(SONG_IDS)
                    for metric in ("precision", "recall", "f1")
                },
                "macro_by_annotator": by_annotator,
                "cluster_bootstrap_by_song": bootstrap_song_macro(per_song),
            }
    return groups


def run(input_root: Path, audit_path: Path, output: Path) -> dict[str, Any]:
    """Run the frozen six-song diagnostic and write bound result artifacts."""
    cases, input_receipts = load_cases(input_root, audit_path)
    configs = _configs()
    case_receipts = [case.receipt_metadata() for case in cases]
    design = {
        "schema_version": EVALUATION_VERSION,
        "official_source": OFFICIAL_SOURCE,
        "cohort": list(SONG_IDS),
        "domain": "exact beat-normalized note identities from annotator-0 track union",
        "canonical_adapter": (
            "union annotator 0 tracks 1 and 2; one piano part, channel 0, "
            "program 0, canonical_melody name; annotator track identity removed"
        ),
        "annotation_views": "track 2 positives scored separately for each annotator",
        "primary_prediction": "all source notes in every verified occurrence of top-ranked family",
        "sensitivity_prediction": "union of all source notes in verified occurrences of top three families",
        "metric": "exact note classification precision, recall and F1",
        "inter_annotator_agreement": "pairwise raw note-label agreement and Cohen kappa",
        "bootstrap": {
            "unit": "song with all three annotators retained",
            "song_count": len(SONG_IDS),
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
            "interval": "percentile 95%",
        },
        "claim_boundary": (
            "local note-domain diagnostic; not the authors' beat-domain F1, not "
            "occurrence-family F1, corpus accuracy or musical memorability"
        ),
        "published_baseline_boundary": (
            "input note-universe coverage only because all 30 published prediction "
            "MIDIs differ from the canonical annotation universe"
        ),
        "input_receipts": input_receipts,
    }
    repository = Path(__file__).resolve().parent.parent
    required_files = [
        "samuged/__init__.py",
        "samuged/metadata_recovery.py",
        "samuged/evaluate_themes.py",
        "samuged/experiment.py",
        "samuged/midi.py",
        "samuged/phrases.py",
        "samuged/aligned.py",
        "samuged/aligned_indexed.py",
        "pyproject.toml",
        "requirements-research.lock",
    ]
    if not (repository / "requirements-research.lock").is_file():
        required_files.remove("requirements-research.lock")
    receipt = prepare_experiment(
        output,
        design=design,
        config={"detectors": configs, "top_k": 3},
        cases=case_receipts,
        required_files=required_files,
    )
    links = receipt_links(receipt)

    iaa = []
    for case in cases:
        for left, right in ((0, 1), (0, 2), (1, 2)):
            iaa.append({
                "song_id": case.song_id,
                "annotator_pair": [left, right],
                **agreement(case.labels[str(left)], case.labels[str(right)], len(case.song.parts[0].notes)),
            })

    detector_runs = []
    metric_rows = []
    for case in cases:
        for method in METHODS:
            started = time.monotonic()
            found = _detect(method, case.song, configs[method])
            runtime = time.monotonic() - started
            predictions = {}
            for view, top_n in (("top1", 1), ("top3", 3)):
                predicted = prediction_indices(
                    case.song,
                    found["phrases"],
                    top_n=top_n,
                    onset_merge_beats=configs[method]["onset_merge_beats"],
                    require_source_verified=method == "aligned_indexed",
                )
                predictions[view] = sorted(predicted)
                for annotator in ANNOTATORS:
                    metric_rows.append({
                        "song_id": case.song_id,
                        "method": method,
                        "view": view,
                        "annotator": annotator,
                        "truth_positive_notes": len(case.labels[str(annotator)]),
                        "predicted_positive_notes": len(predicted),
                        "metrics": classification_metrics(case.labels[str(annotator)], predicted),
                    })
            detector_runs.append({
                "song_id": case.song_id,
                "method": method,
                "runtime_seconds": runtime,
                "phrase_count": len(found["phrases"]),
                "phrase_output_sha256": sha256_json(found["phrases"]),
                "predicted_source_note_indices": predictions,
                "telemetry": _telemetry(found),
            })

    raw = {
        "schema_version": EVALUATION_VERSION,
        **links,
        "input_receipts": input_receipts,
        "cases": case_receipts,
        "inter_annotator_agreement": iaa,
        "detector_runs": detector_runs,
        "note_classification": metric_rows,
    }
    _write_json(output / "raw_results.json", raw)
    aggregate = {
        "schema_version": EVALUATION_VERSION,
        **links,
        "official_source": OFFICIAL_SOURCE,
        "song_count": len(cases),
        "annotation_views": len(cases) * len(ANNOTATORS),
        "method_views": _aggregate(metric_rows),
        "search_limited_runs": sum(run["telemetry"]["search_limited"] for run in detector_runs),
        "curation_truncated_runs": sum(run["telemetry"]["curation_truncated"] for run in detector_runs),
        "total_runtime_seconds": sum(run["runtime_seconds"] for run in detector_runs),
        "inter_annotator_agreement": iaa,
        "metadata_checks": {
            "all_note_universes_equal": True,
            "all_meters_equal": all(case.metadata["meters_equal"] for case in cases),
            "songs_with_annotator_tempo_disagreement": [
                case.song_id for case in cases if not case.metadata["tempos_equal"]
            ],
        },
        "published_baseline_input_coverage": [
            {"song_id": case.song_id, **row}
            for case in cases
            for row in case.baseline_input_coverage
        ],
        "detector_summary": {
            method: {
                "songs": len([row for row in detector_runs if row["method"] == method]),
                "runtime_seconds": sum(
                    row["runtime_seconds"] for row in detector_runs if row["method"] == method
                ),
                "search_limited_songs": sum(
                    row["telemetry"]["search_limited"]
                    for row in detector_runs if row["method"] == method
                ),
                "curation_truncated_songs": sum(
                    row["telemetry"]["curation_truncated"]
                    for row in detector_runs if row["method"] == method
                ),
            }
            for method in METHODS
        },
        "official_source_comparison": input_receipts["official_source_comparison"],
        "claim_boundary": design["claim_boundary"],
        "published_baseline_boundary": design["published_baseline_boundary"],
    }
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output, ("raw_results.json", "aggregate.json"))
    return aggregate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.input_root, arguments.audit, arguments.output), indent=2))
