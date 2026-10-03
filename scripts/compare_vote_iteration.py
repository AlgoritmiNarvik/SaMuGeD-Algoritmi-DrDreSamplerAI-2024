#!/usr/bin/env python3
"""Compare two exact implementations of aligned indexed vote construction."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import gc
from hashlib import sha256
import importlib.util
from itertools import chain
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
from typing import Callable

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.evaluate import generate_cases
from samuged.experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
    verify_completed_experiment,
)
from samuged.midi import load_midi


STUDY_VERSION = "vote-iteration-v1"
SYNTHETIC_CASES = 500
REAL_CASES = 128
BENCHMARK_SATURATED = 8
BENCHMARK_UNLIMITED = 8
BENCHMARK_REPETITIONS = 3
BASELINE_LINE = "group_votes = Counter(group for posting in postings for group in posting)"
CANDIDATE_LINE = "group_votes = Counter(chain.from_iterable(postings))"
RESULT_ARTIFACTS = ("aggregate.json", "raw_results.json")
EXPLICIT_DEPENDENCIES = (
    "scripts/compare_vote_iteration.py",
    "samuged/__init__.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/evaluate.py",
    "samuged/experiment.py",
    "samuged/metadata_recovery.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def candidate_source(source: str) -> str:
    """Return an exact one expression alternative to the current module."""
    if source.count(BASELINE_LINE) != 1:
        raise ValueError("baseline vote expression must occur exactly once")
    import_line = "from itertools import chain\n"
    if import_line in source:
        raise ValueError("baseline unexpectedly imports itertools.chain")
    anchor = "from dataclasses import asdict\n"
    if source.count(anchor) != 1:
        raise ValueError("candidate import anchor differs")
    return source.replace(anchor, anchor + import_line).replace(BASELINE_LINE, CANDIDATE_LINE)


def write_candidate(output: Path, baseline_path: Path) -> Path:
    target = output / "candidate" / "aligned_indexed_vote_chain.py"
    target.parent.mkdir(parents=True, exist_ok=False)
    target.write_text(candidate_source(baseline_path.read_text()))
    return target


def load_candidate(path: Path):
    """Load the copied module under the samuged package for relative imports."""
    name = "samuged._vote_iteration_candidate"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("candidate module spec is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def generator_votes(postings) -> Counter:
    return Counter(group for posting in postings for group in posting)


def chain_votes(postings) -> Counter:
    return Counter(chain.from_iterable(postings))


def _hash_rank(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def select_real_cohort(manifest: Path, expected: int = REAL_CASES) -> tuple[list[dict], list[str]]:
    rows = [json.loads(line) for line in manifest.read_text().split("\n") if line.strip()]
    rows = [row for row in rows if row.get("status") == "ok"]
    if len(rows) != expected or len({row["source_path"] for row in rows}) != expected:
        raise ValueError(f"expected {expected} unique successful real pilot rows")
    cohort = []
    for row in sorted(rows, key=lambda item: item["source_path"]):
        saturation = sum(
            int(part.get("saturated_seed_buckets", 0)) for part in row.get("part_stats", [])
        )
        cohort.append(
            {
                "case_id": f"real-{_hash_rank(row['source_path'])[:16]}",
                "cohort": "fixed_real",
                "source_path": row["source_path"],
                "source_sha256": row["source_sha256"],
                "source_bytes": row["source_bytes"],
                "metadata_repairs": row.get("metadata_repairs", []),
                "pilot_saturated_seed_buckets": saturation,
                "pilot_seed_postings_dropped": sum(
                    int(part.get("saturated_seed_postings_dropped", 0))
                    for part in row.get("part_stats", [])
                ),
                "hash_rank": _hash_rank(row["source_path"]),
            }
        )
    saturated = sorted(
        (row for row in cohort if row["pilot_saturated_seed_buckets"]),
        key=lambda row: (row["hash_rank"], row["source_path"]),
    )[:BENCHMARK_SATURATED]
    unlimited = sorted(
        (row for row in cohort if not row["pilot_saturated_seed_buckets"]),
        key=lambda row: (row["hash_rank"], row["source_path"]),
    )[:BENCHMARK_UNLIMITED]
    benchmark_ids = [row["case_id"] for row in [*saturated, *unlimited]]
    if len(saturated) != BENCHMARK_SATURATED or len(unlimited) != BENCHMARK_UNLIMITED:
        raise ValueError("benchmark cohort requires eight saturated and eight unlimited files")
    return cohort, benchmark_ids


def development_cases(count: int = SYNTHETIC_CASES) -> list:
    cases = [case for case in generate_cases(count * 2) if case.split == "development"]
    if len(cases) != count or any(case.split != "development" for case in cases):
        raise ValueError("development case construction differs")
    return cases


def _validate_sources(source: Path, cohort: list[dict]) -> None:
    root = source.resolve(strict=True)
    for row in cohort:
        path = (root / row["source_path"]).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("real source path escapes source root")
        if path.stat().st_size != row["source_bytes"] or _file_sha256(path) != row["source_sha256"]:
            raise ValueError(f"real source changed: {row['source_path']}")


def _nonruntime_result(result: dict) -> dict:
    return result


def compare_results(baseline: dict, candidate: dict) -> dict:
    baseline_phrases = baseline.get("phrases")
    candidate_phrases = candidate.get("phrases")
    baseline_stats = baseline.get("part_stats")
    candidate_stats = candidate.get("part_stats")
    return {
        "complete_equal": canonical_json(_nonruntime_result(baseline))
        == canonical_json(_nonruntime_result(candidate)),
        "phrases_equal": canonical_json(baseline_phrases) == canonical_json(candidate_phrases),
        "telemetry_equal": canonical_json(baseline_stats) == canonical_json(candidate_stats),
        "baseline_result_sha256": sha256_json(_nonruntime_result(baseline)),
        "candidate_result_sha256": sha256_json(_nonruntime_result(candidate)),
        "baseline_phrases_sha256": sha256_json(baseline_phrases),
        "candidate_phrases_sha256": sha256_json(candidate_phrases),
        "baseline_telemetry_sha256": sha256_json(baseline_stats),
        "candidate_telemetry_sha256": sha256_json(candidate_stats),
    }


def _run_pair(song, config, order: tuple[str, str], detectors: dict[str, Callable]) -> dict:
    results = {}
    elapsed = {}
    for name in order:
        started = time.perf_counter()
        results[name] = detectors[name](song, config)
        elapsed[name] = round(time.perf_counter() - started, 9)
    return {
        "execution_order": list(order),
        "elapsed_seconds": elapsed,
        "comparison": compare_results(results["baseline"], results["chain"]),
    }


def _alternating_order(index: int) -> tuple[str, str]:
    return ("baseline", "chain") if index % 2 == 0 else ("chain", "baseline")


def _full_correctness(
    synthetic: list,
    real: list[dict],
    source: Path,
    config: AlignedConfig,
    detectors: dict[str, Callable],
) -> list[dict]:
    rows = []
    for index, case in enumerate(synthetic):
        rows.append(
            {
                "case_id": case.case_id,
                "cohort": "development",
                "kind": case.kind,
                **_run_pair(case.song, config, _alternating_order(index), detectors),
            }
        )
        if (index + 1) % 100 == 0:
            print(json.dumps({"development_compared": index + 1, "total": len(synthetic)}), flush=True)
    offset = len(synthetic)
    for index, row in enumerate(real):
        song = load_midi(
            source / row["source_path"],
            recover_invalid_keys=bool(row["metadata_repairs"]),
        )
        if song.metadata_repairs != row["metadata_repairs"]:
            raise ValueError(f"metadata repairs changed: {row['source_path']}")
        rows.append(
            {
                **row,
                **_run_pair(song, config, _alternating_order(offset + index), detectors),
            }
        )
        if (index + 1) % 16 == 0:
            print(json.dumps({"real_compared": index + 1, "total": len(real)}), flush=True)
    return rows


def _timing_benchmark(
    real: list[dict],
    benchmark_ids: list[str],
    source: Path,
    config: AlignedConfig,
    detectors: dict[str, Callable],
) -> dict:
    selected = [next(row for row in real if row["case_id"] == case_id) for case_id in benchmark_ids]
    songs = []
    for row in selected:
        songs.append((row, load_midi(source / row["source_path"], recover_invalid_keys=bool(row["metadata_repairs"]))))
    warmup = []
    for case_index, (row, song) in enumerate(songs):
        pair = _run_pair(song, config, _alternating_order(case_index), detectors)
        if not pair["comparison"]["complete_equal"]:
            raise ValueError(f"warmup semantics differ: {row['source_path']}")
        warmup.append({"case_id": row["case_id"], "order": pair["execution_order"]})
    rows = []
    for repetition in range(BENCHMARK_REPETITIONS):
        for case_index, (row, song) in enumerate(songs):
            pair = _run_pair(
                song,
                config,
                _alternating_order(repetition + case_index),
                detectors,
            )
            if not pair["comparison"]["complete_equal"]:
                raise ValueError(f"timing semantics differ: {row['source_path']}")
            rows.append(
                {
                    "repetition": repetition + 1,
                    "case_id": row["case_id"],
                    "source_path": row["source_path"],
                    "saturated": bool(row["pilot_saturated_seed_buckets"]),
                    "execution_order": pair["execution_order"],
                    "elapsed_seconds": pair["elapsed_seconds"],
                }
            )
    by_name = {
        name: [row["elapsed_seconds"][name] for row in rows]
        for name in ("baseline", "chain")
    }
    ratios = [
        row["elapsed_seconds"]["chain"] / row["elapsed_seconds"]["baseline"]
        for row in rows
        if row["elapsed_seconds"]["baseline"] > 0
    ]
    differences = [
        row["elapsed_seconds"]["chain"] - row["elapsed_seconds"]["baseline"]
        for row in rows
    ]
    summary = {
        name: {
            "calls": len(values),
            "total_seconds": round(sum(values), 9),
            "mean_seconds": round(statistics.mean(values), 9),
            "median_seconds": round(statistics.median(values), 9),
        }
        for name, values in by_name.items()
    }
    summary["paired"] = {
        "median_ratio_chain_over_baseline": round(statistics.median(ratios), 9),
        "mean_difference_seconds": round(statistics.mean(differences), 9),
        "median_difference_seconds": round(statistics.median(differences), 9),
        "chain_faster_calls": sum(value < 0 for value in differences),
        "baseline_faster_calls": sum(value > 0 for value in differences),
        "ties": sum(value == 0 for value in differences),
    }
    return {"warmup": warmup, "rows": rows, "summary": summary}


def _vote_microbenchmark() -> dict:
    shapes = (
        (6, 24, 32),
        (12, 96, 128),
        (18, 192, 256),
    )
    rows = []
    for shape_index, (posting_count, posting_size, modulus) in enumerate(shapes):
        postings = [
            [(posting * 17 + item * 7) % modulus for item in range(posting_size)]
            for posting in range(posting_count)
        ]
        if generator_votes(postings) != chain_votes(postings):
            raise ValueError("vote multiset differs")
        loops = max(300, 200_000 // (posting_count * posting_size))
        for repetition in range(7):
            order = _alternating_order(shape_index + repetition)
            elapsed = {}
            for name in order:
                function = generator_votes if name == "baseline" else chain_votes
                started = time.perf_counter()
                for _ in range(loops):
                    function(postings)
                elapsed[name] = time.perf_counter() - started
            rows.append(
                {
                    "posting_count": posting_count,
                    "posting_size": posting_size,
                    "items_per_call": posting_count * posting_size,
                    "loops": loops,
                    "repetition": repetition + 1,
                    "execution_order": list(order),
                    "elapsed_seconds": {key: round(value, 9) for key, value in elapsed.items()},
                }
            )
    baseline = sum(row["elapsed_seconds"]["baseline"] for row in rows)
    candidate = sum(row["elapsed_seconds"]["chain"] for row in rows)
    return {
        "rows": rows,
        "summary": {
            "baseline_total_seconds": round(baseline, 9),
            "chain_total_seconds": round(candidate, 9),
            "ratio_chain_over_baseline": round(candidate / baseline, 9),
        },
    }


def _python_peak_memory(song, config, detectors: dict[str, Callable]) -> dict:
    result = {}
    for name in ("baseline", "chain"):
        gc.collect()
        tracemalloc.start()
        found = detectors[name](song, config)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result[name] = {
            "current_bytes_before_result_release": current,
            "peak_traced_bytes": peak,
            "result_sha256": sha256_json(found),
        }
        del found
    return result


def _concurrent_builds() -> list[str]:
    result = subprocess.run(
        ["ps", "-axo", "command="], capture_output=True, text=True, check=True
    )
    markers = ("samuged.cli build", "corpus_runner")
    return sorted(line.strip() for line in result.stdout.splitlines() if any(marker in line for marker in markers))


def run(source: Path, manifest: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    baseline_path = repository / "samuged" / "aligned_indexed.py"
    copied_candidate = write_candidate(output, baseline_path)

    synthetic = development_cases()
    real, benchmark_ids = select_real_cohort(manifest)
    _validate_sources(source, real)
    config = AlignedConfig()
    candidate_hash = _file_sha256(copied_candidate)
    baseline_hash = _file_sha256(baseline_path)
    concurrent = _concurrent_builds()
    experiment = output / "experiment"
    candidate_relative = copied_candidate.relative_to(repository).as_posix()
    design = {
        "study_version": STUDY_VERSION,
        "change": "replace nested generator iteration passed to Counter with itertools.chain.from_iterable",
        "semantic_requirement": "complete phrases and every nonruntime detector field must be identical",
        "correctness_cohorts": {
            "development": SYNTHETIC_CASES,
            "fixed_real": REAL_CASES,
        },
        "timing": {
            "benchmark_case_ids": benchmark_ids,
            "saturated_files": BENCHMARK_SATURATED,
            "unlimited_files": BENCHMARK_UNLIMITED,
            "warmup_passes": 1,
            "alternating_order_repetitions": BENCHMARK_REPETITIONS,
        },
        "memory": "one tracemalloc pass per variant on the first frozen saturated timing file",
        "concurrent_builds_at_freeze": concurrent,
        "result_artifacts": list(RESULT_ARTIFACTS),
        "claim_boundary": "local implementation timing under concurrent load, not an isolated production speed guarantee",
    }
    frozen_config = {
        "detector_config": asdict(config),
        "baseline_source": "samuged/aligned_indexed.py",
        "baseline_sha256": baseline_hash,
        "candidate_source": candidate_relative,
        "candidate_sha256": candidate_hash,
        "candidate_replacement": {"from": BASELINE_LINE, "to": CANDIDATE_LINE},
        "pilot_manifest": manifest.as_posix(),
        "pilot_manifest_sha256": _file_sha256(manifest),
        "source_root": source.as_posix(),
    }
    required = (*EXPLICIT_DEPENDENCIES, candidate_relative)
    receipt = prepare_experiment(
        experiment,
        design=design,
        config=frozen_config,
        cases=[*synthetic, *real],
        required_files=required,
    )
    links = receipt_links(receipt)
    snapshot_candidate = experiment / "source_snapshot" / candidate_relative
    if _file_sha256(snapshot_candidate) != candidate_hash:
        raise ValueError("frozen candidate differs from precommitted hash")
    candidate_module = load_candidate(snapshot_candidate)
    detectors = {"baseline": extract_indexed, "chain": candidate_module.extract_indexed}

    correctness = _full_correctness(synthetic, real, source, config, detectors)
    failures = [row for row in correctness if not row["comparison"]["complete_equal"]]
    benchmark = _timing_benchmark(real, benchmark_ids, source, config, detectors)
    micro = _vote_microbenchmark()
    memory_row = next(row for row in real if row["case_id"] == benchmark_ids[0])
    memory_song = load_midi(
        source / memory_row["source_path"],
        recover_invalid_keys=bool(memory_row["metadata_repairs"]),
    )
    memory = {
        "case_id": memory_row["case_id"],
        "source_path": memory_row["source_path"],
        "measurement": _python_peak_memory(memory_song, config, detectors),
    }
    raw = {
        **links,
        "study_version": STUDY_VERSION,
        "correctness_rows": correctness,
        "timing_benchmark": benchmark,
        "vote_microbenchmark": micro,
        "python_peak_memory": memory,
    }
    _write_json(experiment / "raw_results.json", raw)
    groups = {}
    for cohort in ("development", "fixed_real"):
        rows = [row for row in correctness if row["cohort"] == cohort]
        groups[cohort] = {
            "cases": len(rows),
            "complete_equal": sum(row["comparison"]["complete_equal"] for row in rows),
            "phrase_equal": sum(row["comparison"]["phrases_equal"] for row in rows),
            "telemetry_equal": sum(row["comparison"]["telemetry_equal"] for row in rows),
            "mismatches": [row["case_id"] for row in rows if not row["comparison"]["complete_equal"]],
        }
    aggregate = {
        **links,
        "study_version": STUDY_VERSION,
        "candidate": {
            "baseline_sha256": baseline_hash,
            "candidate_sha256": candidate_hash,
            "copied_source": candidate_relative,
        },
        "correctness": groups,
        "correctness_failures": len(failures),
        "timing": benchmark["summary"],
        "vote_microbenchmark": micro["summary"],
        "python_peak_memory": memory,
        "concurrent_builds_at_freeze": concurrent,
        "decision_rule": "do not propose a default change unless exact equality holds and repeated timing shows a material consistent benefit",
    }
    _write_json(experiment / "aggregate.json", aggregate)
    complete_experiment(experiment)
    verify_completed_experiment(experiment)
    return aggregate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.source, args.manifest, args.output)
    print(json.dumps(result, indent=2))
    return 1 if result["correctness_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
