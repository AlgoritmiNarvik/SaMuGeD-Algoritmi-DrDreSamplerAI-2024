from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import mido
import pytest

import scripts.make_paired_review as paired_review
from scripts.make_paired_review import build_packet, validate_ratings


def _write_midi(path: Path, *, kind: str = "melodic") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    events = []
    pitches = (36, 42, 38, 46) if kind == "percussion" else (60, 62, 64, 65)
    for origin in (0, 960):
        for index, pitch in enumerate(pitches):
            start = origin + (index // 2) * 120 if kind == "percussion" else origin + index * 120
            events.extend(
                [
                    (start, 1, mido.Message("note_on", channel=9 if kind == "percussion" else 0, note=pitch, velocity=90)),
                    (start + 60, 0, mido.Message("note_off", channel=9 if kind == "percussion" else 0, note=pitch)),
                ]
            )
    previous = 0
    for tick, order, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = tick - previous
        previous = tick
        track.append(message)
    midi.save(path)
    return sha256(path.read_bytes()).hexdigest()


def _write_variant(root: Path, name: str, source_root: Path, source_ids: list[str], *, suffix: str = "", kind: str = "melodic") -> Path:
    dataset = root / name
    dataset.mkdir(parents=True)
    sources = []
    phrases = []
    for index, source_id in enumerate(source_ids):
        relative = f"artist/{source_id}.mid"
        midi_path = source_root / relative
        source_hash = _write_midi(midi_path, kind=kind)
        sources.append({"source_id": source_id, "source_path": relative, "source_sha256": source_hash, "split_group": f"group-{source_id}", "status": "ok"})
        phrases.append({
            "source_id": source_id,
            "source_path": relative,
            "source_sha256": source_hash,
            "split_group": f"group-{source_id}",
            "phrase_id": f"phrase-{source_id}-{suffix or name}",
            "kind": kind,
            "part_index": -1 if kind == "percussion" else 0,
            "start_tick": 0,
            "end_tick": 180 if kind == "percussion" else 420,
            "rank_in_file": 1,
            "recurrence_score": 0.8 + index / 100,
            "note_count": 4,
            "prototype_note_index": 0,
            "occurrences": [{"start_tick": 0, "end_tick": 180 if kind == "percussion" else 420, "note_index": 0}, {"start_tick": 960, "end_tick": 1140 if kind == "percussion" else 1380, "note_index": 4}],
        })
    (dataset / "sources.jsonl").write_text("\n".join(json.dumps(row) for row in sources) + "\n")
    (dataset / "phrases.jsonl").write_text("\n".join(json.dumps(row) for row in phrases) + "\n")
    config = {"algorithm": name, "run_key": f"run-{name}", "version": 1}
    (dataset / "build_config.json").write_text(json.dumps(config) + "\n")
    source_hash = sha256((dataset / "sources.jsonl").read_bytes()).hexdigest()
    phrase_hash = sha256((dataset / "phrases.jsonl").read_bytes()).hexdigest()
    config_hash = sha256((dataset / "build_config.json").read_bytes()).hexdigest()
    summary = {"algorithm": name, "run_key": config["run_key"], "source_files": len(sources), "source_manifest_sha256": source_hash, "phrase_manifest_sha256": phrase_hash}
    (dataset / "summary.json").write_text(json.dumps(summary) + "\n")
    summary_hash = sha256((dataset / "summary.json").read_bytes()).hexdigest()
    audit = {"passed": True, "failure_count": 0, "failures": [], "full_source_coverage_required": False, "source_files": len(sources), "run_key": config["run_key"], "source_manifest_sha256": source_hash, "phrase_manifest_sha256": phrase_hash, "summary_sha256": summary_hash, "build_config_sha256": config_hash}
    (dataset / "audit.json").write_text(json.dumps(audit) + "\n")
    return dataset


def _fixture(tmp_path: Path, count: int = 2, *, kind: str = "melodic") -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    ids = [f"s{index}" for index in range(count)]
    left = _write_variant(tmp_path, "left", source, ids, suffix="L", kind=kind)
    right = _write_variant(tmp_path, "right", source, ids, suffix="R", kind=kind)
    return source, left, right


def _refresh_bindings(dataset: Path) -> None:
    source_hash = sha256((dataset / "sources.jsonl").read_bytes()).hexdigest()
    phrase_hash = sha256((dataset / "phrases.jsonl").read_bytes()).hexdigest()
    config_hash = sha256((dataset / "build_config.json").read_bytes()).hexdigest()
    summary = json.loads((dataset / "summary.json").read_text())
    summary["source_manifest_sha256"] = source_hash
    summary["phrase_manifest_sha256"] = phrase_hash
    (dataset / "summary.json").write_text(json.dumps(summary) + "\n")
    summary_hash = sha256((dataset / "summary.json").read_bytes()).hexdigest()
    audit = json.loads((dataset / "audit.json").read_text())
    audit.update({"source_manifest_sha256": source_hash, "phrase_manifest_sha256": phrase_hash, "summary_sha256": summary_hash, "build_config_sha256": config_hash})
    (dataset / "audit.json").write_text(json.dumps(audit) + "\n")


def test_common_source_join_and_deterministic_balanced_side_order(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 3)
    first = build_packet(source, left, right, tmp_path / "one", count=3, seed="same")
    second = build_packet(source, left, right, tmp_path / "two", count=3, seed="same")
    assert first["packet"] == second["packet"]
    orders = [row["side_order"] for row in first["mapping"]["pairs"]]
    assert orders.count("AB") == 2
    assert orders.count("BA") == 1
    assert len({row["split_group"] for row in first["mapping"]["pairs"]}) == 3
    assert first["packet"]["config"]["scope"] == {"left": "pilot", "right": "pilot"}


def test_audit_binding_and_source_hash_are_required(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    audit_path = left / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["summary_sha256"] = "0" * 64
    audit_path.write_text(json.dumps(audit) + "\n")
    with pytest.raises(ValueError, match="stale"):
        build_packet(source, left, right, tmp_path / "audit-fail", count=1)

    source, left, right = _fixture(tmp_path / "hash", 1)
    midi = source / "artist/s0.mid"
    midi.write_bytes(midi.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="source hash mismatch"):
        build_packet(source, left, right, tmp_path / "hash-fail", count=1)


def test_variant_mutation_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, left, right = _fixture(tmp_path, 1)
    original = paired_review._read_jsonl

    def mutate_after_read(path: Path) -> list[dict]:
        rows = original(path)
        if path == left / "sources.jsonl":
            summary = left / "summary.json"
            summary.write_bytes(summary.read_bytes() + b" ")
        return rows

    monkeypatch.setattr(paired_review, "_read_jsonl", mutate_after_read)
    output = tmp_path / "mutation-fail"
    with pytest.raises(ValueError, match="changed while being read"):
        build_packet(source, left, right, output, count=1)
    assert not output.exists()


def test_metadata_repair_mismatch_is_rejected(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    for dataset in (left, right):
        rows = [json.loads(line) for line in (dataset / "sources.jsonl").read_text().splitlines()]
        rows[0]["metadata_repairs"] = []
        (dataset / "sources.jsonl").write_text(json.dumps(rows[0]) + "\n")
        _refresh_bindings(dataset)
    rows = [json.loads(line) for line in (right / "sources.jsonl").read_text().splitlines()]
    rows[0]["metadata_repairs"] = [{"field": "tempo", "action": "recovered"}]
    (right / "sources.jsonl").write_text(json.dumps(rows[0]) + "\n")
    _refresh_bindings(right)
    with pytest.raises(ValueError, match="metadata repair mismatch"):
        build_packet(source, left, right, tmp_path / "repair-fail", count=1)


def test_html_is_offline_blind_and_escapes_candidate_ids(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    for dataset in (left, right):
        rows = [json.loads(line) for line in (dataset / "phrases.jsonl").read_text().splitlines()]
        rows[0]["phrase_id"] = "bad</script><img src=x onerror=alert(1)>"
        (dataset / "phrases.jsonl").write_text(json.dumps(rows[0]) + "\n")
        _refresh_bindings(dataset)
    # The same candidate ID in both variants is valid for this escaping probe.
    result = build_packet(source, left, right, tmp_path / "html", count=1)
    rendered = (tmp_path / "html/review.html").read_text()
    assert "bad</script>" not in rendered
    assert "\\u003c/script\\u003e" in rendered
    assert "<script src" not in rendered and "fetch(" not in rendered
    assert "algorithm" not in rendered
    assert result["packet"]["config"]["identical_pair_count"] == 1
    assert set(result["input_manifest"]["code_sha256"]) == {
        "scripts/make_paired_review.py",
        "scripts/make_review.py",
        "samuged/__init__.py",
        "samuged/drums.py",
        "samuged/metadata_recovery.py",
        "samuged/midi.py",
        "samuged/phrases.py",
    }


def test_identical_pair_count_uses_rendered_evidence_not_hidden_score(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    rows = [json.loads(line) for line in (right / "phrases.jsonl").read_text().splitlines()]
    rows[0]["recurrence_score"] = 0.123
    (right / "phrases.jsonl").write_text(json.dumps(rows[0]) + "\n")
    _refresh_bindings(right)
    result = build_packet(source, left, right, tmp_path / "identical", count=1)
    assert result["mapping"]["pairs"][0]["identical"] is True
    assert result["packet"]["config"]["identical_pair_count"] == 1


def test_svg_and_percussion_packet_preserve_source_hits_and_use_deterministic_kit_synthesis(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1, kind="percussion")
    result = build_packet(source, left, right, tmp_path / "drums", count=1, kind="percussion")
    prototype = result["packet"]["pairs"][0]["alternatives"]["A"]["snippets"][0]
    assert [(note["onset_beats"], note["pitch"]) for note in prototype["notes"]] == [
        (0.0, 36),
        (0.0, 42),
        (0.25, 38),
        (0.25, 46),
    ]
    rendered = (tmp_path / "drums/review.html").read_text()
    assert "svg.setAttribute('class','roll')" in rendered
    assert "setAttribute('class','grid')" in rendered
    assert "setAttribute('class','note')" in rendered
    assert ".className='roll'" not in rendered
    assert ".className='grid'" not in rendered
    assert ".className='note'" not in rendered
    assert "noiseSample(n.pitch,i)" in rendered
    assert "drumFrequency(n.pitch)" in rendered
    assert "Math.random" not in rendered


def test_valid_unicode_identity_is_preserved_and_unsafe_script_text_is_escaped(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    old_path = source / "artist/s0.mid"
    relative = "artist/Grüße-φ-\u2028.mid"
    new_path = source / relative
    old_path.rename(new_path)
    candidate_id = "候補-\u2029</script><svg onload=alert(1)>"
    for dataset in (left, right):
        source_rows = [json.loads(line) for line in (dataset / "sources.jsonl").read_text().splitlines()]
        phrase_rows = [json.loads(line) for line in (dataset / "phrases.jsonl").read_text().splitlines()]
        source_rows[0]["source_path"] = relative
        phrase_rows[0]["source_path"] = relative
        phrase_rows[0]["phrase_id"] = candidate_id
        (dataset / "sources.jsonl").write_text(json.dumps(source_rows[0], ensure_ascii=False) + "\n")
        (dataset / "phrases.jsonl").write_text(json.dumps(phrase_rows[0], ensure_ascii=False) + "\n")
        _refresh_bindings(dataset)
    result = build_packet(source, left, right, tmp_path / "unicode", count=1)
    mapping = json.loads((tmp_path / "unicode/blind_mapping.json").read_text())
    rendered = (tmp_path / "unicode/review.html").read_text()
    assert mapping["pairs"][0]["source_path"] == relative
    assert result["packet"]["pairs"][0]["candidate_ids"] == {"A": candidate_id, "B": candidate_id}
    assert candidate_id not in rendered
    assert "\\u2029\\u003c/script\\u003e" in rendered


def test_invalid_utf8_manifest_fails_closed_before_output(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 1)
    raw = b'{"source_id":"s0"}\xff\n'
    (left / "sources.jsonl").write_bytes(raw)
    source_hash = sha256(raw).hexdigest()
    summary = json.loads((left / "summary.json").read_text())
    summary["source_manifest_sha256"] = source_hash
    (left / "summary.json").write_text(json.dumps(summary) + "\n")
    audit = json.loads((left / "audit.json").read_text())
    audit["source_manifest_sha256"] = source_hash
    audit["summary_sha256"] = sha256((left / "summary.json").read_bytes()).hexdigest()
    (left / "audit.json").write_text(json.dumps(audit) + "\n")
    output = tmp_path / "invalid-utf8"
    with pytest.raises(ValueError, match="valid UTF-8"):
        build_packet(source, left, right, output, count=1)
    assert not output.exists()


def test_ratings_round_trip_preserves_unrated_nulls_and_rejects_tamper(tmp_path: Path) -> None:
    source, left, right = _fixture(tmp_path, 2)
    result = build_packet(source, left, right, tmp_path / "ratings", count=2)
    packet = result["packet"]
    rows = [{"review_id": pair["review_id"], "preference": None, "notes": None, "candidate_ids": pair["candidate_ids"]} for pair in packet["pairs"]]
    payload = {"schema_version": "samuged-paired-review-ratings-v1", "annotator_id": None, "packet_sha256": packet["packet_sha256"], "ratings": rows}
    assert validate_ratings(payload, packet) == {"row_count": 2, "rated_count": 0}
    rows[0]["preference"] = "not-a-choice"
    with pytest.raises(ValueError, match="invalid preference"):
        validate_ratings(payload, packet)
    rows[0]["preference"] = None
    rows.pop()
    with pytest.raises(ValueError, match="exactly one"):
        validate_ratings(payload, packet)
    payload["ratings"] = [{"review_id": pair["review_id"], "preference": None, "notes": None, "candidate_ids": pair["candidate_ids"]} for pair in packet["pairs"]]
    payload["annotator_id"] = {"unexpected": "object"}
    with pytest.raises(ValueError, match="annotator_id"):
        validate_ratings(payload, packet)
