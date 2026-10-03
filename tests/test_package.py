from hashlib import sha256
import json
from pathlib import Path
import shutil
import tarfile

import mido
import pytest

from samuged.audit import audit
from samuged.dataset import atomic_json, build, canonical_json, file_digest
from samuged.phrases import Config
from scripts.package_dataset import package, unique_views
from scripts.screen_splits import screen


def _write_repeating_midi(path: Path, base_pitch: int = 60) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for repetition in range(2):
        for index, interval in enumerate((0, 2, 5, 4, 7, 9, 5, 2)):
            gap = 1920 if repetition and index == 0 else 0
            track.append(
                mido.Message(
                    "note_on", note=base_pitch + interval, velocity=80, time=gap
                )
            )
            track.append(
                mido.Message("note_off", note=base_pitch + interval, time=240)
            )
    midi.save(path)


def _audited_dataset(tmp_path: Path) -> tuple[Path, Path, dict]:
    source, dataset = tmp_path / "source", tmp_path / "dataset"
    _write_repeating_midi(source / "song.mid")
    build(source, dataset, Config(lengths=(8,), mode="exact"), workers=1)
    result = audit(source, dataset, require_full=True)
    assert result["passed"], result["failures"]
    return source, dataset, result


def _screening_view(dataset: Path, root: Path) -> Path:
    summary = json.loads((dataset / "summary.json").read_text())
    report = {
        "manifest_sha256": summary["source_manifest_sha256"],
        "method_key": "test-method",
        "fingerprint_method_key_counts": {
            "test-method": summary["source_files"]
        },
        "candidates": [],
        "generation": {
            key: False
            for key in (
                "pair_generation_limit_reached",
                "pair_verification_limit_reached",
                "candidate_report_limit_reached",
            )
        },
    }
    report_path = root / "duplicate-report.json"
    atomic_json(report_path, report)
    screening = root / "screening"
    screen(dataset, report_path, screening)
    return screening


def test_unique_views_preserve_membership_and_preferred_split():
    base = {"kind": "melodic", "family_id": "same"}
    rows = [
        {**base, "source_id": "a", "phrase_id": "1", "split_group": "g1",
         "split": "train", "recurrence_score": .6},
        {**base, "source_id": "b", "phrase_id": "2", "split_group": "g2",
         "split": "overlap_excluded", "recurrence_score": .9},
        {**base, "source_id": "c", "phrase_id": "3", "split_group": "g1",
         "split": "train", "recurrence_score": .7},
    ]
    representatives, members = unique_views(rows)
    assert representatives[0]["phrase_id"] == "3"
    assert members[0]["phrase_ids"] == ["1", "2", "3"]
    assert members[0]["source_ids"] == ["a", "b", "c"]
    assert members[0]["phrase_count"] == 3
    assert members[0]["source_count"] == 3
    assert members[0]["split_group_count"] == 2
    assert unique_views(list(reversed(rows))) == (representatives, members)


def test_archive_checksums_are_complete_and_packaging_is_deterministic(tmp_path):
    _source, dataset, audit_result = _audited_dataset(tmp_path)
    for key, name in (
        ("source_manifest_sha256", "sources.jsonl"),
        ("phrase_manifest_sha256", "phrases.jsonl"),
        ("build_config_sha256", "build_config.json"),
        ("summary_sha256", "summary.json"),
    ):
        assert audit_result[key] == file_digest(dataset / name)
    first = package(dataset, tmp_path/"release1", archive=True)
    second = package(dataset, tmp_path/"release2", archive=True)
    assert first["archive_receipt"]["sha256"] == second["archive_receipt"]["sha256"]
    with tarfile.open(tmp_path/"release1.tar.gz") as tar:
        expected = dict(line.split("  ", 1)[::-1] for line in tar.extractfile("SHA256SUMS").read().decode().splitlines())
        assert set(expected) == set(tar.getnames()) - {"SHA256SUMS"}
        for name, digest in expected.items():
            assert sha256(tar.extractfile(name).read()).hexdigest() == digest
        assert first["midi_payloads"] == len([name for name in expected if name.endswith(".mid")]) > 0
        assert all(info.mtime == 0 and info.mode == 0o644 for info in tar.getmembers())
    row = json.loads((dataset/"phrases.jsonl").read_text().splitlines()[0])
    (dataset/row["midi_path"]).write_bytes(b"corruption after audit")
    with pytest.raises(ValueError, match="MIDI artifact hash mismatch"):
        package(dataset, tmp_path/"rejected")


