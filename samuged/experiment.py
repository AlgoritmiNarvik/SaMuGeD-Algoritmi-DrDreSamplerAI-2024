"""Receipts and source snapshots for reproducible local experiments."""
from __future__ import annotations

from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Iterable


RECEIPT_VERSION = "samuged-experiment-receipt-v1"
SNAPSHOT_VERSION = "samuged-source-snapshot-v1"
DEFAULT_RESULT_ARTIFACTS = ("raw_results.json", "aggregate.json")
_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPOSITORY_ROOT = _PACKAGE_ROOT.parent


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _write_json(path: Path, value: Any) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return payload


def _relative_source_files(required_files: Iterable[str] | None = None) -> list[Path]:
    if required_files is None:
        files = sorted(_PACKAGE_ROOT.glob("*.py"))
        legacy = _REPOSITORY_ROOT / "scripts" / "run_legacy_case.py"
        adapter = _REPOSITORY_ROOT / "testing_tools" / "test_scripts" / "asle_scripts" / "pattern_detection_old.py"
        dependency_files = (_REPOSITORY_ROOT/"pyproject.toml", _REPOSITORY_ROOT/"requirements-research.lock")
        files.extend(path for path in (legacy, adapter, *dependency_files) if path.is_file())
        return files
    files = []
    for relative in required_files:
        path = (_REPOSITORY_ROOT / relative).resolve()
        if not path.is_file() or not path.is_relative_to(_REPOSITORY_ROOT):
            raise FileNotFoundError(f"required source file is unavailable: {relative}")
        files.append(path)
    return sorted(set(files))


