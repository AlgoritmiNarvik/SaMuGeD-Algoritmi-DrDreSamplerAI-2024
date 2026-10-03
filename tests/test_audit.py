from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil

import mido
import pytest

from samuged import __version__
from samuged.audit import audit, _matched_strikes, _drum_window_meter
from samuged.dataset import (
    _work,
    atomic_json,
    canonical_json,
    code_digest,
    digest,
    file_digest,
    finalize,
)
from samuged.phrases import Config
from samuged.midi import MidiSong


def _write_repeated_song(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    pitches = (60, 62, 65, 64, 67, 65, 62, 60, 64, 65, 69, 67)
    for repetition in range(3):
        for index, pitch in enumerate(pitches):
            delay = 24 + (2_880 if repetition and index == 0 else 0)
            track.append(
                mido.Message(
                    "note_on", channel=0, note=pitch, velocity=90, time=delay
                )
            )
            track.append(
                mido.Message(
                    "note_off", channel=0, note=pitch, velocity=0, time=216
                )
            )
    midi.save(path)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(f"{canonical_json(row)}\n" for row in rows), encoding="utf-8"
    )


def _refresh_manifest_hash(output: Path, name: str) -> None:
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    key = {"sources.jsonl": "source_manifest_sha256",
           "phrases.jsonl": "phrase_manifest_sha256"}[name]
    summary[key] = file_digest(output / name)
    atomic_json(summary_path, summary)


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _replace_phrase_in_both(output: Path, phrase: dict) -> None:
    phrase_rows = _rows(output / "phrases.jsonl")
    phrase_rows = [phrase if row["phrase_id"] == phrase["phrase_id"] else row
                   for row in phrase_rows]
    _write_jsonl(output / "phrases.jsonl", phrase_rows)
    source_rows = _rows(output / "sources.jsonl")
    for source_row in source_rows:
        source_row["phrases"] = [
            {key: value for key, value in phrase.items()
             if key not in {"source_id", "source_sha256", "source_path",
                            "artist_from_path", "title_from_path", "song_key",
                            "split", "split_group", "ticks_per_beat", "source_split"}}
            if saved["phrase_id"] == phrase["phrase_id"] else saved
            for saved in source_row.get("phrases", [])
        ]
    _write_jsonl(output / "sources.jsonl", source_rows)
    _refresh_manifest_hash(output, "phrases.jsonl")
    _refresh_manifest_hash(output, "sources.jsonl")


@pytest.fixture(scope="session")
def audit_baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("audit-baseline")
    source = root / "source"
    output = root / "output"
    midi_path = source / "Artist" / "song.mid"
    _write_repeated_song(midi_path)

    config = Config(lengths=(12,), mode="exact")
    code = code_digest()
    run_key = digest(
        {
            "config": asdict(config),
            "code": code,
            "version": __version__,
            "export": True,
            "percussion": False,
        }
    )
    record = _work(
        (
            str(midi_path),
            "Artist/song.mid",
            str(output),
            asdict(config),
            run_key,
            True,
            False,
        )
    )
    assert record["status"] == "ok"
    assert record["phrases"]

    metadata = {
        "version": __version__,
        "run_key": run_key,
        "config": asdict(config),
        "code_sha256": code,
        "export": True,
        "percussion": False,
    }
    atomic_json(output / "build_config.json", metadata)
    snapshot = output / "provenance" / "samuged"
    snapshot.mkdir(parents=True)
    package = Path(__file__).parents[1] / "samuged"
    for path in package.glob("*.py"):
        shutil.copyfile(path, snapshot / path.name)
    finalize([record], output, metadata)
    result = audit(source, output, require_full=True)
    assert result["passed"], result["failures"]
    return source, output


@pytest.fixture
def audit_copy(
    tmp_path: Path, audit_baseline: tuple[Path, Path]
) -> tuple[Path, Path]:
    baseline_source, baseline_output = audit_baseline
    source = tmp_path / "source"
    output = tmp_path / "output"
    shutil.copytree(baseline_source, source)
    shutil.copytree(baseline_output, output)
    return source, output


def _failure_reasons(result: dict) -> set[str]:
    return {failure["reason"] for failure in result["failures"]}


def test_strike_audit_does_not_steal_a_later_strikes_only_match() -> None:
    assert _matched_strikes([.08, .16], [0, .09], 1/12) == 2
    assert _matched_strikes([0, .2], [.1, .3], 1/12) == 0


