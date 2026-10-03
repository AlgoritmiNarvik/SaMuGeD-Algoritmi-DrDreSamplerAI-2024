"""Compare the exact-representative cache with a saved reference implementation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
import time

from samuged.dataset import atomic_json, file_digest
from samuged.evaluate import generate_cases, score_case, aggregate_results
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links
from samuged.midi import load_midi
from samuged.phrases import Config, extract


def run(source: Path, manifest: Path, baseline: Path, output: Path) -> dict:
    repository = Path(__file__).resolve().parents[1]
    baseline = baseline.resolve(strict=True)
    baseline_relative = baseline.relative_to(repository).as_posix()
    cases = [case for case in generate_cases(1000) if case.split == "development"]
    sources = [json.loads(line) for line in manifest.read_text().split("\n") if line.strip()]
    files = [{"source_path": row["source_path"], "source_sha256": row["source_sha256"]} for row in sources]
    config = Config(top_k=10)
    receipt = prepare_experiment(output, design={
        "purpose": "fixed-representative exact cache, differential development diagnostic",
        "baseline_sha256": file_digest(baseline), "real_source_manifest_sha256": file_digest(manifest),
        "real_sources": files, "synthetic_split": "development", "changes_expected_when_search_limited": True,
        "method_order": "alternates reference-first and cached-first by case index",
    }, config={"synthetic": asdict(config), "corpus": asdict(Config())},
        cases=[{"kind": "synthetic", **case.metadata()} for case in cases]
              + [{"kind": "source", **row} for row in files],
        required_files=("scripts/compare_cache.py", baseline_relative, "samuged/phrases.py",
                        "samuged/dataset.py", "samuged/midi.py", "samuged/evaluate.py",
                        "samuged/experiment.py", "pyproject.toml", "requirements-research.lock"))
    name = "samuged._cache_comparison_reference"
    spec = importlib.util.spec_from_file_location(name, output/"source_snapshot"/baseline_relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    rows = []
    synthetic = {"reference": [], "cached": []}

    def compare(label, song, cfg, case=None):
        results, times = {}, {}
        methods = [("reference", module.extract, module.Config(**asdict(cfg))),
                   ("cached", extract, cfg)]
        if len(rows) % 2:
            methods.reverse()
        for method, function, configuration in methods:
            start = time.monotonic()
            results[method] = function(song, configuration)
            times[method] = time.monotonic()-start
            if case is not None:
                synthetic[method].append(score_case(case, results[method]["phrases"], times[method]))
        row = {"case_id": label, "kind": "synthetic" if case else "source",
               "phrases_equal": results["reference"]["phrases"] == results["cached"]["phrases"],
               "methods": {}}
        for method, result in results.items():
            row["methods"][method] = {"runtime_seconds": times[method],
                 "phrases": len(result["phrases"]), "search_limited": result["search_limited"],
                 "comparisons": sum(p["comparisons"] for p in result["part_stats"]),
                 "exact_cache_hits": sum(p.get("exact_cache_hits", 0) for p in result["part_stats"])}
        if not row["phrases_equal"]:
            row["changed_phrases"] = {method: result["phrases"] for method, result in results.items()}
        rows.append(row)

    for case in cases:
        compare(case.case_id, case.song, config, case)
    for index, row in enumerate(files):
        path = source/row["source_path"]
        if file_digest(path) != row["source_sha256"]:
            raise ValueError("pilot source changed")
        compare(row["source_path"], load_midi(path), Config())
        if (index+1) % 16 == 0:
            print(json.dumps({"sources_processed": index+1, "total": len(files)}), flush=True)
    atomic_json(output/"raw_results.json", {**receipt_links(receipt), "rows": rows})
    groups = {}
    for kind in ("synthetic", "source"):
        selected = [row for row in rows if row["kind"] == kind]
        groups[kind] = {"cases": len(selected), "identical_phrase_outputs": sum(row["phrases_equal"] for row in selected),
                       "changed_with_reference_unlimited": sum(not row["phrases_equal"] and not row["methods"]["reference"]["search_limited"] for row in selected),
                       "methods": {}}
        for method in ("reference", "cached"):
            groups[kind]["methods"][method] = {key: sum(row["methods"][method][key] for row in selected)
                for key in ("runtime_seconds", "phrases", "search_limited", "comparisons", "exact_cache_hits")}
    result = {**receipt_links(receipt), "groups": groups,
              "development_scores": {key: aggregate_results(value) for key, value in synthetic.items()}}
    atomic_json(output/"aggregate.json", result)
    complete_experiment(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.manifest, args.baseline, args.output), indent=2))
