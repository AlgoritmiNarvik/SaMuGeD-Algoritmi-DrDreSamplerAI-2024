import json
import subprocess
import sys

import pytest

from samuged.aligned import AlignedConfig
from samuged.audit import audit
from samuged.dataset import build
from samuged.evaluate import _build_case, _write_case
from scripts.validate_schema import validate_dataset


def test_closed_build_exports_and_reextracts_replacements(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    case = _build_case("legacy_contiguous_exact", "regression", 0, 30_000_000)
    _write_case(case, source / "phrase.mid")
    output = tmp_path / "closed"
    result = build(source, output, AlignedConfig(), workers=1,
                   algorithm="aligned_closed", percussion=True)
    assert result["algorithm"] == "aligned_closed"
    row = json.loads((output / "sources.jsonl").read_text())
    assert row["closed_extension_count"] == len(row["selection_trace"]) > 0
    assert row["selection"] == "closed-exact-extension-v1"
    assert row["algorithm"] == "aligned_closed"
    assert row["phrases"][0]["note_count"] == 16
    checked = audit(source, output, require_full=True, reextract=True)
    assert checked["passed"], checked["failures"]
    schema = validate_dataset(output)
    assert schema["invalid_rows"] == 0, schema


def test_closed_cli_rejects_reference_only_mode(tmp_path):
    result = subprocess.run([
        sys.executable, "-m", "samuged.cli", "build", "--algorithm", "aligned_closed",
        "--mode", "exact", "--source", str(tmp_path), "--output", str(tmp_path / "out"),
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert "--mode is only supported" in result.stderr


def test_closed_build_rejects_reference_configuration(tmp_path):
    from samuged.phrases import Config
    with pytest.raises(TypeError, match="AlignedConfig"):
        build(tmp_path, tmp_path / "out", Config(), algorithm="aligned_closed")