def test_drum_grid_audit_handles_meter_resets_and_fractional_ticks():
    song = MidiSong(480, [], [(0, 500000)], [(0, 6, 8), (2880, 4, 4)], [])
    assert _drum_window_meter(song, 0, 1440, 1) == (6, 8)
    assert _drum_window_meter(song, 2880, 4800, 1) == (4, 4)
    assert _drum_window_meter(song, 1440, 4320, 2) is None
    assert _drum_window_meter(song, 3000, 4920, 1) is None
    tiny = MidiSong(1, [], [(0, 500000)], [(0, 3, 8)], [])
    assert _drum_window_meter(tiny, 2, 3, 1) == (3, 8)
    assert _drum_window_meter(tiny, 3, 5, 1) == (3, 8)
    assert _drum_window_meter(tiny, 3, 6, 1) is None


def test_drum_audit_rejects_consistently_forged_meter_metadata(tmp_path):
    from samuged.dataset import build
    source, output = tmp_path/'source', tmp_path/'output'
    source.mkdir()
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for index in range(64):
        track.append(mido.Message('note_on', channel=9, note=(36, 42, 38, 42)[index % 4],
                                  velocity=90, time=210 if index else 0))
        track.append(mido.Message('note_off', channel=9, note=(36, 42, 38, 42)[index % 4], time=30))
    midi.save(source/'kit.mid')
    build(source, output, Config(), workers=1, percussion=True)
    assert audit(source, output)['passed']
    phrase = _rows(output/'phrases.jsonl')[0]
    phrase['meter_numerator'] = 3
    _replace_phrase_in_both(output, phrase)
    result = audit(source, output)
    assert not result['passed']
    assert 'drum interval differs from source meter and bar grid' in _failure_reasons(result)


