"""Re-extract a deterministic, receipt-bound sample from a full dataset build.

This replays a bounded sample or every saved successful source record. It requires a
passed full manifest audit with current bound inputs before selecting cases and
writes a separate experiment receipt, so it does not change the dataset's own
audit artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import platform
import time
from typing import Any

from samuged import experiment
from samuged import audit as dataset_audit
from samuged.dataset import canonical_json, runtime_metadata


VERSION = "selection-sample-audit-v1"
DEFAULT_COUNT = 256
DEFAULT_WORKERS = 4
DEFAULT_SEED = 20261003
MAX_COUNT = 50000
MAX_WORKERS = 32
MAX_FAILURE_REASONS = 16
MAX_REASON_LENGTH = 240

_COMMON_DETECTOR_MODULES = ("samuged/__init__.py", "samuged/midi.py", "samuged/metadata_recovery.py")


def _json_sha256(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object rows: {path}")
            rows.append(value)
    return rows


def _artifact_hashes(dataset: Path) -> dict[str, dict[str, Any]]:
    names = ("sources.jsonl", "phrases.jsonl", "build_config.json", "summary.json", "audit.json")
    result = {}
    for name in names:
        path = dataset / name
        data = path.read_bytes()
        result[name] = {"bytes": len(data), "sha256": _bytes_sha256(data)}
    return result


def _safe_source(source: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("source path is missing")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ValueError(f"unsafe source path: {relative}")
    path = (source / pure).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(source.resolve()):
        raise ValueError(f"source path escapes source root: {relative}")
    return path


def _algorithm_modules(config: dict[str, Any]) -> tuple[str, ...]:
    algorithm = config.get("algorithm", "reference")
    modules = set(_COMMON_DETECTOR_MODULES)
    if algorithm == "reference":
        modules.add("samuged/phrases.py")
    elif algorithm == "aligned":
        modules.update(("samuged/phrases.py", "samuged/aligned.py"))
    elif algorithm == "aligned_indexed":
        modules.update(("samuged/phrases.py", "samuged/aligned.py", "samuged/aligned_indexed.py"))
    elif algorithm == "aligned_closed":
        modules.update((
            "samuged/phrases.py", "samuged/aligned.py", "samuged/aligned_indexed.py",
            "samuged/closed_patterns.py",
        ))
    elif algorithm == "aligned_melody":
        modules.update((
            "samuged/phrases.py", "samuged/aligned.py", "samuged/aligned_indexed.py",
            "samuged/closed_patterns.py", "samuged/part_ranking.py",
        ))
    else:
        raise ValueError(f"unsupported dataset algorithm: {algorithm}")
    if config.get("percussion"):
        modules.add("samuged/drums.py")
    return tuple(sorted(modules))


def _verify_current_detector_modules(dataset: Path, config: dict[str, Any]) -> tuple[str, ...]:
    repository = Path(__file__).resolve().parents[1]
    provenance = dataset / "provenance"
    required = _algorithm_modules(config)
    for relative in required:
        current = repository / relative
        frozen = provenance / relative
        if not current.is_file() or not frozen.is_file():
            raise ValueError(f"detector provenance module missing: {relative}")
        if current.read_bytes() != frozen.read_bytes():
            raise ValueError(
                f"current detector module differs from dataset provenance: {relative}"
            )
    return required


def _validate_full_build(dataset: Path, source: Path) -> dict[str, Any]:
    dataset = dataset.resolve(strict=True)
    source = source.resolve(strict=True)
    config = _read_json(dataset / "build_config.json")
    summary = _read_json(dataset / "summary.json")
    saved_audit = _read_json(dataset / "audit.json")
    artifacts = _artifact_hashes(dataset)
    if saved_audit.get("passed") is not True or saved_audit.get("failure_count") != 0:
        raise ValueError("saved dataset audit is not passed")
    if saved_audit.get("full_source_coverage_required") is not True:
        raise ValueError("saved dataset audit is not a full coverage audit")
    for field, filename in (
        ("source_manifest_sha256", "sources.jsonl"),
        ("phrase_manifest_sha256", "phrases.jsonl"),
        ("build_config_sha256", "build_config.json"),
        ("summary_sha256", "summary.json"),
    ):
        if saved_audit.get(field) != artifacts[filename]["sha256"]:
            raise ValueError(f"saved audit {field} is stale")
    if config.get("cohort_limit") is not None:
        raise ValueError("full sample audit requires an unlimited source cohort")
    if config.get("selected_source_files") != config.get("discovered_source_files"):
        raise ValueError("dataset build does not cover all discovered sources")
    if summary.get("source_files") != config.get("discovered_source_files"):
        raise ValueError("summary source count is not full scope")
    if saved_audit.get("run_key") != config.get("run_key"):
        raise ValueError("saved audit run key differs from build config")
    if summary.get("run_key") != config.get("run_key"):
        raise ValueError("summary run key differs from build config")
    if config.get("python") != platform.python_version():
        raise ValueError("recorded Python runtime differs from current runtime")
    if isinstance(config.get("runtime"), dict) and config["runtime"] != runtime_metadata():
        raise ValueError("recorded runtime fingerprint differs from current runtime")
    required_modules = _verify_current_detector_modules(dataset, config)

    records = _read_jsonl(dataset / "sources.jsonl")
    if len(records) != config.get("discovered_source_files"):
        raise ValueError("source manifest count differs from full build")
    discovered = {
        path.relative_to(source).as_posix()
        for path in dataset_audit.discover(source)
    }
    manifest_paths = {row.get("source_path") for row in records}
    if manifest_paths != discovered:
        raise ValueError("current source inventory differs from full audit manifest")
    return {
        "dataset": dataset,
        "source": source,
        "config": config,
        "summary": summary,
        "audit": saved_audit,
        "saved_audit": saved_audit,
        "artifacts": artifacts,
        "records": records,
        "required_modules": required_modules,
    }


def _record_key(record: dict[str, Any], seed: int) -> tuple[str, str, str]:
    source_hash = str(record.get("source_sha256", ""))
    source_id = str(record.get("source_id", ""))
    salted = f"{VERSION}:{seed}:{source_hash}:{source_id}".encode("utf-8")
    return (_bytes_sha256(salted), source_hash, source_id)


def _limited(record: dict[str, Any]) -> bool:
    return bool(record.get("search_limited") or record.get("drum_stats", {}).get("search_limited"))


def _select_records(
    records: list[dict[str, Any]], count: int | None, seed: int = DEFAULT_SEED,
    *, all_successful: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not all_successful and (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT):
        raise ValueError(f"count must be between 1 and {MAX_COUNT}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    successful_count = sum(row.get("status") == "ok" for row in records)
    error_count = sum(row.get("status") == "error" for row in records)
    eligible = [
        row for row in records
        if row.get("status") == "ok"
        and row.get("outcome") in {"matched", "no_match"}
        and isinstance(row.get("source_sha256"), str)
        and len(row["source_sha256"]) == 64
        and all(char in "0123456789abcdef" for char in row["source_sha256"])
    ]
    if all_successful and (len(eligible) != successful_count or successful_count + error_count != len(records)):
        raise ValueError("all-successful scope contains malformed or unsupported manifest rows")
    if all_successful and not eligible:
        raise ValueError("all-successful scope has no successful sources")
    if all_successful and len(eligible) > MAX_COUNT:
        raise ValueError(f"all-successful cohort exceeds the {MAX_COUNT} source cap")
    ordered = sorted(eligible, key=lambda row: _record_key(row, seed))
    if all_successful:
        count = len(ordered)
    assert count is not None
    recovered = [row for row in ordered if bool(row.get("metadata_repairs"))]
    selected = list(ordered if all_successful else recovered[:count])
    remaining = count - len(selected)
    selected_ids = {row["source_id"] for row in selected}
    pool = [] if all_successful else [row for row in ordered if row["source_id"] not in selected_ids]
    strata_pool = ordered if all_successful else pool
    limited = [row for row in strata_pool if _limited(row)]
    unlimited = [row for row in strata_pool if not _limited(row)]
    if remaining and not all_successful:
        take_limited = min(len(limited), (remaining + 1) // 2)
        take_unlimited = min(len(unlimited), remaining - take_limited)
        if take_limited + take_unlimited < remaining:
            extra = remaining - take_limited - take_unlimited
            take_limited += min(extra, len(limited) - take_limited)
            take_unlimited += min(extra - min(extra, len(limited) - take_limited), len(unlimited) - take_unlimited)
        selected.extend(limited[:take_limited])
        selected.extend(unlimited[:take_unlimited])
    selected = sorted(selected, key=lambda row: _record_key(row, seed))
    if len(selected) != count:
        raise ValueError(f"requested {count} successful sources but only {len(selected)} are eligible")
    strata = Counter(
        "metadata_recovered" if row.get("metadata_repairs")
        else "search_limited" if _limited(row)
        else "not_search_limited"
        for row in selected
    )
    return selected, {
        "seed": seed,
        "count": count,
        "selection_mode": "all_successful" if all_successful else "bounded_sample",
        "selection_covers_all_successful_sources": all_successful,
        "total_manifest_sources": len(records),
        "successful_source_count": successful_count,
        "error_source_count": error_count,
        "eligible_successful_sources": len(eligible),
        "eligible_metadata_recovered": len(recovered),
        "eligible_search_limited": len(limited),
        "eligible_not_search_limited": len(unlimited),
        "strata_counts": dict(sorted(strata.items())),
        "search_limit_scope": "melodic or percussion search limit",
        "policy": (
            "sort successful source records by a deterministic hash of seed, source_sha256 "
            "and source_id; select metadata-recovered records first then fill remaining "
            "slots with a balanced search-limited/not-search-limited selection"
            if not all_successful else
            "replay every eligible successful source in deterministic hash order; manifest "
            "error rows remain outside this cohort"
        ),
    }


def _bounded_reasons(problems: list[str]) -> list[str]:
    return [str(problem)[:MAX_REASON_LENGTH] for problem in problems[:MAX_FAILURE_REASONS]]


def _evidence_sha256(record: dict[str, Any]) -> str:
    keys = (
        "algorithm", "config", "phrases", "part_stats", "drum_stats", "search_limited",
        "curation_truncated", "part_ranking", "selection_trace", "closed_extension_count",
        "selection", "matcher_flags",
    )
    return _json_sha256({key: record.get(key) for key in keys})


def _run_one(
    source: Path,
    record: dict[str, Any],
    config: dict[str, Any],
    stratum: str,
) -> dict[str, Any]:
    started = time.monotonic()
    source_id = record.get("source_id")
    result = {
        "source_id": source_id,
        "source_path": record.get("source_path"),
        "source_sha256": record.get("source_sha256"),
        "source_bytes": record.get("source_bytes"),
        "stratum": stratum,
        "record_sha256": _json_sha256(record),
        "detector_evidence_sha256": _evidence_sha256(record),
        "metadata_repairs": record.get("metadata_repairs", []),
        "metadata_recovered": bool(record.get("metadata_repairs")),
        "status": "failed",
        "failures": [],
    }
    failures: list[str] = []
    try:
        path = _safe_source(source, record.get("source_path"))
        data = path.read_bytes()
        if len(data) != record.get("source_bytes") or _bytes_sha256(data) != record.get("source_sha256"):
            raise ValueError("source bytes or hash differs from selected manifest")
        recover = config.get("recover_invalid_keys", False) is True
        song = dataset_audit.load_midi(path, recover_invalid_keys=recover)
        if song.metadata_repairs != record.get("metadata_repairs", []):
            failures.append("metadata repair receipt differs")
        if ("metadata_repairs" in record) != bool(song.metadata_repairs):
            failures.append("metadata repair receipt presence differs")
        if song.warnings != record.get("warnings", []):
            failures.append("source warnings differ")
        failures.extend(dataset_audit._reextract_record(song, record, config))
        algorithm = config.get("algorithm", "reference")
        if algorithm == "aligned_closed":
            last_tick = max((note.end for part in song.parts for note in part.notes), default=0)
            failures.extend(dataset_audit.verify_closed_trace(record, config["config"], last_tick))
            result["closed_trace_checked"] = True
        else:
            result["closed_trace_checked"] = False
        if algorithm == "aligned_melody":
            failures.extend(dataset_audit.verify_part_ranking(record, song, config["config"].get("top_k")))
            result["part_ranking_checked"] = True
        else:
            result["part_ranking_checked"] = False
        if _bytes_sha256(path.read_bytes()) != record.get("source_sha256"):
            failures.append("source bytes changed during re-extraction")
    except Exception as exc:  # each selected source is accounted for
        failures.append(f"{type(exc).__name__}: {exc}")
    result["failures"] = _bounded_reasons(failures)
    result["status"] = "passed" if not failures else "failed"
    result["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return result


def _write_json(path: Path, value: object) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return data


def run_sample(
    dataset: Path,
    source: Path,
    output: Path,
    *,
    count: int | None = DEFAULT_COUNT,
    workers: int = DEFAULT_WORKERS,
    seed: int = DEFAULT_SEED,
    all_successful: bool = False,
) -> dict[str, Any]:
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    context = _validate_full_build(dataset, source)
    records, selection_meta = _select_records(
        context["records"], count, seed, all_successful=all_successful
    )
    count = selection_meta["count"]
    selected = []
    for row in records:
        source_path = _safe_source(context["source"], row.get("source_path"))
        data = source_path.read_bytes()
        if len(data) != row.get("source_bytes") or _bytes_sha256(data) != row.get("source_sha256"):
            raise ValueError(f"selected source changed before receipt: {row.get('source_id')}")
        stratum = (
            "metadata_recovered" if row.get("metadata_repairs")
            else "search_limited" if _limited(row)
            else "not_search_limited"
        )
        selected.append({
            "source_id": row["source_id"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_bytes": row["source_bytes"],
            "record_sha256": _json_sha256(row),
            "detector_evidence_sha256": _evidence_sha256(row),
            "status": row["status"],
            "outcome": row["outcome"],
            "metadata_repairs": row.get("metadata_repairs", []),
            "metadata_recovered": bool(row.get("metadata_repairs")),
            "search_limited": bool(row.get("search_limited")),
            "percussion_search_limited": bool(row.get("drum_stats", {}).get("search_limited")),
            "stratum": stratum,
        })
    selection_body = {
        "version": VERSION,
        "dataset_artifacts": context["artifacts"],
        "dataset_run_key": context["config"].get("run_key"),
        "dataset_algorithm": context["config"].get("algorithm", "reference"),
        "full_audit": {
            "passed": True,
            "source_files": context["audit"].get("source_files"),
            "full_source_coverage_required": True,
            "source_manifest_sha256": context["artifacts"]["sources.jsonl"]["sha256"],
            "phrase_manifest_sha256": context["artifacts"]["phrases.jsonl"]["sha256"],
            "build_config_sha256": context["artifacts"]["build_config.json"]["sha256"],
            "summary_sha256": context["artifacts"]["summary.json"]["sha256"],
        },
        "selection": selection_meta,
        "selected": selected,
    }
    selection_sha256 = _json_sha256(selection_body)
    detector_config = {
        "algorithm": context["config"].get("algorithm", "reference"),
        "config": context["config"].get("config"),
        "percussion": context["config"].get("percussion", False),
        "recover_invalid_keys": context["config"].get("recover_invalid_keys", False),
    }
    claim_boundary = (
        "all successful sources re-extracted; parse errors excluded; no musical quality claim"
        if all_successful else
        "bounded selected-source re-extraction only; no full corpus or quality claim"
    )
    config = {
        "version": VERSION,
        "seed": seed,
        "count": count,
        "selection_mode": selection_meta["selection_mode"],
        "all_successful": all_successful,
        "workers": workers,
        "dataset_run_key": context["config"].get("run_key"),
        "dataset_artifacts": context["artifacts"],
        "detector": detector_config,
        "required_detector_modules": list(context["required_modules"]),
        "selection_sha256": selection_sha256,
        "claim_boundary": claim_boundary,
    }
    design = {
        "version": VERSION,
        "dataset_algorithm": detector_config["algorithm"],
        "dataset_run_key": context["config"].get("run_key"),
        "dataset_artifacts": context["artifacts"],
        "selection_sha256": selection_sha256,
        "selection": selection_meta,
        "required_detector_modules": list(context["required_modules"]),
        "result_artifacts": ["aggregate.json", "design.json", "raw_results.json", "selection.json"],
        "claim_boundary": claim_boundary,
    }
    output = output.resolve()
    receipt = experiment.prepare_experiment(
        output,
        design=design,
        config=config,
        cases=selected,
        required_files=["scripts/audit_selection_sample.py", "samuged/audit.py", *context["required_modules"], "samuged/experiment.py"],
    )
    links = experiment.receipt_links(receipt)
    selection_payload = {**selection_body, "selection_sha256": selection_sha256, **links}
    _write_json(output / "selection.json", selection_payload)
    started = time.monotonic()
    by_id = {row["source_id"]: row for row in records}
    tasks = [
        (context["source"], by_id[item["source_id"]], context["config"], item["stratum"])
        for item in selected
    ]
    rows = []
    if workers == 1:
        for completed, task in enumerate(tasks, 1):
            rows.append(_run_one(*task))
            if completed % 100 == 0:
                print(f"replayed {completed}/{len(tasks)} sources", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_one, *task): index for index, task in enumerate(tasks)}
            for completed, future in enumerate(as_completed(futures), 1):
                rows.append(future.result())
                if completed % 100 == 0:
                    print(f"replayed {completed}/{len(tasks)} sources", flush=True)
    if _artifact_hashes(context["dataset"]) != context["artifacts"]:
        raise ValueError("dataset artifacts changed during sample re-extraction")
    _verify_current_detector_modules(context["dataset"], context["config"])
    rows.sort(key=lambda row: (str(row.get("source_sha256")), str(row.get("source_id"))))
    failures = [row for row in rows if row["status"] != "passed"]
    raw = {
        "version": VERSION,
        **links,
        "selection_sha256": selection_sha256,
        "count": count,
        "selection_mode": selection_meta["selection_mode"],
        "selection_covers_all_successful_sources": selection_meta["selection_covers_all_successful_sources"],
        "workers": workers,
        "cases": rows,
        "failure_count": len(failures),
        "claim_boundary": config["claim_boundary"],
    }
    aggregate = {
        "version": VERSION,
        **links,
        "selection_sha256": selection_sha256,
        "count": count,
        "selection_mode": selection_meta["selection_mode"],
        "selection_covers_all_successful_sources": selection_meta["selection_covers_all_successful_sources"],
        "total_manifest_sources": selection_meta["total_manifest_sources"],
        "successful_source_count": selection_meta["successful_source_count"],
        "error_source_count": selection_meta["error_source_count"],
        "passed_count": len(rows) - len(failures),
        "failure_count": len(failures),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "strata_counts": dict(Counter(row["stratum"] for row in rows)),
        "worker_seconds": round(sum(row["elapsed_seconds"] for row in rows), 6),
        "wall_seconds": round(time.monotonic() - started, 6),
        "claim_boundary": config["claim_boundary"],
    }
    config["selection_sha256"] = selection_sha256
    design_record = {
        **links,
        "design_sha256": experiment.sha256_json(design),
        "config": config,
        "design": design,
        **design,
    }
    _write_json(output / "design.json", design_record)
    _write_json(output / "raw_results.json", raw)
    _write_json(output / "aggregate.json", aggregate)
    experiment.complete_experiment(output)
    return {**aggregate, "output": str(output), "runtime_seconds": round(time.monotonic() - started, 6)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument(
        "--all-successful", action="store_true",
        help="replay every successful source; cannot be combined with --count",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    if args.all_successful and args.count is not None:
        parser.error("--all-successful cannot be combined with --count")
    count = DEFAULT_COUNT if args.count is None and not args.all_successful else args.count
    result = run_sample(
        args.dataset, args.source, args.output, count=count, workers=args.workers,
        seed=args.seed, all_successful=args.all_successful,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("failure_count") else 0


if __name__ == "__main__":
    raise SystemExit(main())
