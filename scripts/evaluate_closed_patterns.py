"""Fresh synthetic and fixed real pilot study of optional closed-pattern selection."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics
import time

from samuged import aligned
from samuged import aligned_indexed
from samuged.closed_patterns import (
    CLOSED_PATTERN_VERSION,
    MIN_EXACT_SUPPORT,
    SCORE_MARGIN,
    select_closed_candidates_with_trace,
    select_original_candidates,
)
from samuged.evaluate import CASE_KINDS, IOU_THRESHOLD, _build_case, aggregate_results, score_case
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    verify_completed_experiment,
)
from samuged.midi import load_midi


STUDY_VERSION = "closed-patterns-fresh-v1"
FRESH_SEED_BASE = 30_000_000
FRESH_CASE_COUNT = 500
REAL_SOURCE_COUNT = 128
REAL_MANIFEST = Path("research_local/pilot_both_v03/sources.jsonl")
REAL_ROOT = Path("datasets/Lakh MIDI Clean")
ALGORITHMS = ("aligned", "aligned_indexed")
VARIANTS = ("original", "closed_exact_extension")
BASE_SOURCE_HASHES = {
    "samuged/aligned.py": "ef26d9aeeb4289cc97db88ca1eb3af3ccd87e58aad499d0484edb120b6153f76",
    "samuged/aligned_indexed.py": "afca9f7c8bf8e231d7b544cd0cb98f8c6e93e301ca1dea5939b0bae042b0eab6",
    "samuged/evaluate.py": "8bc79d2a936e353b2ef20fe081a5e3f0696fecb4300ba6eb300b148e1ee572ff",
    "samuged/midi.py": "e8d26ad2cbe2abbbcb40e2183083feb4ce20ac7787f19d4b20a76820214d97d7",
    "samuged/phrases.py": "ff5095d4bb95a35eafbdd6026aff9bc9af0cc7974e93f4d4b1dc7774c89c8c84",
}
REQUIRED_FILES = (
    "scripts/evaluate_closed_patterns.py",
    "samuged/closed_patterns.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/evaluate.py",
    "samuged/experiment.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "samuged/__init__.py",
    REAL_MANIFEST.as_posix(),
    "pyproject.toml",
    "requirements-research.lock",
)
LIMIT_KEYS = (
    "note_limit_reached",
    "window_limit_reached",
    "comparison_limit_reached",
    "group_limit_reached",
)


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _fresh_cases() -> list:
    return [
        _build_case(
            CASE_KINDS[index % len(CASE_KINDS)],
            "fresh_holdout",
            index,
            FRESH_SEED_BASE + index,
        )
        for index in range(FRESH_CASE_COUNT)
    ]


def _real_cohort(repository: Path) -> tuple[list[dict], list[dict]]:
    manifest = repository / REAL_MANIFEST
    records = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(records) != REAL_SOURCE_COUNT:
        raise ValueError(f"expected exactly {REAL_SOURCE_COUNT} fixed real sources")
    if len({row["source_path"] for row in records}) != len(records):
        raise ValueError("fixed real source manifest contains duplicate paths")
    if any(row.get("status") != "ok" for row in records):
        raise ValueError("fixed real source manifest contains a non-ok row")
    cohort = []
    for index, row in enumerate(records):
        source = repository / REAL_ROOT / row["source_path"]
        if not source.is_file() or _hash(source) != row["source_sha256"]:
            raise ValueError(f"fixed real source changed: {row['source_path']}")
        cohort.append(
            {
                "case_id": f"real:{row['source_path']}",
                "cohort_type": "fixed_real_unlabelled",
                "cohort_index": index,
                "kind": "fixed_real_source",
                "source_path": row["source_path"],
                "source_sha256": row["source_sha256"],
                "source_bytes": source.stat().st_size,
                "metadata_repairs": row.get("metadata_repairs", []),
            }
        )
    return records, cohort


def _detect(song, cfg, algorithm: str) -> tuple[list[dict], list[dict], float]:
    detector = (
        aligned.detect_aligned_part
        if algorithm == "aligned"
        else aligned_indexed.detect_indexed_part
    )
    candidates, stats = [], []
    started = time.monotonic()
    for part in song.parts:
        found, audit = detector(song, part, cfg)
        candidates.extend(found)
        stats.append(audit)
    elapsed = time.monotonic() - started
    return candidates, stats, elapsed


def _phrase_summary(phrases: list[dict]) -> list[dict]:
    return [
        {
            "rank": rank,
            "family_id": phrase["family_id"],
            "part_index": phrase["part_index"],
            "note_count": phrase["note_count"],
            "occurrence_count": phrase["occurrence_count"],
            "recurrence_score": phrase["recurrence_score"],
            "match_quality": phrase["score_components"]["match_quality"],
            "intervals": [
                [row["start_tick"], row["end_tick"]]
                for row in phrase["occurrences"]
            ],
        }
        for rank, phrase in enumerate(phrases, 1)
    ]


def _selection_pair(candidates: list[dict], top_k: int) -> dict:
    original_started = time.monotonic()
    original = select_original_candidates(candidates, top_k)
    original_elapsed = time.monotonic() - original_started
    closed_started = time.monotonic()
    closed, trace = select_closed_candidates_with_trace(candidates, top_k)
    closed_elapsed = time.monotonic() - closed_started
    return {
        "original": original,
        "closed": closed,
        "trace": trace,
        "changed": original != closed,
        "selection_seconds": {
            "original": original_elapsed,
            "closed_exact_extension": closed_elapsed,
        },
    }


def _limits(stats: list[dict]) -> dict:
    return {
        "search_limited": any(
            any(part.get(key, False) for key in LIMIT_KEYS)
            or part.get("saturated_seed_buckets", 0)
            for part in stats
        ),
        "curation_truncated": any(part.get("candidate_limit_reached", False) for part in stats),
        "limit_parts": {
            key: sum(int(part.get(key, False)) for part in stats) for key in LIMIT_KEYS
        },
        "saturated_seed_buckets": sum(part.get("saturated_seed_buckets", 0) for part in stats),
    }


def _percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    position = fraction * (len(values) - 1)
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    weight = position - low
    return values[low] * (1 - weight) + values[high] * weight


def _paired_delta(original: list[dict], closed: list[dict], seed: int) -> dict:
    by_original = {row["case_id"]: row for row in original}
    by_closed = {row["case_id"]: row for row in closed}
    if set(by_original) != set(by_closed):
        raise ValueError("paired synthetic rows differ")
    ids = sorted(by_original)

    def delta(sample: list[str]) -> dict:
        left = aggregate_results([by_original[case_id] for case_id in sample])
        right = aggregate_results([by_closed[case_id] for case_id in sample])
        return {
            "candidate_f1": right["candidate"]["f1"] - left["candidate"]["f1"],
            "occurrence_f1": right["occurrence"]["f1"] - left["occurrence"]["f1"],
            "top1_recovery": right["top1_recovery"] - left["top1_recovery"],
            "recovered_positive_cases": (
                right["recovered_positive_cases"] - left["recovered_positive_cases"]
            ),
            "false_positive_case_count": (
                right["false_positive_case_count"] - left["false_positive_case_count"]
            ),
        }

    point = delta(ids)
    rng = random.Random(seed)
    samples = {key: [] for key in point}
    for _ in range(1000):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        values = delta(sample)
        for key, value in values.items():
            samples[key].append(value)
    return {
        key: {
            "closed_minus_original": point[key],
            "case_bootstrap_ci95": [_percentile(values, 0.025), _percentile(values, 0.975)],
        }
        for key, values in samples.items()
    }


def _method_aggregate(rows: list[dict]) -> dict:
    aggregate = aggregate_results(rows)
    aggregate["changed_selection_cases"] = sum(row["selection_changed"] for row in rows)
    aggregate["closed_extension_replacements"] = sum(row["closed_extension_count"] for row in rows)
    aggregate["by_kind"] = {
        kind: aggregate_results([row for row in rows if row["kind"] == kind])
        for kind in CASE_KINDS
    }
    return aggregate


def _render_report(aggregate: dict) -> str:
    lines = [
        "# Closed exact-pattern selection study",
        "",
        "This experiment uses 500 newly generated cases from the frozen seed range 30000000 to 30000499. The existing development and test namespaces were not scored. The 128-file real pilot has no phrase labels.",
        "",
        "| Algorithm | Variant | Candidate F1 | Occurrence F1 | Recovered positives | Negative output cases | Changed selections |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for algorithm in ALGORITHMS:
        for variant in VARIANTS:
            row = aggregate["synthetic"][algorithm][variant]
            lines.append(
                f"| {algorithm.replace('_', ' ')} | {variant.replace('_', ' ')} | "
                f"{row['candidate']['f1']:.6f} | {row['occurrence']['f1']:.6f} | "
                f"{row['recovered_positive_cases']} | {row['false_positive_case_count']} | "
                f"{row['changed_selection_cases']} |"
            )
    lines.extend(["", "## Paired changes", ""])
    for algorithm in ALGORITHMS:
        delta = aggregate["paired_deltas"][algorithm]
        lines.append(
            f"- {algorithm}: recovered positive cases {delta['recovered_positive_cases']['closed_minus_original']:+.0f}, "
            f"candidate F1 {delta['candidate_f1']['closed_minus_original']:+.6f}, "
            f"occurrence F1 {delta['occurrence_f1']['closed_minus_original']:+.6f}."
        )
    lines.extend(["", "## Unlabelled real pilot", ""])
    for algorithm in ALGORITHMS:
        row = aggregate["real_pilot"][algorithm]
        lines.append(
            f"- {algorithm}: {row['changed_file_count']} of {row['files']} selected outputs changed, "
            f"with {row['closed_extension_replacements']} closed extensions."
        )
    lines.extend(
        [
            "",
            "Real changes are coordinate and support diagnostics only. They do not establish better phrase boundaries or musical quality.",
            "",
            "The exact-extension rule can prefer a maximal symbolic repeat that is longer than a listener-defined phrase. It intentionally requires three exact source-verified occurrences and does not address two-occurrence ambiguity.",
            "",
            "No result in this study measures listener response or memorability.",
            "",
        ]
    )
    return "\n".join(lines)


def run(output: Path) -> dict:
    repository = Path(__file__).resolve().parents[1]
    for relative, expected in BASE_SOURCE_HASHES.items():
        actual = _hash(repository / relative)
        if actual != expected:
            raise RuntimeError(f"frozen core source hash changed: {relative}: {actual}")
    if _hash(repository / REAL_MANIFEST) != "db12be24a75062d008407121cab8a23e6f223afd8fdc7500d48a43a8ff6873e1":
        raise RuntimeError("fixed real source manifest hash changed")

    synthetic_cases = _fresh_cases()
    manifest_rows, real_cohort = _real_cohort(repository)
    synthetic_cfg = aligned.AlignedConfig(top_k=10)
    real_cfg = aligned.AlignedConfig(top_k=3)
    design = {
        "version": STUDY_VERSION,
        "candidate": {
            "version": CLOSED_PATTERN_VERSION,
            "minimum_exact_support": MIN_EXACT_SUPPORT,
            "score_margin": SCORE_MARGIN,
            "requirements": (
                "zero edits, zero timing and duration error, no pitch substitutions, full diagonal matching, "
                "equal support and one-to-one endpoint containment"
            ),
        },
        "fresh_synthetic": {
            "seed_base": FRESH_SEED_BASE,
            "seed_last": FRESH_SEED_BASE + FRESH_CASE_COUNT - 1,
            "case_count": FRESH_CASE_COUNT,
            "conditions": list(CASE_KINDS),
            "split_label": "fresh_holdout",
            "disjoint_from_existing_namespaces": [10_000_000, 20_000_000],
            "thresholds_frozen_before_scoring": True,
        },
        "real_pilot": {
            "manifest": REAL_MANIFEST.as_posix(),
            "manifest_sha256": _hash(repository / REAL_MANIFEST),
            "source_count": REAL_SOURCE_COUNT,
            "labels": False,
        },
        "algorithms": list(ALGORITHMS),
        "variants": list(VARIANTS),
        "iou_threshold": IOU_THRESHOLD,
        "bootstrap": "1000 paired case resamples, deterministic seeds",
        "result_artifacts": ["aggregate.json", "raw_results.json"],
        "claim_boundary": (
            "fresh planted symbolic recurrence and unlabelled real output changes only; "
            "not real accuracy, musical quality, listener response or memorability"
        ),
    }
    configs = {
        "synthetic": asdict(synthetic_cfg),
        "real_pilot": asdict(real_cfg),
        "base_source_hashes": BASE_SOURCE_HASHES,
    }
    receipt_cases = [
        {"cohort_type": "fresh_synthetic", **case.metadata()} for case in synthetic_cases
    ] + real_cohort
    receipt = prepare_experiment(
        output,
        design=design,
        config=configs,
        cases=receipt_cases,
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)

    synthetic_rows = {
        algorithm: {variant: [] for variant in VARIANTS} for algorithm in ALGORITHMS
    }
    synthetic_pair_rows = []
    for case_index, case in enumerate(synthetic_cases):
        algorithm_order = ALGORITHMS if case_index % 2 == 0 else tuple(reversed(ALGORITHMS))
        for algorithm in algorithm_order:
            candidates, stats, detection_seconds = _detect(case.song, synthetic_cfg, algorithm)
            pair = _selection_pair(candidates, synthetic_cfg.top_k)
            limit = _limits(stats)
            for variant, phrases in (
                ("original", pair["original"]),
                ("closed_exact_extension", pair["closed"]),
            ):
                elapsed = detection_seconds + pair["selection_seconds"][variant]
                row = score_case(case, phrases, elapsed)
                row.update(
                    {
                        "algorithm": algorithm,
                        "variant": variant,
                        "candidate_count": len(candidates),
                        "selection_changed": pair["changed"],
                        "closed_extension_count": len(pair["trace"]),
                        **limit,
                    }
                )
                synthetic_rows[algorithm][variant].append(row)
            if pair["changed"]:
                synthetic_pair_rows.append(
                    {
                        "case_id": case.case_id,
                        "kind": case.kind,
                        "algorithm": algorithm,
                        "trace": pair["trace"],
                        "original": _phrase_summary(pair["original"]),
                        "closed_exact_extension": _phrase_summary(pair["closed"]),
                    }
                )
        if (case_index + 1) % 25 == 0:
            print(json.dumps({"synthetic_processed": case_index + 1, "total": FRESH_CASE_COUNT}), flush=True)

    real_rows = []
    for source_index, cohort in enumerate(real_cohort):
        source = repository / REAL_ROOT / cohort["source_path"]
        song = load_midi(source, recover_invalid_keys=bool(cohort["metadata_repairs"]))
        if song.metadata_repairs != cohort["metadata_repairs"]:
            raise ValueError(f"metadata repair receipt changed: {cohort['source_path']}")
        algorithm_order = ALGORITHMS if source_index % 2 == 0 else tuple(reversed(ALGORITHMS))
        for algorithm in algorithm_order:
            candidates, stats, detection_seconds = _detect(song, real_cfg, algorithm)
            pair = _selection_pair(candidates, real_cfg.top_k)
            real_rows.append(
                {
                    "case_id": cohort["case_id"],
                    "cohort_index": source_index,
                    "source_path": cohort["source_path"],
                    "source_sha256": cohort["source_sha256"],
                    "algorithm": algorithm,
                    "candidate_count": len(candidates),
                    "detection_seconds": detection_seconds,
                    "selection_seconds": pair["selection_seconds"],
                    "selection_changed": pair["changed"],
                    "closed_extension_count": len(pair["trace"]),
                    "trace": pair["trace"],
                    "original": _phrase_summary(pair["original"]),
                    "closed_exact_extension": _phrase_summary(pair["closed"]),
                    **_limits(stats),
                }
            )
        if (source_index + 1) % 8 == 0:
            print(json.dumps({"real_processed": source_index + 1, "total": REAL_SOURCE_COUNT}), flush=True)

    synthetic_aggregate = {
        algorithm: {
            variant: _method_aggregate(synthetic_rows[algorithm][variant])
            for variant in VARIANTS
        }
        for algorithm in ALGORITHMS
    }
    paired_deltas = {
        algorithm: _paired_delta(
            synthetic_rows[algorithm]["original"],
            synthetic_rows[algorithm]["closed_exact_extension"],
            73_000 + index,
        )
        for index, algorithm in enumerate(ALGORITHMS)
    }
    real_aggregate = {}
    for algorithm in ALGORITHMS:
        selected = [row for row in real_rows if row["algorithm"] == algorithm]
        changed = [row for row in selected if row["selection_changed"]]
        elapsed = [row["detection_seconds"] for row in selected]
        real_aggregate[algorithm] = {
            "files": len(selected),
            "changed_file_count": len(changed),
            "changed_source_paths": [row["source_path"] for row in changed],
            "closed_extension_replacements": sum(row["closed_extension_count"] for row in selected),
            "search_limited_files": sum(row["search_limited"] for row in selected),
            "curation_truncated_files": sum(row["curation_truncated"] for row in selected),
            "runtime_seconds": {
                "total": sum(elapsed),
                "mean": statistics.mean(elapsed),
                "median": statistics.median(elapsed),
                "maximum": max(elapsed),
            },
            "changed_selections": [
                {
                    "source_path": row["source_path"],
                    "trace": row["trace"],
                    "original": row["original"],
                    "closed_exact_extension": row["closed_exact_extension"],
                }
                for row in changed
            ],
        }

    source_hashes = {
        **BASE_SOURCE_HASHES,
        "samuged/closed_patterns.py": _hash(repository / "samuged/closed_patterns.py"),
        "scripts/evaluate_closed_patterns.py": _hash(repository / "scripts/evaluate_closed_patterns.py"),
        REAL_MANIFEST.as_posix(): _hash(repository / REAL_MANIFEST),
    }
    aggregate = {
        **links,
        "study_version": STUDY_VERSION,
        "source_hashes": source_hashes,
        "synthetic": synthetic_aggregate,
        "paired_deltas": paired_deltas,
        "negative_outputs": {
            algorithm: {
                variant: synthetic_aggregate[algorithm][variant]["false_positive_case_ids"]
                for variant in VARIANTS
            }
            for algorithm in ALGORITHMS
        },
        "real_pilot": real_aggregate,
        "claim_boundary": design["claim_boundary"],
    }
    raw = {
        **links,
        "study_version": STUDY_VERSION,
        "source_hashes": source_hashes,
        "synthetic_rows": synthetic_rows,
        "synthetic_changed_selections": synthetic_pair_rows,
        "real_rows": sorted(real_rows, key=lambda row: (row["cohort_index"], row["algorithm"])),
    }
    _write_json(output / "raw_results.json", raw)
    _write_json(output / "aggregate.json", aggregate)
    (output / "report.md").write_text(_render_report(aggregate), encoding="utf-8")
    complete_experiment(output)
    verify_completed_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
