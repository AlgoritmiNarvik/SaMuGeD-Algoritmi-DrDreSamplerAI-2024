from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts.prepare_publication import digest, parquet_views, repackage


try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover - depends on the selected test extra
    pq = None


requires_pyarrow = pytest.mark.skipif(
    pq is None, reason="publication dependency unavailable"
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))


def _metadata(tmp_path: Path) -> Path:
    metadata = tmp_path / "metadata-source"
    metadata.mkdir()
    _write_json(
        metadata / "release.json",
        {
            "algorithm": "aligned_closed",
            "phrase_rows": 1,
            "run_key": "fixture-run",
            "selection_replay": {"selection_count": 1},
        },
    )
    (metadata / "DATASET_CARD.md").write_text("private card\n", encoding="utf-8")
    (metadata / "review.html").write_text("private review\n", encoding="utf-8")
    (metadata / "SHA256SUMS").write_text("obsolete\n", encoding="utf-8")
    return metadata


def _archive_fixture(tmp_path: Path, metadata: Path) -> tuple[Path, bytes]:
    midi = b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0"
    archive = tmp_path / "source.tar.gz"
    members = [
        ("release.json", (metadata / "release.json").read_bytes()),
        ("DATASET_CARD.md", (metadata / "DATASET_CARD.md").read_bytes()),
        ("review.html", (metadata / "review.html").read_bytes()),
        ("midi/melodic/phrase.mid", midi),
        ("SHA256SUMS", b"old checksums\n"),
    ]
    _tar(archive, members)
    return archive, midi


def _read_archive(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        return {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }


def _checksum_rows(payload: bytes) -> dict[str, str]:
    rows = {}
    for line in payload.decode("utf-8").splitlines():
        value, name = line.split("  ", 1)
        rows[name] = value
    return rows


def test_repackage_preserves_midi_and_binds_new_archive_checksums(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    source_archive, midi = _archive_fixture(tmp_path, metadata)
    output = tmp_path / "public"
    output.mkdir()

    receipt = repackage(metadata, source_archive, output, "closed")

    destination = output / "archives" / "closed.tar.gz"
    sidecar = json.loads((output / "archives" / "closed.tar.gz.json").read_text())
    members = _read_archive(destination)
    checksums = _checksum_rows(members.pop("SHA256SUMS"))
    assert members["midi/melodic/phrase.mid"] == midi
    assert checksums == {
        name: sha256(payload).hexdigest() for name, payload in sorted(members.items())
    }
    assert receipt == sidecar
    assert receipt["sha256"] == digest(destination)
    assert receipt["original_archive_sha256"] == digest(source_archive)
    assert receipt["bytes"] == destination.stat().st_size
    assert receipt["members"] == len(members) + 1
    release = json.loads(members["release.json"])
    assert release["publication_status"] == "public_research_release"
    assert release["collection_license"] == "CC-BY-4.0"


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", b"x")],
        [("/absolute", b"x")],
        [("duplicate", b"a"), ("duplicate", b"b")],
    ],
)
def test_repackage_rejects_dangerous_or_duplicate_members(
    tmp_path: Path, members: list[tuple[str, bytes]]
) -> None:
    metadata = _metadata(tmp_path)
    archive = tmp_path / "source.tar.gz"
    _tar(archive, members)
    output = tmp_path / "public"
    output.mkdir()

    with pytest.raises(ValueError, match="unsafe or duplicate archive member"):
        repackage(metadata, archive, output, "closed")


@pytest.mark.parametrize(
    "extra_members",
    [
        [("midi/a.mid", b"a"), ("midi//a.mid", b"b")],
        [("midi/line\nbreak.mid", b"x")],
        [(r"midi\..\escape.mid", b"x")],
    ],
)
def test_repackage_rejects_noncanonical_or_checksum_ambiguous_names(
    tmp_path: Path, extra_members: list[tuple[str, bytes]]
) -> None:
    metadata = _metadata(tmp_path)
    archive = tmp_path / "source.tar.gz"
    required = [
        ("release.json", (metadata / "release.json").read_bytes()),
        ("DATASET_CARD.md", (metadata / "DATASET_CARD.md").read_bytes()),
        ("review.html", (metadata / "review.html").read_bytes()),
        ("SHA256SUMS", b"old checksums\n"),
    ]
    _tar(archive, required + extra_members)
    output = tmp_path / "public"
    output.mkdir()

    with pytest.raises(ValueError, match="unsafe or duplicate archive member"):
        repackage(metadata, archive, output, "closed")


