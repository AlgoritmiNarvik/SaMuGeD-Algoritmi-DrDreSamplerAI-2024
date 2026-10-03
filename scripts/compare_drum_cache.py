"""Differential development experiment for a saved drum matcher optimization."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
import time

from samuged.dataset import atomic_json, file_digest
from samuged.drum_stress import generate_cohort
from samuged.drums import DrumConfig
from samuged.evaluate_drums import generate_cases
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links
from samuged.midi import load_midi


def _module(path: Path, suffix: str):
    name = f"samuged._drum_comparison_{suffix}"
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def run(source: Path, manifest: Path, baseline: Path, candidate: Path,
        output: Path, *, synthetic_development: bool = False) -> dict:
    repository = Path(__file__).resolve().parents[1]
    baseline = baseline.resolve()
    candidate = candidate.resolve()
    config = asdict(DrumConfig())
    sources = [json.loads(line) for line in manifest.read_text().splitlines()]
    cases = []
    if synthetic_development:
        cases.extend(("easy_development", case) for case in generate_cases(1000)
                     if case.split == "development")
        stress, _ = generate_cohort(40)
        cases.extend(("stress_development", case) for case in stress
                     if case.split == "development")
    cohort = [{"kind": kind, **case.metadata()} for kind, case in cases]
    cohort.extend({"kind": "source", "source_path": row["source_path"],
                   "source_sha256": row["source_sha256"],
                   "manifest_status": row["status"]} for row in sources)
    baseline_relative = baseline.relative_to(repository).as_posix()
    candidate_relative = candidate.relative_to(repository).as_posix()
    required = (
        "scripts/compare_drum_cache.py", baseline_relative, candidate_relative,
        "samuged/__init__.py", "samuged/drums.py", "samuged/drum_stress.py",
        "samuged/evaluate_drums.py", "samuged/experiment.py", "samuged/midi.py",
        "samuged/metadata_recovery.py", "samuged/dataset.py", "samuged/phrases.py",
        "pyproject.toml", "requirements-research.lock",
    )
    receipt = prepare_experiment(output, design={
        "version": "drum-cache-differential-v1",
        "purpose": "fixed prototype exact cache equivalence and runtime diagnostic",
        "baseline_sha256": file_digest(baseline),
        "candidate_sha256": file_digest(candidate),
        "manifest_sha256": file_digest(manifest),
        "method_order": "alternates baseline-first and candidate-first by case index",
        "synthetic_split": "development only",
        "load_policy": "strict source load; opt into recovery only for recorded repairs",
        "promotion_rule": "no unbounded-output regression; inspect every changed limited case",
        "claim_boundary": "output equivalence and runtime, not perceptual quality",
    }, config=config, cases=cohort, required_files=required)
    modules = {
        "baseline": _module(output/"source_snapshot"/baseline_relative, "baseline"),
        "candidate": _module(output/"source_snapshot"/candidate_relative, "candidate"),
    }
    rows = []

    def compare(case_id, kind, song):
        results, timings = {}, {}
        order = ("baseline", "candidate") if len(rows) % 2 == 0 else ("candidate", "baseline")
        for method in order:
            module = modules[method]
            started = time.monotonic()
            results[method] = module.extract_drums(song, module.DrumConfig(**config))
            timings[method] = time.monotonic()-started
        equal = results["baseline"]["phrases"] == results["candidate"]["phrases"]
        row = {"case_id": case_id, "kind": kind, "phrases_equal": equal, "methods": {}}
        for method, result in results.items():
            stats = result["stats"]
            row["methods"][method] = {
                "runtime_seconds": timings[method], "phrase_count": len(result["phrases"]),
                "comparisons": stats["comparisons"],
                "exact_prototype_cache_hits": stats.get("exact_prototype_cache_hits", 0),
                "search_limited": stats["search_limited"],
                "comparison_limit_reached": stats["comparison_limit_reached"],
                "saturated_seed_buckets": stats["saturated_seed_buckets"],
            }
        if not equal:
            row["changed_phrases"] = {method: result["phrases"] for method, result in results.items()}
        rows.append(row)

    for kind, case in cases:
        compare(case.case_id, kind, case.song)
    errors = []
    for index, row in enumerate(sources):
        path = source/row["source_path"]
        if file_digest(path) != row["source_sha256"]:
            raise ValueError("source differs from frozen manifest")
        try:
            song = load_midi(path, recover_invalid_keys=bool(row.get("metadata_repairs")))
        except Exception as exc:
            if row["status"] != "error":
                raise
            errors.append({"source_path": row["source_path"], "error_type": type(exc).__name__})
        else:
            if song.metadata_repairs != row.get("metadata_repairs", []):
                raise ValueError("metadata recovery differs from manifest")
            compare(row["source_path"], "source", song)
        if (index+1) % 128 == 0:
            print(json.dumps({"sources_processed": index+1, "total": len(sources)}), flush=True)
    groups = {}
    for kind in sorted({row["kind"] for row in rows}):
        selected = [row for row in rows if row["kind"] == kind]
        groups[kind] = {
            "cases": len(selected),
            "identical_phrase_outputs": sum(row["phrases_equal"] for row in selected),
            "changed_with_baseline_unlimited": sum(
                not row["phrases_equal"] and not row["methods"]["baseline"]["search_limited"]
                for row in selected),
            "methods": {method: {key: sum(row["methods"][method][key] for row in selected)
                                   for key in selected[0]["methods"][method]}
                        for method in modules},
        }
    result = {**receipt_links(receipt), "groups": groups, "parse_errors": errors}
    atomic_json(output/"raw_results.json", {**receipt_links(receipt), "rows": rows})
    atomic_json(output/"aggregate.json", result)
    complete_experiment(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "manifest", "baseline", "candidate", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--synthetic-development", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(run(**vars(arguments)), indent=2))
