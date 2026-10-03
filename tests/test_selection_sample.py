from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import platform

import pytest

import scripts.audit_selection_sample as sample


def _rows() -> list[dict]:
    rows = []
    for index in range(10):
        rows.append({
            "source_id": f"source-{index}",
            "source_sha256": f"{index:064x}",
            "source_path": f"artist/{index}.mid",
            "source_bytes": 1,
            "status": "ok",
            "outcome": "matched",
            "metadata_repairs": [{"event": "repair"}] if index in {1, 8} else [],
            "search_limited": index in {2, 3, 5, 7},
        })
    rows.append({
        "source_id": "error",
        "source_sha256": "f" * 64,
        "status": "error",
        "outcome": "parse_error",
    })
    return rows


def test_selection_is_hash_ordered_reproducible_and_balanced() -> None:
    rows = _rows()
    selected_a, meta_a = sample._select_records(list(reversed(rows)), 6, seed=17)
    selected_b, meta_b = sample._select_records(rows, 6, seed=17)

    assert [row["source_id"] for row in selected_a] == [row["source_id"] for row in selected_b]
    assert meta_a == meta_b
    assert meta_a["strata_counts"]["metadata_recovered"] == 2
    assert meta_a["strata_counts"]["search_limited"] == 2
    assert meta_a["strata_counts"]["not_search_limited"] == 2
    assert all(row["status"] == "ok" for row in selected_a)


def test_seed_changes_selection_and_drum_limits_are_included() -> None:
    rows = _rows()
    first, _ = sample._select_records(rows, 6, seed=17)
    second, _ = sample._select_records(rows, 6, seed=18)
    assert [r["source_id"] for r in first] != [r["source_id"] for r in second]
    assert sample._limited({"search_limited": False, "drum_stats": {"search_limited": True}})


def test_run_one_accounts_for_detector_evidence_tampering(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "song.mid"
    data = b"midi fixture"
    path.write_bytes(data)
    record = {
        "source_id": "source",
        "source_path": "song.mid",
        "source_sha256": sha256(data).hexdigest(),
        "source_bytes": len(data),
        "warnings": [],
        "status": "ok",
        "outcome": "no_match",
        "phrases": [],
    }

    class Song:
        metadata_repairs = []
        warnings = []

    monkeypatch.setattr(sample.dataset_audit, "load_midi", lambda *args, **kwargs: Song())
    monkeypatch.setattr(
        sample.dataset_audit,
        "_reextract_record",
        lambda *args, **kwargs: ["re-extracted phrases differ"],
    )
    result = sample._run_one(
        tmp_path,
        record,
        {"algorithm": "reference", "config": {}, "percussion": False},
        "not_search_limited",
    )

    assert result["status"] == "failed"
    assert result["failures"] == ["re-extracted phrases differ"]


def _empty_full_fixture(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    provenance = dataset / "provenance"
    provenance.mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    (dataset / "sources.jsonl").write_text("")
    (dataset / "phrases.jsonl").write_text("")
    config = {
        "algorithm": "reference",
        "code_sha256": "fixture",
        "cohort_limit": None,
        "config": {},
        "discovered_source_files": 0,
        "export": True,
        "git_dirty": True,
        "git_head": "fixture",
        "percussion": False,
        "python": platform.python_version(),
        "recover_invalid_keys": False,
        "run_key": "fixture",
        "selected_source_files": 0,
        "version": "fixture",
    }
    (dataset / "build_config.json").write_text(json.dumps(config))
    (dataset / "summary.json").write_text(json.dumps({"source_files": 0, "run_key": "fixture"}))
    (dataset / "audit.json").write_text("{}")
    for relative in sample._algorithm_modules(config):
        target = provenance / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(__file__).parents[1] / relative).read_bytes())
    hashes = sample._artifact_hashes(dataset)
    saved_audit = {
        "passed": True,
        "failure_count": 0,
        "full_source_coverage_required": True,
        "source_files": 0,
        "run_key": "fixture",
        "source_manifest_sha256": hashes["sources.jsonl"]["sha256"],
        "phrase_manifest_sha256": hashes["phrases.jsonl"]["sha256"],
        "build_config_sha256": hashes["build_config.json"]["sha256"],
        "summary_sha256": hashes["summary.json"]["sha256"],
    }
    (dataset / "audit.json").write_text(json.dumps(saved_audit))
    return dataset


def test_validate_full_build_rejects_wrong_runtime_and_code(tmp_path: Path, monkeypatch) -> None:
    dataset = _empty_full_fixture(tmp_path)
    source = tmp_path / "source"
    monkeypatch.setattr(
        sample.dataset_audit,
        "audit",
        lambda *args, **kwargs: {"passed": True, "full_source_coverage_required": True, "source_files": 0},
    )
    context = sample._validate_full_build(dataset, source)
    assert context["records"] == []

    config_path = dataset / "build_config.json"
    config = json.loads(config_path.read_text())
    config["python"] = "0.0.0"
    config_path.write_text(json.dumps(config))
    saved_audit = json.loads((dataset / "audit.json").read_text())
    saved_audit["build_config_sha256"] = sample._bytes_sha256(config_path.read_bytes())
    (dataset / "audit.json").write_text(json.dumps(saved_audit))
    with pytest.raises(ValueError, match="Python runtime"):
        sample._validate_full_build(dataset, source)

    dataset = _empty_full_fixture(tmp_path / "second")
    (dataset / "provenance" / "samuged" / "phrases.py").write_text("tampered")
    with pytest.raises(ValueError, match="detector module differs"):
        sample._validate_full_build(dataset, tmp_path / "second" / "source")


def test_run_one_rejects_changed_source_bytes(tmp_path: Path) -> None:
    path = tmp_path / "song.mid"
    path.write_bytes(b"changed")
    record = {
        "source_id": "source",
        "source_path": "song.mid",
        "source_sha256": "0" * 64,
        "source_bytes": 1,
        "metadata_repairs": [],
    }
    result = sample._run_one(tmp_path, record, {"algorithm": "reference", "config": {}}, "not_search_limited")
    assert result["status"] == "failed"
    assert "source bytes or hash differs" in result["failures"][0]


def test_run_one_rejects_source_mutation_during_replay(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "song.mid"
    data = b"original MIDI fixture"
    path.write_bytes(data)
    record = {
        "source_id": "source", "source_path": "song.mid",
        "source_sha256": sha256(data).hexdigest(), "source_bytes": len(data),
    }

    class Song:
        metadata_repairs = []
        warnings = []

    monkeypatch.setattr(sample.dataset_audit, "load_midi", lambda *args, **kwargs: Song())

    def mutate(*args):
        path.write_bytes(b"changed during replay")
        return []

    monkeypatch.setattr(sample.dataset_audit, "_reextract_record", mutate)
    result = sample._run_one(tmp_path, record, {"algorithm": "reference"}, "not_search_limited")
    assert result["status"] == "failed"
    assert result["failures"] == ["source bytes changed during re-extraction"]


def test_full_gate_rejects_nonzero_failures_even_with_passed_flag(tmp_path: Path) -> None:
    dataset = _empty_full_fixture(tmp_path)
    path = dataset / "audit.json"
    audit = json.loads(path.read_text())
    audit["failure_count"] = 1
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="audit is not passed"):
        sample._validate_full_build(dataset, tmp_path / "source")


def test_cli_returns_nonzero_when_sample_has_failures(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sample, "run_sample", lambda *args, **kwargs: {"failure_count": 1})
    assert sample.main(["--dataset", "d", "--source", "s", "--output", "o"]) == 1
    assert '"failure_count": 1' in capsys.readouterr().out