def test_metadata_checksums_list_only_files_in_metadata_release(tmp_path):
    _source, dataset, _audit_result = _audited_dataset(tmp_path)
    release = tmp_path / "metadata-release"
    package(dataset, release)

    checksums = dict(
        line.split("  ", 1)[::-1]
        for line in (release / "SHA256SUMS").read_text().splitlines()
    )
    assert checksums
    assert all((release / name).is_file() for name in checksums)
    assert all(
        sha256((release / name).read_bytes()).hexdigest() == digest
        for name, digest in checksums.items()
    )
    assert not any(name.endswith(".mid") for name in checksums)


def test_package_distinguishes_artifact_audit_from_full_selection_replay(tmp_path):
    source, dataset, _ = _audited_dataset(tmp_path)
    ordinary = package(dataset, tmp_path / "ordinary")
    assert ordinary["algorithm"] == "reference"
    assert ordinary["audit_scope"]["full_source_coverage_required"] is True
    assert ordinary["audit_scope"]["selection_reextracted_for_all_successful_sources"] is False
    assert "did not repeat candidate generation" in (
        tmp_path / "ordinary" / "DATASET_CARD.md"
    ).read_text()

    result = audit(source, dataset, require_full=True, reextract=True)
    assert result["passed"]
    replayed = package(dataset, tmp_path / "replayed")
    assert replayed["audit_scope"]["selection_reextracted_for_all_successful_sources"] is True
    assert replayed["audit_scope"]["audit_sha256"] == file_digest(dataset / "audit.json")
    assert "re-extracted every successful source" in (
        tmp_path / "replayed" / "DATASET_CARD.md"
    ).read_text()


def test_package_rejects_audit_copied_from_different_corpus(tmp_path):
    first_source, first_dataset = tmp_path / "first-source", tmp_path / "first-dataset"
    second_source, second_dataset = tmp_path / "second-source", tmp_path / "second-dataset"
    _write_repeating_midi(first_source / "first.mid", 60)
    _write_repeating_midi(second_source / "different.mid", 61)
    config = Config(lengths=(8,), mode="exact")
    build(first_source, first_dataset, config, workers=1)
    build(second_source, second_dataset, config, workers=1)
    assert audit(first_source, first_dataset, require_full=True)["passed"]
    shutil.copyfile(first_dataset / "audit.json", second_dataset / "audit.json")
    first_summary = json.loads((first_dataset / "summary.json").read_text())
    second_summary = json.loads((second_dataset / "summary.json").read_text())
    assert first_summary["run_key"] == second_summary["run_key"]
    assert (
        first_summary["source_manifest_sha256"]
        != second_summary["source_manifest_sha256"]
    )

    with pytest.raises(ValueError, match="audit receipt does not match sources.jsonl"):
        package(second_dataset, tmp_path / "release")


def test_package_requires_complete_audit_binding(tmp_path):
    _source, dataset, _result = _audited_dataset(tmp_path)
    audit_path = dataset / "audit.json"
    receipt = json.loads(audit_path.read_text())
    del receipt["build_config_sha256"]
    audit_path.write_text(json.dumps(receipt))

    with pytest.raises(
        ValueError, match="audit receipt does not match build_config.json"
    ):
        package(dataset, tmp_path / "release")


@pytest.mark.parametrize("collision", ["archive", "receipt"])
def test_archive_collision_is_rejected_before_output_mutation(tmp_path, collision):
    _source, dataset, _result = _audited_dataset(tmp_path)
    output = tmp_path / "release"
    archive = tmp_path / "release.tar.gz"
    path = archive if collision == "archive" else tmp_path / "release.tar.gz.json"
    path.write_bytes(b"existing")

    with pytest.raises(ValueError, match="archive or archive receipt already exists"):
        package(dataset, output, archive=True)

    assert not output.exists()


def test_package_includes_independently_verified_screening_view(tmp_path):
    _source, dataset, _result = _audited_dataset(tmp_path)
    screening = _screening_view(dataset, tmp_path)

    result = package(dataset, tmp_path / "release", screening=screening)

    assert result["duplicate_screening"]["excluded_source_groups"] == 0
    assert (
        tmp_path / "release" / "views" / "duplicate_screening" / "summary.json"
    ).is_file()


def test_package_rejects_self_hashed_but_semantically_invalid_screening(tmp_path):
    _source, dataset, _result = _audited_dataset(tmp_path)
    screening = _screening_view(dataset, tmp_path)
    phrase_path = screening / "phrase_splits.jsonl"
    rows = [json.loads(line) for line in phrase_path.read_text().splitlines()]
    rows[0]["screened_split"] = "duplicate_excluded"
    phrase_path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )
    summary_path = screening / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["artifacts"]["phrase_splits.jsonl"] = file_digest(phrase_path)
    atomic_json(summary_path, summary)
    output = tmp_path / "release"

    with pytest.raises(ValueError, match="screening phrase mapping mismatch"):
        package(dataset, output, screening=screening)

    assert not output.exists()
