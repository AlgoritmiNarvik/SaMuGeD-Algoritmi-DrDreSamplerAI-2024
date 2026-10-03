from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shutil

import mido
import pytest

from samuged import __version__
from samuged.aligned import AlignedConfig
from samuged.audit import audit
from samuged.audit_alignment import (
    EXPECTED_MATCHER_FLAGS,
    validate_aligned_config,
    verify_alignment,
)
from samuged.dataset import (
    _work,
    atomic_json,
    canonical_json,
    code_digest,
    digest,
    file_digest,
    finalize,
)
from samuged.midi import Note


PPQ = 480
PITCHES = [60, 62, 65, 64, 67, 65, 62, 60]
ONSETS = [0.0, 0.75, 1.5, 2.25, 3.0, 3.75, 4.5, 5.25]


def _notes(start: float, pitches: list[int], onsets: list[float]) -> list[Note]:
    return [
        Note(
            round((start + onset) * PPQ),
            round((start + onset + 0.4) * PPQ),
            pitch,
            90,
        )
        for pitch, onset in zip(pitches, onsets)
    ]


def _valid_alignment() -> tuple[list[Note], list[Note], dict, dict]:
    prototype = _notes(4.0, PITCHES, ONSETS)
    candidate_pitches = [pitch + 5 for pitch in PITCHES]
    candidate_pitches.insert(4, 71)
    candidate_onsets = list(ONSETS)
    candidate_onsets.insert(4, 2.7)
    candidate = _notes(16.0, candidate_pitches, candidate_onsets)
    pairs = [[index, index] for index in range(4)] + [
        [index, index + 1] for index in range(4, 8)
    ]
    occurrence = {
        "start_tick": candidate[0].start,
        "end_tick": max(note.end for note in candidate),
        "note_index": 8,
        "note_count": 9,
        "transpose_semitones": 5,
        "similarity": round(0.7 * (1 - 1 / 9) + 0.2 + 0.1, 8),
        "edit_count": 1,
        "inserted_note_indices": [4],
        "deleted_prototype_note_indices": [],
        "substituted_note_pairs": [],
        "matched_note_pairs": pairs,
        "max_timing_error_beats": 0.0,
        "max_duration_error_beats": 0.0,
        "source_verified": True,
    }
    return prototype, candidate, occurrence, asdict(AlignedConfig())


def _write_aligned_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(type=0, ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (0, 0, mido.MetaMessage("key_signature", key="C", time=0))
    ]
    variants = [
        (4.0, list(PITCHES), list(ONSETS)),
        (
            16.0,
            [pitch + 5 for pitch in PITCHES[:4]]
            + [71]
            + [pitch + 5 for pitch in PITCHES[4:]],
            ONSETS[:4] + [2.7] + ONSETS[4:],
        ),
        (28.0, list(PITCHES), list(ONSETS)),
    ]
    for start, pitches, onsets in variants:
        for note in _notes(start, pitches, onsets):
            events.append(
                (
                    note.start,
                    1,
                    mido.Message(
                        "note_on", note=note.pitch, velocity=note.velocity, time=0
                    ),
                )
            )
            events.append(
                (
                    note.end,
                    0,
                    mido.Message("note_off", note=note.pitch, velocity=0, time=0),
                )
            )
    previous = 0
    for tick, _priority, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = tick - previous
        previous = tick
        track.append(message)
    track.append(mido.MetaMessage("end_of_track", time=0))
    midi.save(path)
    source = path.read_bytes()
    valid_key = b"\xff\x59\x02\x00\x00"
    assert source.count(valid_key) == 1
    path.write_bytes(source.replace(valid_key, b"\xff\x59\x02\xff\xff", 1))


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows))


def _refresh_hash(output: Path, name: str) -> None:
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[
        "source_manifest_sha256" if name == "sources.jsonl" else "phrase_manifest_sha256"
    ] = file_digest(output / name)
    atomic_json(summary_path, summary)


def _replace_phrase(output: Path, phrase: dict) -> None:
    rows = _read_rows(output / "phrases.jsonl")
    rows = [phrase if row["phrase_id"] == phrase["phrase_id"] else row for row in rows]
    _write_rows(output / "phrases.jsonl", rows)
    sources = _read_rows(output / "sources.jsonl")
    source_columns = {
        "source_id",
        "source_sha256",
        "source_path",
        "artist_from_path",
        "title_from_path",
        "song_key",
        "split",
        "split_group",
        "ticks_per_beat",
        "source_split",
    }
    for source in sources:
        source["phrases"] = [
            {key: value for key, value in phrase.items() if key not in source_columns}
            if saved["phrase_id"] == phrase["phrase_id"]
            else saved
            for saved in source.get("phrases", [])
        ]
    _write_rows(output / "sources.jsonl", sources)
    _refresh_hash(output, "phrases.jsonl")
    _refresh_hash(output, "sources.jsonl")