def test_audit_detects_corrupt_midi_artifact(audit_copy: tuple[Path, Path]) -> None:
    source, output = audit_copy
    phrase = json.loads(
        (output / "phrases.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    (output / phrase["midi_path"]).write_bytes(b"broken artifact")

    result = audit(source, output)

    assert not result["passed"]
    assert "MIDI hash mismatch" in _failure_reasons(result)


def test_audit_detects_false_occurrence_coordinates(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    phrase = _rows(output / "phrases.jsonl")[0]
    phrase["occurrences"][0]["start_tick"] += 1
    _replace_phrase_in_both(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert "occurrence coordinates differ from source" in _failure_reasons(result)


def test_audit_detects_source_hash_change(audit_copy: tuple[Path, Path]) -> None:
    source, output = audit_copy
    source_path = source / "Artist" / "song.mid"
    source_path.write_bytes(source_path.read_bytes() + b"\x00")

    result = audit(source, output)

    assert not result["passed"]
    assert "source hash mismatch" in _failure_reasons(result)


def test_audit_detects_family_split_conflict(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    manifest = output / "phrases.jsonl"
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    conflicting = dict(rows[0])
    conflicting["phrase_id"] = f"{conflicting['phrase_id']}-conflict"
    conflicting["split"] = "test" if conflicting["split"] != "test" else "train"
    rows.append(conflicting)
    _write_jsonl(manifest, rows)
    _refresh_manifest_hash(output, "phrases.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert "canonical family crosses splits" in _failure_reasons(result)


def test_audit_detects_phrase_outside_source_membership(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    rows = _rows(output / "phrases.jsonl")
    injected = dict(rows[0])
    injected["phrase_id"] = "0" * 32
    injected["source_id"] = "f" * 24
    rows.append(injected)
    _write_jsonl(output / "phrases.jsonl", rows)
    _refresh_manifest_hash(output, "phrases.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert "phrase references unknown source ID" in _failure_reasons(result)
    assert "phrase membership differs from source records" in _failure_reasons(result)


def test_audit_detects_source_path_escape(audit_copy: tuple[Path, Path]) -> None:
    source, output = audit_copy
    records = _rows(output / "sources.jsonl")
    records[0]["source_path"] = "../../outside.mid"
    _write_jsonl(output / "sources.jsonl", records)
    _refresh_manifest_hash(output, "sources.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert "source path escapes source root" in _failure_reasons(result)


def test_audit_detects_reassigned_split_even_when_record_is_consistent(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    records = _rows(output / "sources.jsonl")
    records[0]["split"] = "test" if records[0]["split"] != "test" else "train"
    _write_jsonl(output / "sources.jsonl", records)
    _refresh_manifest_hash(output, "sources.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert "split differs from recomputed assignment" in _failure_reasons(result)


def test_audit_detects_summary_count_tamper(audit_copy: tuple[Path, Path]) -> None:
    source, output = audit_copy
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    summary["phrase_counts"]["melodic"] += 1
    atomic_json(output / "summary.json", summary)

    result = audit(source, output)

    assert not result["passed"]
    assert "phrase_counts count or value mismatch" in _failure_reasons(result)


def test_audit_detects_run_key_not_derived_from_build_inputs(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    config = json.loads((output / "build_config.json").read_text(encoding="utf-8"))
    config["run_key"] = "substituted"
    atomic_json(output / "build_config.json", config)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    summary["run_key"] = "substituted"
    atomic_json(output / "summary.json", summary)

    result = audit(source, output)

    assert not result["passed"]
    assert "run key differs from build inputs" in _failure_reasons(result)


def test_audit_detects_code_snapshot_tamper(audit_copy: tuple[Path, Path]) -> None:
    source, output = audit_copy
    snapshot = output / "provenance" / "samuged" / "audit.py"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n# changed\n",
                        encoding="utf-8")

    result = audit(source, output)

    assert not result["passed"]
    assert "code fingerprint mismatch" in _failure_reasons(result)


def test_audit_detects_source_note_count_tamper(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    records = _rows(output / "sources.jsonl")
    records[0]["note_count"] += 1
    _write_jsonl(output / "sources.jsonl", records)
    _refresh_manifest_hash(output, "sources.jsonl")

    result = audit(source, output)

    assert not result["passed"]
    assert "source note count mismatch" in _failure_reasons(result)


def test_audit_detects_internal_artifact_tempo_change(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    phrase = _rows(output / "phrases.jsonl")[0]
    artifact = output / phrase["midi_path"]
    midi = mido.MidiFile(artifact, clip=False)
    end = midi.tracks[0][-1]
    assert end.type == "end_of_track" and end.time > 100
    end.time -= 100
    midi.tracks[0].insert(-1, mido.MetaMessage("set_tempo", tempo=400_000, time=100))
    midi.save(artifact)
    phrase["midi_sha256"] = file_digest(artifact)
    _replace_phrase_in_both(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert "export tempo map differs" in _failure_reasons(result)


def test_audit_detects_artifact_program_change(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    phrase = _rows(output / "phrases.jsonl")[0]
    artifact = output / phrase["midi_path"]
    midi = mido.MidiFile(artifact, clip=False)
    program = next(message for track in midi.tracks for message in track
                   if message.type == "program_change")
    program.program = (program.program + 1) % 128
    midi.save(artifact)
    phrase["midi_sha256"] = file_digest(artifact)
    _replace_phrase_in_both(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert "export program differs" in _failure_reasons(result)


def test_audit_detects_one_short_artifact_track(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    phrase = _rows(output / "phrases.jsonl")[0]
    artifact = output / phrase["midi_path"]
    midi = mido.MidiFile(artifact, clip=False)
    assert midi.tracks[0][-1].type == "end_of_track"
    assert midi.tracks[0][-1].time > 1
    midi.tracks[0][-1].time -= 1
    midi.save(artifact)
    phrase["midi_sha256"] = file_digest(artifact)
    _replace_phrase_in_both(output, phrase)

    result = audit(source, output)

    assert not result["passed"]
    assert "export track length differs from requested clip" in _failure_reasons(result)


def test_reextract_detects_score_tamper_copied_to_both_manifests(
    audit_copy: tuple[Path, Path],
) -> None:
    source, output = audit_copy
    phrase = _rows(output / "phrases.jsonl")[0]
    phrase["recurrence_score"] = round(phrase["recurrence_score"] + 0.01, 8)
    _replace_phrase_in_both(output, phrase)

    lightweight = audit(source, output)
    reextracted = audit(source, output, reextract=True)

    assert lightweight["passed"], lightweight["failures"]
    assert not reextracted["passed"]
    assert "re-extracted phrases differ" in _failure_reasons(reextracted)
