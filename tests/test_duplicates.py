from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys

import mido
import pytest

from scripts import audit_duplicates as duplicate_module
from scripts.audit_duplicates import (
    DuplicateConfig,
    _cache_key,
    audit_duplicates,
    find_candidates,
)
from samuged.dataset import file_digest


def _write_melody(path: Path, pitches: list[int], gaps: list[int], scale: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    starts = [0]
    for gap in gaps:
        starts.append(starts[-1] + gap*scale)
    events = []
    for sequence, (start, pitch) in enumerate(zip(starts, pitches)):
        events.append((start, 1, sequence,
                       mido.Message("note_on", channel=0, note=pitch, velocity=90)))
        events.append((start+120*scale, 0, sequence,
                       mido.Message("note_off", channel=0, note=pitch, velocity=0)))
    previous = 0
    for tick, _priority, _sequence, message in sorted(events):
        track.append(message.copy(time=tick-previous))
        previous = tick
    midi.save(path)


def _manifest(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_transposed_and_uniformly_scaled_timing_is_a_candidate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    pitches = [55 + ((index*7 + index*index*3) % 28) for index in range(48)]
    gaps = [120 * (1 + ((index*5 + index*index) % 5)) for index in range(47)]
    _write_melody(source / "First" / "theme.mid", pitches, gaps)
    _write_melody(source / "Second" / "copy.mid", [pitch+5 for pitch in pitches], gaps, 2)
    manifest = tmp_path / "sources.jsonl"
    _manifest(manifest, [
        {"source_path": "First/theme.mid", "split": "train"},
        {"source_path": "Second/copy.mid", "split": "test"},
    ])

    output = tmp_path / "result.json"
    original_task = duplicate_module._fingerprint_task

    def assert_design_exists(task):
        assert (tmp_path / "result_provenance" / "design.json").is_file()
        return original_task(task)

    monkeypatch.setattr(duplicate_module, "_fingerprint_task", assert_design_exists)
    result = audit_duplicates(source, output, manifest=manifest,
                              cache=tmp_path / "cache")

    assert result["status_counts"] == {"ok": 2}
    assert result["candidate_counts"]["reported"] == 1
    candidate = result["candidates"][0]
    assert candidate["symbolic_near_duplicate"]
    assert not candidate["exact_bytes"]
    assert not candidate["exact_arrangement"]
    assert candidate["shared_rare_shingles"] >= 20
    assert not candidate["shared_pattern_candidate"]
    assert candidate["cross_split"]
    design_path = tmp_path / result["design"]
    receipt_path = tmp_path / result["fingerprint_receipt"]
    design = json.loads(design_path.read_text())
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    assert result["schema_version"] == 2
    assert result["design_sha256"] == file_digest(design_path)
    assert result["fingerprint_receipt_sha256"] == file_digest(receipt_path)
    assert result["manifest_sha256"] == file_digest(manifest)
    assert design["input_manifest_sha256"] == file_digest(manifest)
    assert design["method_key"] == result["method_key"]
    assert design["snapshot"]["files"]["scripts/audit_duplicates.py"]
    assert design["snapshot"]["files"]["samuged/midi.py"]
    assert len(receipts) == 2
    assert {row["method_key"] for row in receipts} == {result["method_key"]}
    assert all(not row["cache_hit"] for row in receipts)

    cached = audit_duplicates(source, tmp_path / "cached.json", manifest=manifest,
                              cache=tmp_path / "cache")
    assert cached["cache_hits"] == 2
    assert cached["cache_method_key_counts"] == {cached["method_key"]: 2}
    assert cached["cache_hit_method_key_counts"] == {cached["method_key"]: 2}
    assert cached["fingerprint_method_key_counts"] == {cached["method_key"]: 2}
    assert cached["candidates"] == result["candidates"]


def test_unrelated_monotone_scale_fragments_do_not_seed_candidates(tmp_path: Path) -> None:
    source = tmp_path / "source"
    gaps = [240] * 11
    _write_melody(source / "A" / "major.mid",
                  [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79], gaps)
    _write_melody(source / "B" / "chromatic.mid", list(range(48, 60)), gaps)

    result = audit_duplicates(source, tmp_path / "result.json", cache=tmp_path / "cache")

    assert result["candidate_counts"]["reported"] == 0
    assert result["generation"]["unique_shingles"] == 0


def test_exact_byte_copies_are_reported_without_symbolic_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    original = source / "A" / "short.mid"
    _write_melody(original, [60, 64, 62, 67], [240, 360, 240])
    copy = source / "B" / "short-copy.mid"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(original, copy)

    result = audit_duplicates(source, tmp_path / "result.json", cache=tmp_path / "cache")

    assert result["candidate_counts"]["exact_bytes"] == 1
    assert result["candidates"][0]["exact_bytes"]
    assert not result["candidates"][0]["symbolic_near_duplicate"]


def test_ubiquitous_shingles_and_pair_generation_are_bounded() -> None:
    fingerprints = [
        {"status": "ok", "source_path": f"Artist {index}/song.mid",
         "source_sha256": f"hash-{index}", "musical_sha256": f"music-{index}",
         "shingles": ["common", f"unique-{index}"]}
        for index in range(20)
    ]
    cfg = replace(DuplicateConfig(), max_document_frequency=3,
                  max_document_fraction=1.0, max_generated_pairs=5)

    candidates, stats = find_candidates(fingerprints, cfg)

    assert candidates == []
    assert stats["ubiquitous_shingles_excluded"] == 1
    assert stats["pair_events_generated"] == 0


def test_four_shared_features_in_unrelated_long_sources_are_only_a_pattern() -> None:
    common = [f"common-{index}" for index in range(4)]
    fingerprints = [
        {"status": "ok", "source_path": "A/long.mid",
         "source_sha256": "hash-a", "musical_sha256": "music-a",
         "shingles": common + [f"a-{index}" for index in range(100)]},
        {"status": "ok", "source_path": "B/long.mid",
         "source_sha256": "hash-b", "musical_sha256": "music-b",
         "shingles": common + [f"b-{index}" for index in range(100)]},
    ]

    candidates, _stats = find_candidates(fingerprints, DuplicateConfig())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["shared_pattern_candidate"]
    assert not candidate["symbolic_near_duplicate"]
    assert candidate["shared_rare_shingles"] == 4
    assert candidate["containment"] < 0.04


def test_worker_count_is_capped_at_two(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="workers must be 1 or 2"):
        audit_duplicates(source, tmp_path / "result.json", workers=3)


@pytest.mark.parametrize(("field", "value"), [
    ("max_generated_pairs", 20_000_001),
    ("max_verified_pairs", 2_000_001),
    ("max_reported_candidates", 400_001),
])
def test_expanded_pair_limits_have_explicit_upper_bounds(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=f"{field} must not exceed"):
        DuplicateConfig(**{field: value})


def test_only_the_exact_method_key_is_reused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_melody(source / "A" / "theme.mid",
                  [60, 64, 61, 67, 62, 69, 63, 70], [120] * 7)
    cache = tmp_path / "cache"
    first = audit_duplicates(source, tmp_path / "first.json", cache=cache)
    receipt = json.loads((tmp_path / first["fingerprint_receipt"]).read_text().strip())
    current_path = cache / f"{_cache_key(receipt['source_sha256'], first['method_key'])}.json"
    cached = json.loads(current_path.read_text())
    legacy_key = "1" * 64
    cached["method_key"] = legacy_key
    legacy_path = cache / f"{_cache_key(cached['source_sha256'], legacy_key)}.json"
    legacy_path.write_text(json.dumps(cached), encoding="utf-8")
    current_path.unlink()

    second = audit_duplicates(source, tmp_path / "second.json", cache=cache)

    assert second["cache_hits"] == 0
    assert second["cache_method_key_counts"] == {second["method_key"]: 1}
    assert second["cache_hit_method_key_counts"] == {}
    assert second["fingerprint_method_key_counts"] == {second["method_key"]: 1}
    assert legacy_path.is_file()
    assert current_path.is_file()


def test_existing_output_or_provenance_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "result.json"
    output.write_text("do not replace", encoding="utf-8")

    with pytest.raises(ValueError, match="output already exists"):
        audit_duplicates(source, output)
    assert output.read_text() == "do not replace"

    output.unlink()
    (tmp_path / "result_provenance").mkdir()
    with pytest.raises(ValueError, match="provenance directory already exists"):
        audit_duplicates(source, output)


def test_cli_exposes_expanded_bounds_and_progress(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_melody(source / "A" / "theme.mid",
                  [60, 64, 61, 67, 62, 69, 63, 70], [120] * 7)
    output = tmp_path / "cli.json"

    completed = subprocess.run([
        sys.executable, "scripts/audit_duplicates.py",
        "--source", str(source), "--output", str(output),
        "--cache", str(tmp_path / "cache"),
        "--max-generated-pairs", "20000000",
        "--max-verified-pairs", "2000000",
        "--max-reported-candidates", "400000",
    ], cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True)

    result = json.loads(output.read_text())
    assert result["config"]["max_generated_pairs"] == 20_000_000
    assert result["config"]["max_verified_pairs"] == 2_000_000
    assert result["config"]["max_reported_candidates"] == 400_000
    assert '"stage":"fingerprinting"' in completed.stderr
    assert '"stage":"candidate_generation"' in completed.stderr


def test_optional_metadata_recovery_is_separate_from_strict_cache(tmp_path: Path) -> None:
    source = tmp_path / "source"
    original = source / "A" / "theme.mid"
    _write_melody(original, [60, 64, 61, 67, 62, 69, 63, 70], [120] * 7)
    midi = mido.MidiFile(original)
    midi.tracks[0].insert(0, mido.MetaMessage("key_signature", key="C", time=0))
    midi.save(original)
    valid = original.read_bytes()
    assert valid.count(bytes.fromhex("ff59020000")) == 1
    broken = source / "B" / "broken.mid"
    broken.parent.mkdir()
    broken.write_bytes(valid.replace(bytes.fromhex("ff59020000"), bytes.fromhex("ff59020800")))
    before = file_digest(broken)
    cache = tmp_path / "cache"

    strict = audit_duplicates(source, tmp_path / "strict.json", cache=cache)
    recovered = audit_duplicates(
        source, tmp_path / "recovered.json", cache=cache,
        cfg=DuplicateConfig(recover_invalid_keys=True),
    )

    assert strict["status_counts"] == {"ok": 1, "error": 1}
    assert recovered["status_counts"] == {"ok": 2}
    assert recovered["cache_hits"] == 0
    assert strict["method_key"] != recovered["method_key"]
    assert recovered["candidate_counts"]["exact_arrangement"] == 1
    assert recovered["metadata_recovered_files"] == 1
    assert recovered["metadata_recovered_events"] == 1
    receipts = [json.loads(line) for line in (tmp_path / recovered["fingerprint_receipt"]).read_text().splitlines()]
    repaired = next(row for row in receipts if row["source_path"] == "B/broken.mid")
    assert repaired["metadata_repairs"][0]["original_payload_hex"] == "0800"
    assert file_digest(broken) == before
    assert json.loads((tmp_path / recovered["design"]).read_text())["snapshot"]["files"]["samuged/metadata_recovery.py"]


def test_metadata_recovery_requires_boolean_config() -> None:
    with pytest.raises(ValueError, match="recover_invalid_keys must be boolean"):
        DuplicateConfig(recover_invalid_keys="false")
