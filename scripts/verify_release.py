"""Verify a portable SaMuGeD metadata release and optional archive."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any, BinaryIO, Iterator

from samuged import experiment
from samuged.dataset import canonical_json, file_digest

try:
    from scripts.package_dataset import _selection_replay_binding
    from scripts.screen_splits import verify_screening
except ModuleNotFoundError as exc:  # Direct ``python scripts/verify_release.py``.
    if exc.name != "scripts":
        raise
    from package_dataset import _selection_replay_binding
    from screen_splits import verify_screening


VERSION = "samuged-portable-release-verification-v1"
CORE_FILES = (
    "release.json",
    "sources.jsonl",
    "phrases.jsonl",
    "summary.json",
    "build_config.json",
    "audit.json",
)
AUDIT_BINDINGS = {
    "source_manifest_sha256": "sources.jsonl",
    "phrase_manifest_sha256": "phrases.jsonl",
    "build_config_sha256": "build_config.json",
    "summary_sha256": "summary.json",
}
HEX64 = re.compile(r"[0-9a-f]{64}")
PROVENANCE_SEEDS = (
    "scripts/verify_release.py",
    "scripts/package_dataset.py",
    "scripts/screen_splits.py",
)


def _safe_relative(name: str, *, label: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe {label} path")
    raw_parts = name.split("/")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in ("", ".", "..") for part in raw_parts)
        or path.as_posix() != name
    ):
        raise ValueError(f"unsafe {label} path: {name}")
    return name


def _regular_inventory(root: Path) -> dict[str, Path]:
    if root.is_symlink():
        raise ValueError("release root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("release must be a directory")
    result: dict[str, Path] = {}

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                _safe_relative(relative, label="metadata")
                if entry.is_symlink():
                    raise ValueError(f"release contains a symlink: {relative}")
                if entry.is_dir(follow_symlinks=False):
                    visit(path)
                elif entry.is_file(follow_symlinks=False):
                    result[relative] = path
                else:
                    raise ValueError(f"release contains a non-regular entry: {relative}")

    visit(root)
    return result


def _parse_checksums(data: bytes, *, label: str) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc
    if text and not text.endswith("\n"):
        raise ValueError(f"{label} must end with LF")
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.split("\n")[:-1], 1):
        if len(line) < 67 or line[64:66] != "  ":
            raise ValueError(f"invalid {label} line {line_number}")
        digest, name = line[:64], line[66:]
        if not HEX64.fullmatch(digest):
            raise ValueError(f"invalid {label} digest on line {line_number}")
        _safe_relative(name, label=label)
        if name in result:
            raise ValueError(f"duplicate {label} path: {name}")
        result[name] = digest
    return result


def _object_from_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"invalid {label}") from exc
    return _object_from_bytes(data, label=label)


def _normalized_counts(value: Any, keys: tuple[str, ...], *, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f"invalid {label}")
    result: dict[str, int] = {}
    for key in keys:
        count = value.get(key, 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid {label}")
        result[key] = count
    return result


def _zero_default_count(value: dict[str, Any], key: str, *, label: str) -> int:
    count = value.get(key, 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"invalid {label}")
    return count


def _code_provenance() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    files: dict[str, dict[str, int | str]] = {}
    for path in experiment._relative_source_files(PROVENANCE_SEEDS):
        name = path.relative_to(repository).as_posix()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"verifier dependency is missing or linked: {name}")
        files[name] = {"bytes": path.stat().st_size, "sha256": file_digest(path)}
    return {
        "status": "local_code_hashes_not_publisher_authentication",
        "authenticated_publisher": False,
        "files": files,
        "closure_sha256": sha256(canonical_json(files).encode("utf-8")).hexdigest(),
    }


def _jsonl_rows(path: Path, *, label: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """Read only LF as the record separator, preserving Unicode line controls."""
    with path.open("rb") as stream:
        line_number = 0
        for raw in stream:
            line_number += 1
            if not raw.endswith(b"\n"):
                raise ValueError(f"{label} line {line_number} does not end with LF")
            payload = raw[:-1]
            if payload.endswith(b"\r"):
                payload = payload[:-1]
            if not payload.strip():
                raise ValueError(f"{label} contains an empty row on line {line_number}")
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid {label} row on line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{label} row is not an object on line {line_number}")
            yield line_number, value


def _verify_metadata_checksums(
    inventory: dict[str, Path]
) -> tuple[dict[str, str], dict[str, int]]:
    checksum_path = inventory.get("SHA256SUMS")
    if checksum_path is None:
        raise ValueError("release is missing SHA256SUMS")
    expected = _parse_checksums(checksum_path.read_bytes(), label="metadata SHA256SUMS")
    actual_names = set(inventory) - {"SHA256SUMS"}
    if set(expected) != actual_names:
        missing = sorted(actual_names - set(expected))
        stale = sorted(set(expected) - actual_names)
        raise ValueError(
            "metadata SHA256SUMS file set mismatch"
            f" (unlisted={missing[:3]}, stale={stale[:3]})"
        )
    sizes: dict[str, int] = {}
    for name in sorted(expected):
        path = inventory[name]
        digest = file_digest(path)
        if digest != expected[name]:
            raise ValueError(f"metadata SHA256 mismatch: {name}")
        sizes[name] = path.stat().st_size
    return expected, sizes


def _verify_jsonl_files(inventory: dict[str, Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in sorted(path for path in inventory if path.endswith(".jsonl")):
        counts[name] = sum(1 for _line, _row in _jsonl_rows(inventory[name], label=name))
    return counts


def _verify_core(
    release: Path, inventory: dict[str, Path], metadata_hashes: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    for name in CORE_FILES:
        if name not in inventory:
            raise ValueError(f"release is missing {name}")
    release_json = _load_object(inventory["release.json"], label="release.json")
    summary = _load_object(inventory["summary.json"], label="summary.json")
    audit = _load_object(inventory["audit.json"], label="audit.json")
    build_config = _load_object(inventory["build_config.json"], label="build_config.json")
    if release_json.get("schema_version") != "samuged-local-release-v1":
        raise ValueError("unsupported release schema version")
    run_key = release_json.get("run_key")
    if not isinstance(run_key, str) or not HEX64.fullmatch(run_key):
        raise ValueError("release has an invalid run key")
    if any(value.get("run_key") != run_key for value in (summary, audit, build_config)):
        raise ValueError("release run key is inconsistent")
    algorithm = build_config.get("algorithm", "reference")
    if summary.get("algorithm") != algorithm:
        raise ValueError("release algorithm is inconsistent")
    if release_json.get("algorithm") not in (None, algorithm):
        raise ValueError("release algorithm is inconsistent")
    if (
        audit.get("passed") is not True
        or audit.get("failure_count") != 0
        or audit.get("failures") != []
    ):
        raise ValueError("release audit did not pass cleanly")
    for field, name in AUDIT_BINDINGS.items():
        if audit.get(field) != metadata_hashes.get(name):
            raise ValueError(f"audit binding mismatch: {name}")
    if summary.get("source_manifest_sha256") != metadata_hashes["sources.jsonl"]:
        raise ValueError("summary source manifest binding mismatch")
    if summary.get("phrase_manifest_sha256") != metadata_hashes["phrases.jsonl"]:
        raise ValueError("summary phrase manifest binding mismatch")
    if release_json.get("source_manifest_sha256") != metadata_hashes["sources.jsonl"]:
        raise ValueError("release source manifest binding mismatch")
    if release_json.get("phrase_manifest_sha256") != metadata_hashes["phrases.jsonl"]:
        raise ValueError("release phrase manifest binding mismatch")

    source_ids: set[str] = set()
    source_status = Counter()
    for line_number, row in _jsonl_rows(inventory["sources.jsonl"], label="sources.jsonl"):
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in source_ids:
            raise ValueError(f"invalid or duplicate source ID on line {line_number}")
        if row.get("status") not in ("ok", "error"):
            raise ValueError(f"invalid source status on line {line_number}")
        source_ids.add(source_id)
        source_status[str(row.get("status"))] += 1

    phrase_ids: set[str] = set()
    phrase_counts = Counter()
    families: dict[str, set[str]] = {"melodic": set(), "percussion": set()}
    midi_payloads: dict[str, str] = {}
    phrase_rows = 0
    for line_number, row in _jsonl_rows(inventory["phrases.jsonl"], label="phrases.jsonl"):
        phrase_rows += 1
        phrase_id = row.get("phrase_id")
        source_id = row.get("source_id")
        kind = row.get("kind")
        if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_ids:
            raise ValueError(f"invalid or duplicate phrase ID on line {line_number}")
        if source_id not in source_ids:
            raise ValueError(f"phrase references an unknown source on line {line_number}")
        if kind not in families:
            raise ValueError(f"invalid phrase kind on line {line_number}")
        phrase_ids.add(phrase_id)
        phrase_counts[kind] += 1
        family_id = row.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError(f"phrase has no family ID on line {line_number}")
        families[kind].add(family_id)
        midi_path, midi_hash = row.get("midi_path"), row.get("midi_sha256")
        if midi_path is None:
            if midi_hash is not None:
                raise ValueError(f"phrase has a MIDI hash without a path on line {line_number}")
            continue
        _safe_relative(midi_path, label="phrase MIDI")
        if not isinstance(midi_hash, str) or not HEX64.fullmatch(midi_hash):
            raise ValueError(f"phrase has an invalid MIDI hash on line {line_number}")
        previous = midi_payloads.setdefault(midi_path, midi_hash)
        if previous != midi_hash:
            raise ValueError(f"conflicting MIDI hashes for path: {midi_path}")

    source_rows = len(source_ids)
    actual_source_status = {key: source_status.get(key, 0) for key in ("ok", "error")}
    summary_source_status = _normalized_counts(
        summary.get("source_status"), ("ok", "error"), label="summary source status"
    )
    if summary_source_status != actual_source_status:
        raise ValueError("summary source status counts mismatch")
    audit_counts = audit.get("counts")
    if not isinstance(audit_counts, dict):
        raise ValueError("audit counts are missing")
    if _zero_default_count(
        audit_counts, "sources_verified", label="audit verified source count"
    ) != actual_source_status["ok"]:
        raise ValueError("audit verified source count mismatch")
    if _zero_default_count(
        audit_counts, "reported_input_errors", label="audit input error count"
    ) != actual_source_status["error"]:
        raise ValueError("audit input error count mismatch")
    expected_phrase_counts = {
        key: phrase_counts.get(key, 0) for key in ("melodic", "percussion")
    }
    if any(
        value != source_rows
        for value in (
            release_json.get("source_files"),
            summary.get("source_files"),
            audit.get("source_files"),
        )
    ):
        raise ValueError("source row count mismatch")
    if release_json.get("phrase_rows") != phrase_rows or audit.get("phrase_rows") != phrase_rows:
        raise ValueError("phrase row count mismatch")
    summary_phrase_counts = _normalized_counts(
        summary.get("phrase_counts"),
        ("melodic", "percussion"),
        label="summary phrase counts",
    )
    if summary_phrase_counts != expected_phrase_counts:
        raise ValueError("summary phrase counts mismatch")
    audit_phrase_counts = {
        key: _zero_default_count(audit_counts, key, label=f"audit {key} count")
        for key in ("melodic", "percussion")
    }
    if audit_phrase_counts != expected_phrase_counts:
        raise ValueError("audit phrase counts mismatch")
    if release_json.get("midi_payloads") != len(midi_payloads):
        raise ValueError("release MIDI payload count mismatch")
    if _zero_default_count(
        audit_counts, "midi_verified", label="audit verified MIDI count"
    ) != len(midi_payloads):
        raise ValueError("audit verified MIDI count mismatch")
    unique_counts = {kind: len(values) for kind, values in families.items()}
    release_family_counts = _normalized_counts(
        release_json.get("unique_family_counts"),
        ("melodic", "percussion"),
        label="release family counts",
    )
    if release_family_counts != unique_counts:
        raise ValueError("release family counts mismatch")
    if set(midi_payloads) & set(inventory):
        raise ValueError("MIDI and metadata paths collide")
    if "SHA256SUMS" in midi_payloads:
        raise ValueError("MIDI path collides with archive checksum list")

    audit_scope = release_json.get("audit_scope")
    if audit_scope is not None and not isinstance(audit_scope, dict):
        raise ValueError("release audit scope is invalid")
    full = (
        summary.get("cohort_limit") is None
        and summary.get("source_files") == summary.get("discovered_source_files")
        and audit.get("full_source_coverage_required") is True
    )
    if release_json.get("full_local_corpus") is not full:
        raise ValueError("release full corpus flag mismatch")
    if audit_scope is not None:
        if audit_scope.get("primary_audit_passed") is not True:
            raise ValueError("release audit scope does not record a passing audit")
        if audit_scope.get("audit_sha256") != metadata_hashes["audit.json"]:
            raise ValueError("release audit scope hash mismatch")
        if audit_scope.get("full_source_coverage_required") is not (
            audit.get("full_source_coverage_required") is True
        ):
            raise ValueError("release audit scope coverage flag mismatch")
        if audit_scope.get("source_records_verified") != audit.get("counts", {}).get(
            "sources_verified", 0
        ):
            raise ValueError("release audit scope source count mismatch")
        if audit_scope.get("midi_excerpts_verified") != audit.get("counts", {}).get(
            "midi_verified", 0
        ):
            raise ValueError("release audit scope MIDI count mismatch")
        if audit_scope.get("selection_reextracted_for_all_successful_sources") is not (
            audit.get("reextraction_required") is True
        ):
            raise ValueError("release audit scope re-extraction flag mismatch")

    optional: dict[str, Any] = {}
    replay_path = release / "evidence" / "selection_replay"
    replay_declared = release_json.get("selection_replay")
    if replay_path.exists() or replay_path.is_symlink() or replay_declared is not None:
        if replay_declared is None or not replay_path.is_dir():
            raise ValueError("selection replay declaration and directory differ")
        verified = _selection_replay_binding(
            replay_path, release, summary, audit, build_config
        )
        verified.pop("files", None)
        if replay_declared != verified:
            raise ValueError("release selection replay summary mismatch")
        if audit_scope is None or audit_scope.get("selection_replay") != verified:
            raise ValueError("release audit scope selection replay summary mismatch")
        optional["selection_replay"] = verified
    elif audit_scope is not None and audit_scope.get("selection_replay") is not None:
        raise ValueError("audit scope declares a missing selection replay")

    screening_path = release / "views" / "duplicate_screening"
    screening_declared = release_json.get("duplicate_screening")
    if screening_path.exists() or screening_path.is_symlink() or screening_declared is not None:
        if screening_declared is None or not screening_path.is_dir():
            raise ValueError("screening declaration and directory differ")
        verified_screening = verify_screening(release, screening_path)
        expected_screening = {
            "summary_sha256": file_digest(screening_path / "summary.json"),
            "phrase_split_counts": verified_screening["phrase_split_counts"],
            "excluded_source_groups": verified_screening["excluded_source_groups"],
            "duplicate_report_sha256": verified_screening["duplicate_report_sha256"],
        }
        if screening_declared != expected_screening:
            raise ValueError("release duplicate screening summary mismatch")
        optional["duplicate_screening"] = expected_screening

    details = {
        "run_key": run_key,
        "algorithm": algorithm,
        "full_local_corpus": release_json.get("full_local_corpus"),
        "source_rows": source_rows,
        "source_status_counts": actual_source_status,
        "phrase_rows": phrase_rows,
        "phrase_counts": expected_phrase_counts,
        "unique_family_counts": unique_counts,
        "midi_payloads": len(midi_payloads),
        "audit_sha256": metadata_hashes["audit.json"],
        "audit_bindings": {field: audit[field] for field in AUDIT_BINDINGS},
        "release_audit_scope_recorded": audit_scope is not None,
    }
    return details, midi_payloads, optional


def _hash_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _verify_archive(
    archive: Path,
    release: Path,
    metadata_hashes: dict[str, str],
    metadata_sizes: dict[str, int],
    midi_payloads: dict[str, str],
    run_key: str,
) -> dict[str, Any]:
    if archive.is_symlink():
        raise ValueError("archive must not be a symlink")
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.is_relative_to(release):
        raise ValueError("archive must be a regular file outside the release directory")
    receipt_path = archive.with_suffix(archive.suffix + ".json")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("archive receipt is missing or is a symlink")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha256 = sha256(receipt_bytes).hexdigest()
    receipt = _object_from_bytes(receipt_bytes, label="archive receipt")
    archive_sha256 = file_digest(archive)
    archive_bytes = archive.stat().st_size
    expected_names = set(metadata_hashes) | set(midi_payloads) | {"SHA256SUMS"}
    seen: set[str] = set()
    actual_hashes: dict[str, str] = {}
    actual_sizes: dict[str, int] = {}
    checksum_bytes: bytes | None = None
    try:
        with tarfile.open(archive, mode="r|gz") as tar:
            for member in tar:
                name = _safe_relative(member.name, label="archive member")
                if name in seen:
                    raise ValueError(f"duplicate archive member: {name}")
                seen.add(name)
                if not member.isreg():
                    raise ValueError(f"archive member is not a regular file: {name}")
                if name not in expected_names:
                    raise ValueError(f"unexpected archive member: {name}")
                if name in metadata_sizes and member.size != metadata_sizes[name]:
                    raise ValueError(f"archive metadata size mismatch: {name}")
                if name == "SHA256SUMS" and member.size > 128 * 1024 * 1024:
                    raise ValueError("archive SHA256SUMS is unreasonably large")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ValueError(f"archive member cannot be read: {name}")
                if name == "SHA256SUMS":
                    checksum_bytes = extracted.read()
                    digest, size = sha256(checksum_bytes).hexdigest(), len(checksum_bytes)
                else:
                    digest, size = _hash_stream(extracted)
                if size != member.size:
                    raise ValueError(f"archive member size mismatch: {name}")
                actual_hashes[name], actual_sizes[name] = digest, size
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ValueError("invalid archive stream") from exc
    if seen != expected_names:
        missing = sorted(expected_names - seen)
        raise ValueError(f"archive member set mismatch (missing={missing[:3]})")
    if checksum_bytes is None:
        raise ValueError("archive is missing SHA256SUMS")
    archive_checksums = _parse_checksums(checksum_bytes, label="archive SHA256SUMS")
    payload_names = seen - {"SHA256SUMS"}
    if set(archive_checksums) != payload_names:
        raise ValueError("archive SHA256SUMS payload set mismatch")
    for name in sorted(payload_names):
        if archive_checksums[name] != actual_hashes[name]:
            raise ValueError(f"archive SHA256 mismatch: {name}")
        if name in metadata_hashes and actual_hashes[name] != metadata_hashes[name]:
            raise ValueError(f"archive metadata differs from release directory: {name}")
        if name in midi_payloads and actual_hashes[name] != midi_payloads[name]:
            raise ValueError(f"archive MIDI differs from phrase manifest: {name}")
    if receipt.get("archive") != archive.name:
        raise ValueError("archive receipt filename mismatch")
    if receipt.get("sha256") != archive_sha256 or receipt.get("bytes") != archive_bytes:
        raise ValueError("archive receipt byte binding mismatch")
    if receipt.get("members") != len(seen):
        raise ValueError("archive receipt member count mismatch")
    if receipt.get("run_key") != run_key:
        raise ValueError("archive receipt run key mismatch")
    final_archive_bytes = archive.stat().st_size
    final_archive_sha256 = file_digest(archive)
    if final_archive_bytes != archive_bytes or final_archive_sha256 != archive_sha256:
        raise ValueError("archive changed during verification")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError("archive receipt changed during verification")
    final_receipt_bytes = receipt_path.read_bytes()
    if (
        len(final_receipt_bytes) != len(receipt_bytes)
        or sha256(final_receipt_bytes).hexdigest() != receipt_sha256
    ):
        raise ValueError("archive receipt changed during verification")
    return {
        "path": str(archive),
        "receipt_path": str(receipt_path.resolve()),
        "sha256": archive_sha256,
        "bytes": archive_bytes,
        "members": len(seen),
        "metadata_members": len(metadata_hashes),
        "midi_members": len(midi_payloads),
        "checksum_member_sha256": actual_hashes["SHA256SUMS"],
        "receipt_sha256": receipt_sha256,
    }


def verify_release(release: Path, output: Path, *, archive: Path | None = None) -> dict[str, Any]:
    release_input = Path(release)
    if release_input.is_symlink():
        raise ValueError("release root must not be a symlink")
    release = release_input.resolve(strict=True)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("verification output already exists")
    output_parent = output.parent.resolve(strict=True)
    output = output_parent / output.name
    if output == release or output.is_relative_to(release):
        raise ValueError("verification output must be outside the release directory")
    archive_path = None
    if archive is not None:
        archive_input = Path(archive)
        if archive_input.is_symlink():
            raise ValueError("archive must not be a symlink")
        archive_path = archive_input.resolve(strict=True)
        receipt_path = archive_path.with_suffix(archive_path.suffix + ".json")
        if output in (archive_path, receipt_path):
            raise ValueError("verification output collides with an archive input")

    inventory = _regular_inventory(release)
    metadata_hashes, metadata_sizes = _verify_metadata_checksums(inventory)
    metadata_checksum_sha256 = file_digest(release / "SHA256SUMS")
    metadata_checksum_bytes = (release / "SHA256SUMS").stat().st_size
    jsonl_counts = _verify_jsonl_files(inventory)
    dataset, midi_payloads, optional = _verify_core(release, inventory, metadata_hashes)
    archive_result = None
    if archive_path is not None:
        archive_result = _verify_archive(
            archive_path,
            release,
            metadata_hashes,
            metadata_sizes,
            midi_payloads,
            dataset["run_key"],
        )
    provenance = _code_provenance()
    report: dict[str, Any] = {
        "schema_version": VERSION,
        "status": "passed",
        "scope": "metadata_and_archive" if archive_result else "metadata_only",
        "claim_boundary": (
            "portable byte integrity and recorded metadata consistency only; no source corpus, "
            "musical correctness, perceptual quality, redistribution rights or authenticity claim"
        ),
        "verifier_provenance": provenance,
        "release": str(release),
        "metadata": {
            "checksum_sha256": metadata_checksum_sha256,
            "payload_files": len(metadata_hashes),
            "payload_bytes": sum(metadata_sizes.values()),
            "jsonl_row_counts": jsonl_counts,
        },
        "dataset": dataset,
        "optional_evidence": optional,
        "archive": archive_result,
    }
    try:
        final_inventory = _regular_inventory(release)
        final_hashes, final_sizes = _verify_metadata_checksums(final_inventory)
        final_checksum_sha256 = file_digest(release / "SHA256SUMS")
        final_checksum_bytes = (release / "SHA256SUMS").stat().st_size
    except (OSError, ValueError) as exc:
        raise ValueError("release metadata changed during verification") from exc
    if (
        set(final_inventory) != set(inventory)
        or final_hashes != metadata_hashes
        or final_sizes != metadata_sizes
        or final_checksum_sha256 != metadata_checksum_sha256
        or final_checksum_bytes != metadata_checksum_bytes
    ):
        raise ValueError("release metadata changed during verification")
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(report) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_release(args.release, args.output, archive=args.archive)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
