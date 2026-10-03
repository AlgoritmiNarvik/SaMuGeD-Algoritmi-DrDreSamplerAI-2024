"""External annotated-pattern diagnostics on the published JKU development set.

Use the upstream CSV scores, not its MIDI checking files. Nothing is downloaded
by this module. The five classical works are an external diagnostic, not a
representative popular-music test set or an official MIREX submission.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import re
import shutil
import sys
import time

import mir_eval
import mir_eval.io
import mir_eval.pattern

from .dataset import atomic_json, digest, file_digest
from .experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
)
from .midi import MidiSong, Note, Part
from .phrases import Config, extract, skyline


ANNOTATORS = {"barlowAndMorgensternRevised", "bruhn", "schoenberg",
              "sectionalRepetitions", "tomCollins"}

PUBLISHED_METRIC_COLUMNS = {
    "P_est": 2, "R_est": 3, "F_est": 4,
    "P_occ.75": 5, "R_occ.75": 6, "F_occ.75": 7,
    "P_3": 8, "R_3": 9, "F_3": 10,
    "FFTP_est": 13, "FFP": 14,
    "P_occ.5": 15, "R_occ.5": 16, "F_occ.5": 17,
    "P": 18, "R": 19, "F": 20,
}

METRIC_PROVENANCE = {
    "implementation": "mir_eval.pattern metrics with explicit occurrence_FPR thresholds",
    "occurrence_threshold_calls": {"occ.5": "thres=0.5", "occ.75": "thres=0.75"},
    "published_reference": "matlab/results/results.txt, all 17 comparable metrics plus pattern counts",
    "prior_artifact_correction": {
        "artifact": "research_local/jku_reference_v01",
        "invalid_metrics": ["F_occ.5", "P_occ.5", "R_occ.5"],
        "reason": "mir_eval 0.8.2 evaluate passes thresh, but occurrence_FPR accepts thres; the 0.5 labels contained 0.75 scores",
    },
}

ALGORITHMS = ("reference", "aligned", "aligned_indexed")
EXPECTED_PIECES = (
    "bachBWV889Fg",
    "beethovenOp2No1Mvt3",
    "chopinOp24No4",
    "gibbonsSilverSwan1612",
    "mozartK282Mvt2",
)
LIMIT_KEYS = ("note_limit_reached", "window_limit_reached",
              "comparison_limit_reached", "group_limit_reached")
PROFILE_KEYS = ("comparisons", "proposed_pairs", "seed_support_rejections",
                "exact_signature_hits", "alignment_cache_hits", "dp_calls",
                "saturated_seed_buckets", "saturated_seed_postings_dropped")


def _algorithm_specs(algorithm: str, top_k: int):
    if algorithm == "reference":
        configs = {mode: asdict(Config(mode=mode, top_k=top_k))
                   for mode in ("exact", "transposed", "approximate")}
        return configs, lambda mode, song: extract(song, Config(**configs[mode]))
    if algorithm == "aligned":
        from .aligned import AlignedConfig, extract_aligned
        configs = {"aligned": asdict(AlignedConfig(top_k=top_k))}
        return configs, lambda mode, song: extract_aligned(song, AlignedConfig(**configs[mode]))
    if algorithm == "aligned_indexed":
        from .aligned_indexed import AlignedConfig, extract_indexed
        configs = {"aligned_indexed": asdict(AlignedConfig(top_k=top_k))}
        return configs, lambda mode, song: extract_indexed(song, AlignedConfig(**configs[mode]))
    raise ValueError(f"algorithm must be one of {', '.join(ALGORITHMS)}")


def _result_telemetry(found: dict) -> dict:
    part_stats = found.get("part_stats", [])
    return {
        "limit_parts": {
            key: sum(int(part.get(key, False)) for part in part_stats)
            for key in LIMIT_KEYS
        },
        "profile_counters": {
            key: sum(part.get(key, 0) for part in part_stats)
            for key in PROFILE_KEYS
        },
    }


def _expected_pieces(root: Path) -> tuple[str, ...]:
    """Return the frozen five-work cohort from the official JKU layout."""
    ground_truth = root / "groundTruth"
    if not ground_truth.is_dir():
        raise ValueError(f"JKU source is missing groundTruth: {ground_truth}")
    pieces = tuple(sorted(path.name for path in ground_truth.iterdir() if path.is_dir()))
    if pieces != EXPECTED_PIECES:
        raise ValueError(
            "JKU cohort must contain exactly the five expected works: "
            + ", ".join(EXPECTED_PIECES)
        )
    return pieces


def _snapshot_code(output: Path) -> tuple[str, dict[str, str]]:
    package = Path(__file__).parent
    target = output/"provenance"/"samuged"
    target.mkdir(parents=True)
    for path in sorted(package.glob("*.py")):
        shutil.copyfile(path, target/path.name)
    code_hash = digest({path.name: sha256(path.read_bytes()).hexdigest()
                        for path in sorted(target.glob("*.py"))})
    dependencies = {}
    for name in ("pyproject.toml", "requirements-research.lock"):
        source = package.parent/name
        if source.is_file():
            destination = target.parent/name
            shutil.copyfile(source, destination)
            dependencies[name] = file_digest(destination)
    return code_hash, dependencies


def _csv(path: Path) -> list[list[float]]:
    with path.open() as stream:
        rows = [[float(value) for value in row] for row in csv.reader(stream) if row]
    if not rows or any(not all(math.isfinite(value) for value in row) for row in rows):
        raise ValueError(f"empty or non-finite score CSV: {path}")
    return rows


def _point(row):
    if len(row) < 2 or row[1] != int(row[1]) or not 0 <= row[1] <= 127:
        raise ValueError("invalid annotation point columns")
    return round(row[0], 5), int(row[1])


def load_piece(path: Path) -> tuple[MidiSong, list, dict]:
    scores = sorted((path/"csv").glob("*.csv"))
    if len(scores) != 1:
        raise ValueError("expected one full score CSV")
    source = _csv(scores[0])
    if any(len(row) != 5 or row[1] != int(row[1]) or not 0 <= row[1] <= 127
           or row[3] <= 0 or row[4] != int(row[4]) or row[4] < 0 for row in source):
        raise ValueError("invalid full score columns")
    meters = set()
    for kern in (path/"kern").glob("*.krn"):
        meters.update((int(n), int(d)) for n, d in re.findall(r"\*M(\d+)/(\d+)", kern.read_text()))
    if len(meters) != 1:
        raise ValueError("this adapter requires one verified constant score meter")
    numerator, denominator = next(iter(meters))
    bar_beats = numerator*4/denominator
    offset = math.ceil(max(0, -min(row[0] for row in source))/bar_beats)*bar_beats
    ppq = 960
    parts = defaultdict(list)
    max_error = 0
    for row in source:
        start, duration = round((row[0]+offset)*ppq), round(row[3]*ppq)
        max_error = max(max_error, abs(start/ppq-offset-row[0]), abs(duration/ppq-row[3]))
        if duration <= 0:
            raise ValueError("score duration below adapter resolution")
        parts[int(row[4])].append(Note(start, start+duration, int(row[1]), 90))
    if max_error > 1e-5:
        raise ValueError("CSV timing cannot be represented at 960 PPQ within 1e-5 beat")
    song = MidiSong(ppq, [Part(index, index, index % 9, 0, f"staff {staff}", False,
                              sorted(notes, key=lambda n: (n.start, n.pitch, n.end)))
                         for index, (staff, notes) in enumerate(sorted(parts.items()))],
                    [(0, 500_000)], [(0, numerator, denominator)], [])
    allowed = ANNOTATORS | ({"barlowAndMorgenstern"} if path.name == "monophonic" else set())
    patterns, names, unmatched = [], [], []
    score_points = {_point(row) for row in source}
    for annotator in sorted((path/"repeatedPatterns").iterdir()):
        if annotator.name not in allowed:
            continue
        for pattern in sorted(annotator.iterdir()):
            if not pattern.is_dir():
                continue
            files = sorted((pattern/"occurrences"/"csv").glob("occ*.csv"),
                           key=lambda item: int(item.stem[3:]))
            if not files:
                continue
            occurrences = [sorted({_point(row) for row in _csv(file)}) for file in files]
            for file, occurrence in zip(files, occurrences):
                missing = set(occurrence)-score_points
                if missing:
                    unmatched.append({"path": file.relative_to(path).as_posix(), "points": len(missing)})
            names.append(f"{annotator.name}/{pattern.name}")
            patterns.append(occurrences)
    if unmatched:
        raise ValueError(f"annotations contain points absent from score: {unmatched}")
    point_lookup = {}
    for row in source:
        key = (round((row[0]+offset)*ppq), int(row[1]))
        value = round(row[0], 5)
        if key in point_lookup and point_lookup[key] != value:
            raise ValueError("different CSV onsets collapse to the same tick/pitch")
        point_lookup[key] = value
    return song, patterns, {"score_path": scores[0].as_posix(), "score_sha256": file_digest(scores[0]),
                            "offset_beats": offset, "adapter_ppq": ppq, "maximum_timing_error_beats": max_error,
                            "meter": [numerator, denominator], "score_notes": len(source),
                            "ground_truth_pattern_names": names,
                            "ground_truth_patterns": len(patterns),
                            "ground_truth_occurrences": sum(len(p) for p in patterns),
                            "ground_truth_points_verified_in_score": True,
                            "_point_lookup": point_lookup}


def prediction_points(song, phrases, offset, point_lookup=None):
    streams = {part.index: skyline(part, song.ticks_per_beat) for part in song.parts}
    patterns = []
    def point(note):
        onset = ((point_lookup[(note.start, note.pitch)]) if point_lookup is not None
                 else round(note.start/song.ticks_per_beat-offset, 5))
        return onset, note.pitch
    for phrase in phrases:
        stream = streams[phrase["part_index"]]
        prototype = stream[phrase["prototype_note_index"]:phrase["prototype_note_index"]+phrase["note_count"]]
        prototype_points = sorted({point(n) for n in prototype})
        occurrences = []
        for occurrence in phrase["occurrences"]:
            index, count = occurrence["note_index"], occurrence.get("note_count", phrase["note_count"])
            points = sorted({point(n) for n in stream[index:index+count]})
            if points not in occurrences:
                occurrences.append(points)
        # mir_eval expects the prototype first. Include it once if interval
        # pruning omitted it; retain the actual source notes, never transpose.
        if prototype_points in occurrences:
            occurrences.remove(prototype_points)
        patterns.append([prototype_points]+occurrences)
    return patterns


def metrics(reference, estimated):
    if not reference or not estimated:
        # mir_eval0.8.2 returns a tuple for first_n_target_proportion_R on an
        # empty estimate, although the nonempty metric is scalar. Define the
        # no-recovery case explicitly and keep a stable numeric output schema.
        return {key: 0.0 for key in ("F", "P", "R", "F_est", "P_est", "R_est",
                "F_occ.5", "P_occ.5", "R_occ.5", "F_occ.75", "P_occ.75", "R_occ.75",
                "F_3", "P_3", "R_3", "FFP", "FFTP_est")}
    scores = dict(mir_eval.pattern.evaluate(reference, estimated))
    for suffix, threshold in ((".5", 0.5), (".75", 0.75)):
        f_score, precision, recall = mir_eval.pattern.occurrence_FPR(
            reference, estimated, thres=threshold
        )
        scores[f"F_occ{suffix}"] = f_score
        scores[f"P_occ{suffix}"] = precision
        scores[f"R_occ{suffix}"] = recall
    return {key: float(value) for key, value in scores.items()}


def verify_published_examples(root: Path) -> dict:
    _, reference, metadata = load_piece(root/"groundTruth"/"mozartK282Mvt2"/"polyphonic")
    result = {}
    expected = []
    for line in (root/"matlab"/"results"/"results.txt").read_text().splitlines():
        if line.startswith("9, "):
            expected.append([float(x) for x in line.split(",")])
    if len(expected) != 7 or len(reference) != 9:
        raise ValueError("published sanity case layout changed")
    for index, values in enumerate(expected, 1):
        path = root/"matlab"/"pattDiscOut"/f"algo{index}"/f"mzrt_sonata04-2_algo{index}.txt"
        prediction = mir_eval.io.load_patterns(str(path))
        prediction = [[[(round(t, 5), int(p)) for t, p in occurrence] for occurrence in pattern] for pattern in prediction]
        scores = metrics(reference, prediction)
        check = {key: values[column] for key, column in PUBLISHED_METRIC_COLUMNS.items()}
        deviations = {key: abs(scores[key]-value) for key, value in check.items()}
        pattern_count_deviations = {
            "reference_patterns": abs(len(reference)-values[0]),
            "estimated_patterns": abs(len(prediction)-values[1]),
        }
        maximum = max((*deviations.values(), *pattern_count_deviations.values()))
        result[f"algo{index}"] = {
            "maximum_absolute_deviation": maximum,
            "absolute_deviations": deviations,
            "pattern_count_deviations": pattern_count_deviations,
            "expected_scores": check,
            "passed": maximum <= 1e-5,
            "scores": scores,
        }
    return {"passed": all(item["passed"] for item in result.values()), "examples": result,
            "reference_patterns": metadata["ground_truth_patterns"],
            "verified_metric_names": list(PUBLISHED_METRIC_COLUMNS),
            "metric_provenance": METRIC_PROVENANCE,
            "mir_eval_version": mir_eval.__version__}


def run(root: Path, output: Path, top_k=3, algorithm: str = "reference") -> dict:
    """Run one frozen detector family on the fixed JKU development cohort."""
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output directory must be absent or empty")
    root = root.resolve(strict=True)
    config, detector = _algorithm_specs(algorithm, top_k)
    files = {
        path.relative_to(root).as_posix(): file_digest(path)
        for path in sorted(root.rglob("*"))
        if path.suffix in {".csv", ".krn", ".txt"} and path.is_file()
    }
    pieces = _expected_pieces(root)
    cases = []
    for piece in pieces:
        for variant in ("monophonic", "polyphonic"):
            prefix = f"groundTruth/{piece}/{variant}/"
            subset = {name: value for name, value in files.items() if name.startswith(prefix)}
            cases.append({
                "case_id": f"{piece}/{variant}",
                "piece": piece,
                "variant": variant,
                "source_subset_sha256": digest(subset),
                "source_file_count": len(subset),
            })

    repository = Path(__file__).resolve().parent.parent
    prior_golden = repository/"research_local"/"jku_reference_v02"/"published_examples.json"
    required_files = [
        "samuged/evaluate_jku.py",
        "samuged/dataset.py",
        "samuged/experiment.py",
        "samuged/__init__.py",
        "samuged/metadata_recovery.py",
        "samuged/midi.py",
        "samuged/phrases.py",
        "pyproject.toml",
        "requirements-research.lock",
        "research_local/jku_reference_v02/published_examples.json",
    ]
    if algorithm in {"aligned", "aligned_indexed"}:
        required_files.append("samuged/aligned.py")
    if algorithm == "aligned_indexed":
        required_files.append("samuged/aligned_indexed.py")
    design = {
        "schema_version": 3,
        "dataset": "JKUPDD-noAudio-Aug2013",
        "corpus_role": "external classical development diagnostic",
        "algorithm": algorithm,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "mir_eval_version": mir_eval.__version__,
        "configs": config,
        "expected_pieces": list(pieces),
        "source_root_name": root.name,
        "source_files": files,
        "external_source_snapshot_sha256": digest(files),
        "timestamp_rounding_decimals": 5,
        "metric_provenance": METRIC_PROVENANCE,
        "adapter": (
            "CSV notes at 960 PPQ for matching; predictions map back to original "
            "CSV onsets rounded to 5 decimals; whole-bar pickup offset, staff parts, "
            "constant verified meter, piano program, velocity 90"
        ),
        "claim_boundary": (
            "five classical development works; external annotation diagnostic, "
            "no official MIREX or popular-music accuracy claim"
        ),
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config={"algorithm": algorithm, "top_k": top_k, "detector_configs": config},
        cases=cases,
        required_files=required_files,
    )
    links = receipt_links(receipt)
    code_hash, dependency_files = _snapshot_code(output)
    design_artifact = {
        **design,
        **links,
        "frozen_design_sha256": receipt["design_sha256"],
        "receipt": links,
        "code_sha256": code_hash,
        "code_snapshot": "provenance/samuged",
        "dependency_snapshot_sha256": dependency_files,
    }
    atomic_json(output/"design.json", design_artifact)

    sanity = verify_published_examples(root)
    prior = json.loads(prior_golden.read_text())
    current_examples_hash = sha256_json(sanity["examples"])
    prior_examples_hash = sha256_json(prior["examples"])
    sanity.update({
        **links,
        "frozen_design_sha256": receipt["design_sha256"],
        "receipt": links,
        "examples_payload_sha256": current_examples_hash,
        "prior_corrected_examples_payload_sha256": prior_examples_hash,
        "prior_corrected_examples_unchanged": current_examples_hash == prior_examples_hash,
        "prior_corrected_artifact": "research_local/jku_reference_v02/published_examples.json",
    })
    atomic_json(output/"published_examples.json", sanity)
    if not sanity["passed"]:
        raise ValueError("mir_eval reproduction differs from published sanity cases; inspect before evaluating")
    if not sanity["prior_corrected_examples_unchanged"]:
        raise ValueError("published sanity payload differs from the corrected reference artifact")

    results = []
    raw = {
        "schema_version": 3,
        "algorithm": algorithm,
        **links,
        "frozen_design_sha256": receipt["design_sha256"],
        "receipt": links,
        "results": results,
    }
    atomic_json(output/"raw_results.json", raw)
    for piece in pieces:
        for variant in ("monophonic", "polyphonic"):
            song, reference, provenance = load_piece(root/"groundTruth"/piece/variant)
            point_lookup = provenance.pop("_point_lookup")
            for mode in config:
                start = time.monotonic()
                found = detector(mode, song)
                elapsed = time.monotonic()-start
                estimated = prediction_points(
                    song, found["phrases"], provenance["offset_beats"], point_lookup
                )
                result = {
                    "piece": piece,
                    "variant": variant,
                    "algorithm": algorithm,
                    "mode": mode,
                    "prediction_patterns": len(estimated),
                    "phrase_output_sha256": sha256_json(found["phrases"]),
                    "prediction_output_sha256": sha256_json(estimated),
                    "search_limited": found["search_limited"],
                    "curation_truncated": found["curation_truncated"],
                    "runtime_seconds": elapsed,
                    "telemetry": _result_telemetry(found),
                    "metrics": metrics(reference, estimated),
                    **provenance,
                }
                results.append(result)
                atomic_json(output/"raw_results.json", raw)
                print(json.dumps({
                    key: result[key]
                    for key in ("piece", "variant", "algorithm", "mode",
                                "prediction_patterns", "search_limited")
                }), flush=True)

    aggregates = {}
    for variant in ("monophonic", "polyphonic"):
        for mode in config:
            selected = [
                row for row in results
                if row["variant"] == variant and row["mode"] == mode
            ]
            aggregates[f"{variant}/{mode}"] = {
                "works": len(selected),
                "macro_metrics": {
                    key: sum(row["metrics"][key] for row in selected)/len(selected)
                    for key in selected[0]["metrics"]
                },
                "search_limited_works": sum(row["search_limited"] for row in selected),
                "curation_truncated_works": sum(row["curation_truncated"] for row in selected),
                "limit_parts": {
                    key: sum(row["telemetry"]["limit_parts"][key] for row in selected)
                    for key in LIMIT_KEYS
                },
                "profile_counters": {
                    key: sum(row["telemetry"]["profile_counters"][key] for row in selected)
                    for key in PROFILE_KEYS
                },
                "total_runtime_seconds": sum(row["runtime_seconds"] for row in selected),
            }
    result = {
        "schema_version": 3,
        "dataset": design["dataset"],
        "algorithm": algorithm,
        **links,
        "mir_eval_version": mir_eval.__version__,
        "top_k": top_k,
        "frozen_design_sha256": receipt["design_sha256"],
        "receipt": links,
        "raw_results_sha256": file_digest(output/"raw_results.json"),
        "published_examples_sha256": file_digest(output/"published_examples.json"),
        "external_source_snapshot_sha256": design["external_source_snapshot_sha256"],
        "metric_provenance": METRIC_PROVENANCE,
        "published_metric_examples_verified": sanity["passed"],
        "prior_corrected_examples_unchanged": sanity["prior_corrected_examples_unchanged"],
        "all_annotation_points_verified_in_score": all(
            row["ground_truth_points_verified_in_score"] for row in results
        ),
        "groups": aggregates,
        "claim_boundary": design["claim_boundary"],
    }
    atomic_json(output/"aggregate.json", result)
    complete_experiment(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--algorithm", choices=ALGORITHMS, default="reference")
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.output, args.top_k, args.algorithm), indent=2))
