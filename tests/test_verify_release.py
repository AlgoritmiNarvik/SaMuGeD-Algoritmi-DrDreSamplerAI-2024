from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

import mido
import pytest

from samuged.audit import audit
from samuged.dataset import atomic_json, build, canonical_json, file_digest
from samuged.phrases import Config
from scripts.audit_selection_sample import run_sample
from scripts.package_dataset import package
from scripts.screen_splits import screen
import scripts.verify_release as release_verifier
from scripts.verify_release import verify_release


def _write_repeating_midi(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for repetition in range(2):
        for index, interval in enumerate((0, 2, 5, 4, 7, 9, 5, 2)):
            gap = 1920 if repetition and index == 0 else 0
            track.append(
                mido.Message("note_on", note=60 + interval, velocity=80, time=gap)
            )
            track.append(mido.Message("note_off", note=60 + interval, time=240))
    midi.save(path)


def _audited_dataset(tmp_path: Path, *, unicode_path: bool = False) -> tuple[Path, Path]:
    source, dataset = tmp_path / "source", tmp_path / "dataset"
    relative = Path("artist\u0085name") / "song.mid" if unicode_path else Path("song.mid")
    _write_repeating_midi(source / relative)
    build(source, dataset, Config(lengths=(8,), mode="exact"), workers=1)
    result = audit(source, dataset, require_full=True)
    assert result["passed"], result["failures"]
    return source, dataset


def _screening(dataset: Path, root: Path) -> Path:
    summary = json.loads((dataset / "summary.json").read_text())
    report = {
        "manifest_sha256": summary["source_manifest_sha256"],
        "method_key": "test-method",
        "fingerprint_method_key_counts": {"test-method": summary["source_files"]},
        "candidates": [],
        "generation": {
            "pair_generation_limit_reached": False,
            "pair_verification_limit_reached": False,
            "candidate_report_limit_reached": False,
        },
    }
    report_path = root / "duplicate-report.json"
    atomic_json(report_path, report)
    output = root / "screening"
    screen(dataset, report_path, output)
    return output


def _refresh_metadata_checksum(release: Path, name: str) -> None:
    path = release / "SHA256SUMS"
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        _digest, relative = line.split("  ", 1)
        digest = file_digest(release / relative) if relative == name else _digest
        rows.append(f"{digest}  {relative}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _malicious_archive(
    source: Path, target: Path, *, member_name: str, duplicate: bool = False
) -> None:
    members: list[tuple[str, bytes]] = []
    with tarfile.open(source, "r:gz") as tar:
        for info in tar:
            assert info.isreg()
            stream = tar.extractfile(info)
            assert stream is not None
            members.append((info.name, stream.read()))
    payload = members[0][1] if duplicate else b"unsafe"
    name = members[0][0] if duplicate else member_name
    members.append((name, payload))
    with tarfile.open(target, "w:gz") as tar:
        for relative, data in members:
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    original_receipt = json.loads(
        source.with_suffix(source.suffix + ".json").read_text()
    )
    receipt = {
        **original_receipt,
        "archive": target.name,
        "sha256": file_digest(target),
        "bytes": target.stat().st_size,
        "members": len(members),
    }
    atomic_json(target.with_suffix(target.suffix + ".json"), receipt)


def _link_archive(source: Path, target: Path) -> None:
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(source, "r:gz") as tar:
        for info in tar:
            stream = tar.extractfile(info)
            assert stream is not None
            members.append((info, stream.read()))
    with tarfile.open(target, "w:gz") as tar:
        for index, (original, data) in enumerate(members):
            info = tarfile.TarInfo(original.name)
            if index == 0:
                info.type = tarfile.SYMTYPE
                info.linkname = members[1][0].name
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
                continue
            tar.addfile(info)
    original_receipt = json.loads(
        source.with_suffix(source.suffix + ".json").read_text()
    )
    atomic_json(
        target.with_suffix(target.suffix + ".json"),
        {
            **original_receipt,
            "archive": target.name,
            "sha256": file_digest(target),
            "bytes": target.stat().st_size,
        },
    )


def test_verifies_real_tiny_metadata_and_archive_with_optional_evidence(tmp_path):
    source, dataset = _audited_dataset(tmp_path, unicode_path=True)
    replay = tmp_path / "selection-replay"
    run_sample(dataset, source, replay, count=None, workers=1, all_successful=True)
    screening = _screening(dataset, tmp_path)
    release = tmp_path / "release"
    package(
        dataset,
        release,
        archive=True,
        screening=screening,
        selection_replay=replay,
    )
    assert b"\xc2\x85" in (release / "sources.jsonl").read_bytes()

    report = verify_release(
        release, tmp_path / "verification.json", archive=tmp_path / "release.tar.gz"
    )

    assert report["status"] == "passed"
    assert report["scope"] == "metadata_and_archive"
    assert report["dataset"]["source_rows"] == 1
    assert report["dataset"]["phrase_rows"] > 0
    assert report["archive"]["midi_members"] == report["dataset"]["midi_payloads"]
    assert report["optional_evidence"]["selection_replay"]["failure_count"] == 0
    assert (
        report["optional_evidence"]["duplicate_screening"]["excluded_source_groups"]
        == 0
    )
    provenance = report["verifier_provenance"]
    assert provenance["authenticated_publisher"] is False
    assert provenance["status"] == "local_code_hashes_not_publisher_authentication"
    for name in (
        "scripts/verify_release.py",
        "scripts/package_dataset.py",
        "scripts/screen_splits.py",
        "samuged/experiment.py",
        "samuged/dataset.py",
    ):
        assert provenance["files"][name] == {
            "bytes": Path(name).stat().st_size,
            "sha256": file_digest(Path(name)),
        }
    assert provenance["closure_sha256"] == sha256(
        canonical_json(provenance["files"]).encode("utf-8")
    ).hexdigest()


def test_metadata_only_scope_and_output_protection(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)

    report = verify_release(release, tmp_path / "report.json")
    assert report["scope"] == "metadata_only"
    assert report["archive"] is None

    with pytest.raises(ValueError, match="already exists"):
        verify_release(release, tmp_path / "report.json")
    with pytest.raises(ValueError, match="outside the release"):
        verify_release(release, release / "report.json")


def test_rejects_tampered_metadata_bytes(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    (release / "DATASET_CARD.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="metadata SHA256 mismatch"):
        verify_release(release, tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()


def test_rejects_duplicate_metadata_checksum_entry(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    path = release / "SHA256SUMS"
    first = path.read_text(encoding="utf-8").splitlines()[0]
    with path.open("a", encoding="utf-8") as stream:
        stream.write(first + "\n")

    with pytest.raises(ValueError, match="duplicate metadata SHA256SUMS path"):
        verify_release(release, tmp_path / "report.json")


def test_rejects_self_consistent_but_stale_phrase_manifest(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    path = release / "phrases.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().split(b"\n") if line]
    rows[0]["part_name"] = "changed after audit"
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )
    _refresh_metadata_checksum(release, "phrases.jsonl")

    with pytest.raises(ValueError, match="audit binding mismatch: phrases.jsonl"):
        verify_release(release, tmp_path / "report.json")


def test_rejects_self_consistent_false_source_status_count(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    summary_path = release / "summary.json"
    audit_path = release / "audit.json"
    release_path = release / "release.json"
    summary = json.loads(summary_path.read_text())
    summary["source_status"]["ok"] += 1
    atomic_json(summary_path, summary)
    audit_report = json.loads(audit_path.read_text())
    audit_report["summary_sha256"] = file_digest(summary_path)
    atomic_json(audit_path, audit_report)
    release_record = json.loads(release_path.read_text())
    release_record["audit_scope"]["audit_sha256"] = file_digest(audit_path)
    atomic_json(release_path, release_record)
    for name in ("summary.json", "audit.json", "release.json"):
        _refresh_metadata_checksum(release, name)

    with pytest.raises(ValueError, match="summary source status counts mismatch"):
        verify_release(release, tmp_path / "report.json")


def test_rejects_self_consistent_false_audit_midi_count(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    audit_path = release / "audit.json"
    release_path = release / "release.json"
    audit_report = json.loads(audit_path.read_text())
    audit_report["counts"]["midi_verified"] += 1
    atomic_json(audit_path, audit_report)
    release_record = json.loads(release_path.read_text())
    release_record["audit_scope"]["audit_sha256"] = file_digest(audit_path)
    release_record["audit_scope"]["midi_excerpts_verified"] += 1
    atomic_json(release_path, release_record)
    for name in ("audit.json", "release.json"):
        _refresh_metadata_checksum(release, name)

    with pytest.raises(ValueError, match="audit verified MIDI count mismatch"):
        verify_release(release, tmp_path / "report.json")


def test_rejects_metadata_changed_during_verification(tmp_path, monkeypatch):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    original = release_verifier._verify_core

    def verify_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        (release / "DATASET_CARD.md").write_text("changed during verification")
        return result

    monkeypatch.setattr(release_verifier, "_verify_core", verify_then_mutate)
    with pytest.raises(ValueError, match="release metadata changed during verification"):
        verify_release(release, tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()


def test_rejects_archive_changed_during_verification(tmp_path, monkeypatch):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release, archive=True)
    archive = (tmp_path / "release.tar.gz").resolve()
    original = release_verifier.file_digest
    archive_calls = 0

    def changed_digest(path):
        nonlocal archive_calls
        result = original(path)
        if Path(path).resolve() == archive:
            archive_calls += 1
            if archive_calls == 2:
                return "0" * 64
        return result

    monkeypatch.setattr(release_verifier, "file_digest", changed_digest)
    with pytest.raises(ValueError, match="archive changed during verification"):
        verify_release(release, tmp_path / "report.json", archive=archive)
    assert archive_calls == 2
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize(
    ("member_name", "duplicate", "message"),
    [
        ("unused", True, "duplicate archive member"),
        ("../escape", False, "unsafe archive member path"),
    ],
)
def test_rejects_duplicate_or_unsafe_archive_members(
    tmp_path, member_name, duplicate, message
):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release, archive=True)
    malicious = tmp_path / ("duplicate.tar.gz" if duplicate else "unsafe.tar.gz")
    _malicious_archive(
        tmp_path / "release.tar.gz",
        malicious,
        member_name=member_name,
        duplicate=duplicate,
    )

    with pytest.raises(ValueError, match=message):
        verify_release(release, tmp_path / "report.json", archive=malicious)


def test_rejects_metadata_symlink_even_when_checksum_target_matches(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release)
    card = release / "DATASET_CARD.md"
    original = tmp_path / "card.md"
    original.write_bytes(card.read_bytes())
    card.unlink()
    card.symlink_to(original)

    with pytest.raises(ValueError, match="release contains a symlink"):
        verify_release(release, tmp_path / "report.json")


def test_rejects_archive_receipt_tampering(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release, archive=True)
    receipt_path = tmp_path / "release.tar.gz.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["members"] += 1
    atomic_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="archive receipt member count mismatch"):
        verify_release(
            release, tmp_path / "report.json", archive=tmp_path / "release.tar.gz"
        )


def test_rejects_archive_link_member(tmp_path):
    _source, dataset = _audited_dataset(tmp_path)
    release = tmp_path / "release"
    package(dataset, release, archive=True)
    linked = tmp_path / "linked.tar.gz"
    _link_archive(tmp_path / "release.tar.gz", linked)

    with pytest.raises(ValueError, match="archive member is not a regular file"):
        verify_release(release, tmp_path / "report.json", archive=linked)