def _assemble_aligned_output(path: Path, output: Path, algorithm: str) -> dict:
    cfg = AlignedConfig(min_notes=8, max_notes=9, top_k=10, max_candidates=30)
    config = asdict(cfg)
    code = code_digest()
    run_key = digest(
        {
            "config": config,
            "code": code,
            "version": __version__,
            "export": True,
            "percussion": False,
            "algorithm": algorithm,
            "recover_invalid_keys": True,
        }
    )
    record = _work(
        (
            str(path),
            "Artist/song.mid",
            str(output),
            config,
            run_key,
            True,
            False,
            algorithm,
            True,
        )
    )
    assert record["status"] == "ok", record
    metadata = {
        "version": __version__,
        "run_key": run_key,
        "config": config,
        "code_sha256": code,
        "export": True,
        "percussion": False,
        "algorithm": algorithm,
        "recover_invalid_keys": True,
    }
    atomic_json(output / "build_config.json", metadata)
    snapshot = output / "provenance" / "samuged"
    snapshot.mkdir(parents=True)
    package = Path(__file__).parents[1] / "samuged"
    for module in package.glob("*.py"):
        shutil.copyfile(module, snapshot / module.name)
    finalize([record], output, metadata)
    return record


@pytest.fixture(scope="session")
def aligned_audit_baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("aligned-audit-baseline")
    source, output = root / "source", root / "output"
    path = source / "Artist" / "song.mid"
    _write_aligned_source(path)
    record = _assemble_aligned_output(path, output, "aligned")
    assert record["metadata_repairs"]
    assert any(
        occurrence["note_count"] != phrase["note_count"]
        for phrase in record["phrases"]
        for occurrence in phrase["occurrences"]
    )
    result = audit(source, output, require_full=True, reextract=True)
    assert result["passed"], result["failures"]
    return source, output


@pytest.fixture
def aligned_audit_copy(
    tmp_path: Path, aligned_audit_baseline: tuple[Path, Path]
) -> tuple[Path, Path]:
    baseline_source, baseline_output = aligned_audit_baseline
    source, output = tmp_path / "source", tmp_path / "output"
    shutil.copytree(baseline_source, source)
    shutil.copytree(baseline_output, output)
    return source, output


def test_independent_alignment_verifier_accepts_complete_source_partition() -> None:
    prototype, candidate, occurrence, config = _valid_alignment()

    assert verify_alignment(prototype, candidate, occurrence, PPQ, config) == []
    assert EXPECTED_MATCHER_FLAGS["terminal_gaps_allowed"] is False


def test_indexed_aligned_build_uses_same_independent_audit(
    tmp_path: Path,
) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    path = source / "Artist" / "song.mid"
    _write_aligned_source(path)
    record = _assemble_aligned_output(path, output, "aligned_indexed")

    result = audit(source, output, require_full=True, reextract=True)

    assert record["index_variant"] == "exact_first_cached_v1"
    assert result["passed"], result["failures"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda row: row["matched_note_pairs"].__setitem__(
                slice(2, 4), list(reversed(row["matched_note_pairs"][2:4]))
            ),
            "alignment is not strictly monotone",
        ),
        (
            lambda row: row.__setitem__("inserted_note_indices", []),
            "occurrence alignment partition is incomplete or overlapping",
        ),
        (
            lambda row: row["matched_note_pairs"].pop(0),
            "alignment has terminal gaps",
        ),
        (
            lambda row: row.__setitem__("transpose_semitones", 4),
            "substitution list differs from source pitches",
        ),
        (
            lambda row: row.__setitem__("similarity", 1.0),
            "alignment similarity differs from source",
        ),
        (
            lambda row: row.__setitem__("edit_count", 0),
            "edit count differs from alignment",
        ),
        (
            lambda row: row.__setitem__("max_timing_error_beats", 0.01),
            "max_timing_error_beats differs from source",
        ),
        (
            lambda row: row.__setitem__("max_duration_error_beats", 0.01),
            "max_duration_error_beats differs from source",
        ),
        (
            lambda row: row.__setitem__("note_count", 8),
            "occurrence note count differs from source",
        ),
    ],
)
def test_independent_alignment_verifier_rejects_corruption(mutation, expected) -> None:
    prototype, candidate, occurrence, config = _valid_alignment()
    mutation(occurrence)

    assert expected in verify_alignment(prototype, candidate, occurrence, PPQ, config)