def _snapshot_sources(output: Path, required_files: Iterable[str] | None = None) -> dict[str, Any]:
    target = output / "source_snapshot"
    target.mkdir()
    entries = []
    for source in _relative_source_files(required_files):
        relative = source.relative_to(_REPOSITORY_ROOT).as_posix()
        data = source.read_bytes()
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        entries.append({"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)})
    snapshot_sha256 = sha256_json({"version": SNAPSHOT_VERSION, "files": entries})
    metadata = {
        "snapshot_version": SNAPSHOT_VERSION,
        "files": entries,
        "snapshot_sha256": snapshot_sha256,
    }
    _write_json(output / "source_snapshot.json", metadata)
    return metadata


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def runtime_metadata() -> dict[str, Any]:
    """Return interpreter and versions of packages used by the experiments."""
    package_names = (
        "samuged-phrases",
        "mido",
        "jsonschema",
        "jsonschema-specifications",
        "referencing",
        "rpds-py",
        "numpy",
        "miditoolkit",
        "scikit-learn",
        "matplotlib",
        "mir-eval",
    )
    packages = {
        name: version
        for name in package_names
        if (version := _version(name)) is not None
    }
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": str(Path(sys.executable).resolve()),
        "packages": packages,
        "dependencies": packages,
    }


def _case_cohort(cases: Iterable[Any]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        metadata = case.metadata() if hasattr(case, "metadata") else dict(case)
        rows.append(metadata)
    return rows


def prepare_experiment(
    output: Path,
    *,
    design: dict[str, Any],
    config: dict[str, Any],
    cases: Iterable[Any],
    required_files: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Create an immutable start receipt in a new, empty output directory.

    The directory check occurs before any experiment output is created. The
    receipt is written after the source snapshot and case cohort are frozen,
    but before a detector may be called.
    """
    output = output.resolve()
    if output.exists():
        if not output.is_dir():
            raise FileExistsError(f"experiment output is not a directory: {output}")
        if any(output.iterdir()):
            raise FileExistsError(f"experiment output must be empty: {output}")
    else:
        output.mkdir(parents=True)

    cohort = _case_cohort(cases)
    snapshot = _snapshot_sources(output, required_files)
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "status": "started",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "design": design,
        "design_sha256": sha256_json(design),
        "config": config,
        "config_sha256": sha256_json(config),
        "case_cohort": cohort,
        "case_cohort_sha256": sha256_json(cohort),
        "source_snapshot": {
            "path": "source_snapshot",
            "metadata_path": "source_snapshot.json",
            "snapshot_sha256": snapshot["snapshot_sha256"],
        },
        "runtime": runtime_metadata(),
    }
    receipt_bytes = _write_json(output / "experiment_receipt.json", receipt)
    receipt["receipt_sha256"] = sha256_bytes(receipt_bytes)
    return receipt


def receipt_links(receipt: dict[str, Any]) -> dict[str, str]:
    """Return stable hash links to place in result artifacts."""
    return {
        "receipt_sha256": receipt["receipt_sha256"],
        "config_sha256": receipt["config_sha256"],
        "source_snapshot_sha256": receipt["source_snapshot"]["snapshot_sha256"],
        "snapshot_sha256": receipt["source_snapshot"]["snapshot_sha256"],
        "case_cohort_sha256": receipt["case_cohort_sha256"],
    }


def _contained_artifact(output: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("unsafe experiment artifact path")
    resolved = (output / relative).resolve(strict=True)
    if not resolved.is_relative_to(output.resolve()) or not resolved.is_file():
        raise ValueError("experiment artifact escapes output directory")
    return resolved


def _contained_directory(output: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("unsafe experiment directory path")
    resolved = (output / relative).resolve(strict=True)
    if not resolved.is_relative_to(output.resolve()) or not resolved.is_dir():
        raise ValueError("experiment directory escapes output directory")
    return resolved


def _expected_result_artifacts(receipt: dict[str, Any]) -> tuple[str, ...]:
    declared = receipt.get("design", {}).get("result_artifacts", DEFAULT_RESULT_ARTIFACTS)
    if not isinstance(declared, (list, tuple)) or not declared:
        raise ValueError("experiment design requires a nonempty result_artifacts list")
    if any(not isinstance(name, str) or not name for name in declared):
        raise ValueError("experiment result artifact names must be nonempty strings")
    names = tuple(sorted(declared))
    if len(set(names)) != len(names):
        raise ValueError("experiment result artifact names must be distinct")
    reserved = {"experiment_receipt.json", "source_snapshot.json", "completion_receipt.json"}
    if any(name in reserved for name in names):
        raise ValueError("completion artifact must be a result file")
    return names


def verify_start_receipt(output: Path) -> dict[str, Any]:
    """Verify a frozen design and every saved executable source byte."""
    output = output.resolve(strict=True)
    receipt_path = _contained_artifact(output, "experiment_receipt.json")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("receipt_version") != RECEIPT_VERSION or receipt.get("status") != "started":
        raise ValueError("unsupported experiment start receipt")
    for key in ("design", "config", "case_cohort"):
        if sha256_json(receipt[key]) != receipt[f"{key}_sha256"]:
            raise ValueError(f"experiment {key} hash mismatch")
    source_snapshot = receipt.get("source_snapshot")
    if (not isinstance(source_snapshot, dict)
            or source_snapshot.get("path") != "source_snapshot"
            or source_snapshot.get("metadata_path") != "source_snapshot.json"):
        raise ValueError("experiment receipt has invalid snapshot paths")
    snapshot_path = _contained_artifact(output, "source_snapshot.json")
    snapshot_root = _contained_directory(output, "source_snapshot")
    snapshot = json.loads(snapshot_path.read_text())
    snapshot_hash = sha256_json({"version": snapshot["snapshot_version"], "files": snapshot["files"]})
    if (snapshot.get("snapshot_version") != SNAPSHOT_VERSION
            or snapshot_hash != snapshot.get("snapshot_sha256")
            or snapshot_hash != receipt["source_snapshot"]["snapshot_sha256"]):
        raise ValueError("experiment snapshot manifest hash mismatch")
    paths = set()
    for entry in snapshot["files"]:
        if entry["path"] in paths:
            raise ValueError("duplicate experiment snapshot path")
        paths.add(entry["path"])
        data = _contained_artifact(snapshot_root, entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
            raise ValueError(f"experiment snapshot file mismatch: {entry['path']}")
    return {**receipt, "receipt_sha256": sha256_bytes(receipt_path.read_bytes())}


def complete_experiment(
    output: Path, artifacts: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Bind the complete frozen result set without changing the start receipt.

    The default result contract is ``raw_results.json`` plus ``aggregate.json``.
    A study may replace that set only by declaring ``design.result_artifacts``
    before execution.  A caller-provided list must equal the frozen set exactly.

    JSON results carry provenance links; declared binary or text artifacts are
    bound by their exact bytes. This proves integrity and provenance links only. It does not certify
    metric correctness, evaluation design quality or a promotion decision.
    """
    output = output.resolve()
    target = output / "completion_receipt.json"
    if target.exists():
        raise FileExistsError("experiment completion receipt already exists")
    receipt = verify_start_receipt(output)
    links = receipt_links(receipt)
    expected = _expected_result_artifacts(receipt)
    names = expected if artifacts is None else tuple(sorted(artifacts))
    if len(set(names)) != len(names):
        raise ValueError("completion requires distinct result artifact names")
    if names != expected:
        raise ValueError(
            "completion artifacts differ from the frozen expected result set: "
            + ", ".join(expected)
        )
    entries = {}
    for relative in names:
        if relative in {"experiment_receipt.json", "source_snapshot.json", "completion_receipt.json"}:
            raise ValueError("completion artifact must be a result file")
        data = _contained_artifact(output, relative).read_bytes()
        if PurePosixPath(relative).suffix == ".json":
            result = json.loads(data)
            if not isinstance(result, dict) or any(result.get(key) != value for key, value in links.items()):
                raise ValueError(f"result provenance links mismatch: {relative}")
        entries[relative] = {"sha256": sha256_bytes(data), "bytes": len(data)}
    completion = {
        "schema_version": "samuged-experiment-completion-v1", "status": "completed",
        **links, "required_artifacts": list(expected), "artifacts": entries,
        "claim_boundary": "artifact integrity and frozen provenance links, not scientific acceptance",
    }
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(completion, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return completion


def verify_completed_experiment(output: Path) -> dict[str, Any]:
    """Verify both the frozen design and a separate completed result receipt."""
    output = output.resolve(strict=True)
    receipt = verify_start_receipt(output)
    completion_path = _contained_artifact(output, "completion_receipt.json")
    completion = json.loads(completion_path.read_text())
    if (completion.get("schema_version") != "samuged-experiment-completion-v1"
            or completion.get("status") != "completed"
            or any(completion.get(key) != value for key, value in receipt_links(receipt).items())):
        raise ValueError("invalid experiment completion receipt")
    entries = completion.get("artifacts")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("experiment completion has no artifacts")
    expected = _expected_result_artifacts(receipt)
    if tuple(sorted(entries)) != expected:
        raise ValueError("experiment completion artifact set differs from frozen design")
    declared = completion.get("required_artifacts")
    if declared is not None and tuple(declared) != expected:
        raise ValueError("experiment completion required_artifacts mismatch")
    for relative, entry in entries.items():
        data = _contained_artifact(output, relative).read_bytes()
        if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
            raise ValueError(f"completed result changed: {relative}")
        if PurePosixPath(relative).suffix == ".json":
            result = json.loads(data)
            if not isinstance(result, dict) or any(result.get(key) != value for key, value in receipt_links(receipt).items()):
                raise ValueError(f"completed result links mismatch: {relative}")
    return completion
