import json
from pathlib import Path

import pytest

from samuged.evaluate import generate_cases
from samuged.experiment import verify_completed_experiment
from scripts import compare_cache


def test_comparison_freezes_executed_reference_and_driver(tmp_path, monkeypatch):
    development = [case for case in generate_cases(10) if case.split == "development"][:2]
    monkeypatch.setattr(compare_cache, "generate_cases", lambda _count: development)
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text("")
    baseline = Path(compare_cache.__file__).resolve().parents[1] / "samuged" / "phrases.py"
    output = tmp_path / "comparison"
    result = compare_cache.run(tmp_path, manifest, baseline, output)
    assert result["groups"]["synthetic"]["identical_phrase_outputs"] == len(development)
    assert verify_completed_experiment(output)["status"] == "completed"
    snapshot = json.loads((output / "source_snapshot.json").read_text())
    paths = {entry["path"] for entry in snapshot["files"]}
    assert {"scripts/compare_cache.py", "samuged/phrases.py"} <= paths
    frozen_reference = output / "source_snapshot" / "samuged" / "phrases.py"
    frozen_reference.write_bytes(frozen_reference.read_bytes() + b"\n# altered snapshot\n")
    with pytest.raises(ValueError, match="snapshot file mismatch"):
        verify_completed_experiment(output)