def test_aligned_config_is_checked_without_constructing_detector() -> None:
    config = asdict(AlignedConfig())
    assert validate_aligned_config(config) == []
    config["max_edit_fraction"] = 0.5
    config["min_notes"] = 33
    config["max_notes"] = 20

    problems = validate_aligned_config(config)

    assert "aligned config max_edit_fraction is outside (0, 0.15]" in problems
    assert "aligned config min_notes exceeds max_notes" in problems


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("max_beats", 5.0, "alignment beat span is outside configured bounds"),
        ("max_gap_beats", 0.3, "alignment source gap exceeds configured bound"),
    ],
)
def test_independent_alignment_verifier_checks_source_window_bounds(
    field: str, value: float, reason: str
) -> None:
    prototype, candidate, occurrence, config = _valid_alignment()
    config[field] = value

    assert reason in verify_alignment(prototype, candidate, occurrence, PPQ, config)


def _phrase_with_insertion(output: Path) -> dict:
    for phrase in _read_rows(output / "phrases.jsonl"):
        if any(occurrence["inserted_note_indices"] for occurrence in phrase["occurrences"]):
            return phrase
    raise AssertionError("fixture has no aligned insertion")


def test_audit_rejects_interchanged_pairs_in_both_manifests(
    aligned_audit_copy: tuple[Path, Path],
) -> None:
    source, output = aligned_audit_copy
    phrase = _phrase_with_insertion(output)
    occurrence = next(o for o in phrase["occurrences"] if o["inserted_note_indices"])
    occurrence["matched_note_pairs"][2:4] = reversed(
        occurrence["matched_note_pairs"][2:4]
    )
    _replace_phrase(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert any(
        failure["reason"] == "alignment is not strictly monotone"
        for failure in result["failures"]
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "inserted_note_indices",
            [],
            "occurrence alignment partition is incomplete or overlapping",
        ),
        ("note_count", 128, "occurrence note count is outside aligned config bounds"),
    ],
)
def test_audit_rejects_alignment_partition_and_source_count_corruption(
    aligned_audit_copy: tuple[Path, Path], field: str, value, reason: str
) -> None:
    source, output = aligned_audit_copy
    phrase = _phrase_with_insertion(output)
    occurrence = next(o for o in phrase["occurrences"] if o["inserted_note_indices"])
    occurrence[field] = value
    _replace_phrase(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert any(failure["reason"] == reason for failure in result["failures"])


def test_audit_rejects_tampered_metadata_repair_receipt(
    aligned_audit_copy: tuple[Path, Path],
) -> None:
    source, output = aligned_audit_copy
    records = _read_rows(output / "sources.jsonl")
    records[0]["metadata_repairs"][0]["original_payload_hex"] = "0000"
    _write_rows(output / "sources.jsonl", records)
    _refresh_hash(output, "sources.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert any(
        failure["reason"] == "source metadata repairs differ from current loader"
        for failure in result["failures"]
    )


def test_audit_rejects_matcher_flags_and_recovery_summary_tampering(
    aligned_audit_copy: tuple[Path, Path],
) -> None:
    source, output = aligned_audit_copy
    phrase = _phrase_with_insertion(output)
    phrase["matcher_flags"]["terminal_gaps_allowed"] = True
    _replace_phrase(output, phrase)
    summary = json.loads((output / "summary.json").read_text())
    summary["metadata_repair_events"] += 1
    atomic_json(output / "summary.json", summary)

    result = audit(source, output)

    reasons = {failure["reason"] for failure in result["failures"]}
    assert "aligned matcher flags differ" in reasons
    assert "metadata_repair_events count or value mismatch" in reasons


def test_new_fingerprint_requires_both_algorithm_flags(
    aligned_audit_copy: tuple[Path, Path],
) -> None:
    source, output = aligned_audit_copy
    config_path = output / "build_config.json"
    config = json.loads(config_path.read_text())
    del config["recover_invalid_keys"]
    atomic_json(config_path, config)
    summary = json.loads((output / "summary.json").read_text())
    del summary["recover_invalid_keys"]
    atomic_json(output / "summary.json", summary)

    result = audit(source, output)

    assert not result["passed"]
    assert any(
        failure["reason"] == "build fingerprint fields missing"
        for failure in result["failures"]
    )