def _phrase(kind: str, phrase_id: str, midi_path: str, midi_hash: str) -> dict:
    row = {
        "phrase_id": phrase_id,
        "source_id": f"source-{phrase_id}",
        "source_path": f"Artist/{phrase_id}.mid",
        "source_sha256": "1" * 64,
        "artist_from_path": "Artist",
        "title_from_path": "Title",
        "kind": kind,
        "family_id": f"family-{phrase_id}",
        "split": "train",
        "split_group": f"group-{phrase_id}",
        "part_name": "Piano" if kind == "melodic" else None,
        "start_tick": 0,
        "end_tick": 480,
        "ticks_per_beat": 480,
        "note_count": 2,
        "occurrence_count": 3,
        "program": 0 if kind == "melodic" else None,
        "duration_beats": 1.0,
        "recurrence_score": 0.8,
        "onsets_beats": [0.0, 0.5],
        "durations_beats": [0.25, 0.25],
        "pitches": [60, 64] if kind == "melodic" else [36, 42],
        "velocities": [80, 90],
        "occurrences": [
            {"start_tick": 0, "end_tick": 480},
            {"start_tick": 480, "end_tick": 960},
            {"start_tick": 960, "end_tick": 1440},
        ],
        "midi_path": midi_path,
        "midi_sha256": midi_hash,
    }
    if kind == "melodic":
        row["matcher_flags"] = {"source_verified": True}
    return row


def _dataset(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    dataset = tmp_path / "dataset"
    (dataset / "midi" / "melodic").mkdir(parents=True)
    (dataset / "midi" / "percussion").mkdir(parents=True)
    payloads = {
        "midi/melodic/m.mid": b"melodic-midi-bytes\x00\xff",
        "midi/percussion/p.mid": b"percussion-midi-bytes\x00\xfe",
    }
    for relative, payload in payloads.items():
        (dataset / relative).write_bytes(payload)
    rows = [
        _phrase(
            "melodic",
            "m",
            "midi/melodic/m.mid",
            sha256(payloads["midi/melodic/m.mid"]).hexdigest(),
        ),
        _phrase(
            "percussion",
            "p",
            "midi/percussion/p.mid",
            sha256(payloads["midi/percussion/p.mid"]).hexdigest(),
        ),
    ]
    (dataset / "phrases.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return dataset, payloads


@requires_pyarrow
def test_parquet_views_normalize_percussion_and_preserve_midi_bytes(
    tmp_path: Path,
) -> None:
    dataset, payloads = _dataset(tmp_path)
    output = tmp_path / "public"

    counts = parquet_views(dataset, output, "closed")

    assert counts == {"melodic": 1, "percussion": 1}
    melodic = pq.read_table(output / "data" / "closed_melodic" / "all.parquet")
    percussion = pq.read_table(output / "data" / "closed_percussion" / "all.parquet")
    assert melodic.schema == percussion.schema
    melodic_row = melodic.to_pylist()[0]
    percussion_row = percussion.to_pylist()[0]
    assert melodic_row["midi_bytes"] == payloads["midi/melodic/m.mid"]
    assert percussion_row["midi_bytes"] == payloads["midi/percussion/p.mid"]
    assert melodic_row["matcher_flags_json"] == '{"source_verified": true}'
    assert percussion_row["matcher_flags_json"] == "{}"
    assert percussion_row["program"] is None
    assert percussion_row["part_name"] is None


@requires_pyarrow
def test_parquet_views_rejects_midi_hash_mismatch(tmp_path: Path) -> None:
    dataset, _payloads = _dataset(tmp_path)
    rows = [json.loads(line) for line in (dataset / "phrases.jsonl").read_text().splitlines()]
    rows[0]["midi_sha256"] = "0" * 64
    (dataset / "phrases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="MIDI hash or path mismatch"):
        parquet_views(dataset, tmp_path / "public", "closed")


@requires_pyarrow
def test_parquet_views_rejects_midi_path_escape(tmp_path: Path) -> None:
    dataset, _payloads = _dataset(tmp_path)
    outside = tmp_path / "outside.mid"
    outside.write_bytes(b"outside")
    rows = [json.loads(line) for line in (dataset / "phrases.jsonl").read_text().splitlines()]
    rows[0]["midi_path"] = "../outside.mid"
    rows[0]["midi_sha256"] = sha256(outside.read_bytes()).hexdigest()
    (dataset / "phrases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="MIDI hash or path mismatch"):
        parquet_views(dataset, tmp_path / "public", "closed")
