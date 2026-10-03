"""Prepare a local candidate release and an optional deterministic archive.

This tool never publishes, uploads or changes the source corpus. Musical
redistribution rights and human quality acceptance remain external decisions.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

from samuged import experiment
from samuged.dataset import atomic_json, canonical_json, file_digest

try:
    from scripts.screen_splits import verify_screening
except ModuleNotFoundError as exc:  # Direct ``python scripts/package_dataset.py``.
    if exc.name != "scripts":
        raise
    from screen_splits import verify_screening


def _contained(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("unsafe artifact path")
    resolved = (root/relative).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("artifact escapes dataset")
    return resolved


def unique_views(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """One preferred-split representative per canonical family, retaining links."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["kind"], row["family_id"])].append(row)
    representatives, memberships = [], []
    for key, members in sorted(groups.items()):
        eligible = [row for row in members if row["split"] != "overlap_excluded"]
        if not eligible:
            raise ValueError("family has no eligible split representative")
        representative = min(eligible, key=lambda row: (-row["recurrence_score"], row["source_id"], row["phrase_id"]))
        representatives.append(representative)
        memberships.append({"kind": key[0], "family_id": key[1],
                            "representative_phrase_id": representative["phrase_id"],
                            "phrase_count": len(members),
                            "source_count": len({row["source_id"] for row in members}),
                            "split_group_count": len({row["split_group"] for row in members}),
                            "phrase_ids": sorted(row["phrase_id"] for row in members),
                            "source_ids": sorted({row["source_id"] for row in members})})
    return representatives, memberships


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(canonical_json(row)+"\n" for row in rows), encoding="utf-8")


def _jsonl_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object rows: {path}")
            rows.append(value)
    return rows


def _artifact_hashes(root: Path, names: tuple[str, ...]) -> dict[str, dict[str, int | str]]:
    return {
        name: {"bytes": (root / name).stat().st_size, "sha256": file_digest(root / name)}
        for name in names
    }


def _selection_replay_files(root: Path, start: dict) -> set[str]:
    """Return the complete portable file set and reject links or extras."""
    if root.is_symlink():
        raise ValueError("selection replay root must not be a symlink")
    snapshot = json.loads((root / "source_snapshot.json").read_text(encoding="utf-8"))
    entries = snapshot.get("files")
    if not isinstance(entries, list):
        raise ValueError("selection replay source snapshot has no file list")
    expected = {
        "experiment_receipt.json", "source_snapshot.json", "completion_receipt.json",
        *start.get("design", {}).get("result_artifacts", []),
    }
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("selection replay source snapshot has an invalid path")
        expected.add((Path("source_snapshot") / entry["path"]).as_posix())

    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"selection replay contains a symlink: {relative}")
        if path.is_dir():
            if relative != "source_snapshot" and not relative.startswith("source_snapshot/"):
                raise ValueError(f"selection replay contains an unexpected directory: {relative}")
            continue
        if not path.is_file():
            raise ValueError(f"selection replay contains a non-file artifact: {relative}")
        actual.add(relative)
    if actual != expected:
        unexpected = sorted(actual - expected)
        missing = sorted(expected - actual)
        detail = []
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected[:4]))
        if missing:
            detail.append("missing=" + ",".join(missing[:4]))
        raise ValueError("selection replay file set mismatch (" + "; ".join(detail) + ")")
    return expected


def _selection_replay_binding(
    replay: Path,
    dataset: Path,
    summary: dict,
    audit: dict,
    build_config: dict,
) -> dict:
    """Verify a completed selection replay against the exact dataset manifests."""
    if replay.is_symlink():
        raise ValueError("selection replay root must not be a symlink")
    replay = replay.resolve(strict=True)
    if not replay.is_dir():
        raise ValueError("selection replay must be a directory")
    experiment.verify_completed_experiment(replay)
    start = experiment.verify_start_receipt(replay)
    if not isinstance(start.get("design"), dict):
        raise ValueError("selection replay receipt has no design")
    replay_files = _selection_replay_files(replay, start)
    expected_names = ("sources.jsonl", "phrases.jsonl", "build_config.json", "summary.json", "audit.json")
    expected_artifacts = _artifact_hashes(dataset, expected_names)
    expected_run_key = build_config.get("run_key")
    if not expected_run_key or summary.get("run_key") != expected_run_key or audit.get("run_key") != expected_run_key:
        raise ValueError("dataset run key is not consistently bound")

    receipt_config = start.get("config")
    if not isinstance(receipt_config, dict):
        raise ValueError("selection replay receipt has no configuration")
    if receipt_config.get("dataset_run_key") != expected_run_key:
        raise ValueError("selection replay config run key mismatch")
    expected_detector = {
        "algorithm": build_config.get("algorithm", "reference"),
        "config": build_config.get("config"),
        "percussion": build_config.get("percussion", False),
        "recover_invalid_keys": build_config.get("recover_invalid_keys", False),
    }
    if receipt_config.get("detector") != expected_detector:
        raise ValueError("selection replay detector config mismatch")
    if receipt_config.get("dataset_artifacts") != expected_artifacts:
        raise ValueError("selection replay config dataset binding mismatch")
    design = start.get("design")
    if not isinstance(design, dict):
        raise ValueError("selection replay receipt has no design")
    if design.get("dataset_run_key") != expected_run_key or design.get("dataset_artifacts") != expected_artifacts:
        raise ValueError("selection replay design dataset binding mismatch")
    declared = tuple(sorted(design.get("result_artifacts", [])))
    required_results = {"aggregate.json", "raw_results.json", "selection.json"}
    if not required_results.issubset(declared):
        raise ValueError("selection replay is missing a required result artifact")

    selection = json.loads((replay / "selection.json").read_text(encoding="utf-8"))
    aggregate = json.loads((replay / "aggregate.json").read_text(encoding="utf-8"))
    raw = json.loads((replay / "raw_results.json").read_text(encoding="utf-8"))
    design_result = json.loads((replay / "design.json").read_text(encoding="utf-8")) if (replay / "design.json").is_file() else {}
    for name, value in (("selection.json", selection), ("aggregate.json", aggregate), ("raw_results.json", raw)):
        if not isinstance(value, dict):
            raise ValueError(f"selection replay result is not an object: {name}")
        links = experiment.receipt_links(start)
        if any(value.get(key) != expected for key, expected in links.items()):
            raise ValueError(f"selection replay provenance links mismatch: {name}")
        if value.get("dataset_run_key") is not None and value.get("dataset_run_key") != expected_run_key:
            raise ValueError(f"selection replay run key mismatch: {name}")
        if value.get("dataset_artifacts") is not None and value.get("dataset_artifacts") != expected_artifacts:
            raise ValueError(f"selection replay dataset binding mismatch: {name}")
    if design_result and design_result.get("dataset_run_key") not in (None, expected_run_key):
        raise ValueError("selection replay design result run key mismatch")
    if design_result and design_result.get("dataset_artifacts") not in (None, expected_artifacts):
        raise ValueError("selection replay design result dataset binding mismatch")
    if design_result:
        if design_result.get("design") != design or design_result.get("design_sha256") != start.get("design_sha256"):
            raise ValueError("selection replay design result hash mismatch")
        if design_result.get("config") != receipt_config or design_result.get("config_sha256") != start.get("config_sha256"):
            raise ValueError("selection replay config result hash mismatch")

    selection_body_keys = (
        "version", "dataset_artifacts", "dataset_run_key", "dataset_algorithm", "full_audit", "selection", "selected",
    )
    if any(key not in selection for key in selection_body_keys):
        raise ValueError("selection replay selection artifact is incomplete")
    selection_body = {key: selection[key] for key in selection_body_keys}
    if selection.get("selection_sha256") != experiment.sha256_json(selection_body):
        raise ValueError("selection replay selection hash mismatch")
    if selection["dataset_artifacts"] != expected_artifacts or selection["dataset_run_key"] != expected_run_key:
        raise ValueError("selection replay selection dataset binding mismatch")
    selection_hash = selection["selection_sha256"]
    if receipt_config.get("selection_sha256") != selection_hash:
        raise ValueError("selection replay config selection hash mismatch")
    if design.get("selection_sha256") != selection_hash or design.get("selection") != selection["selection"]:
        raise ValueError("selection replay design selection binding mismatch")
    if start.get("case_cohort") != selection["selected"]:
        raise ValueError("selection replay frozen cohort differs from selection")
    expected_full_audit = {
        "passed": True,
        "source_files": audit.get("source_files"),
        "full_source_coverage_required": True,
        "source_manifest_sha256": expected_artifacts["sources.jsonl"]["sha256"],
        "phrase_manifest_sha256": expected_artifacts["phrases.jsonl"]["sha256"],
        "build_config_sha256": expected_artifacts["build_config.json"]["sha256"],
        "summary_sha256": expected_artifacts["summary.json"]["sha256"],
    }
    if selection["full_audit"] != expected_full_audit:
        raise ValueError("selection replay full audit binding mismatch")

    source_rows = _jsonl_rows(dataset / "sources.jsonl")
    source_by_id = {row.get("source_id"): row for row in source_rows}
    if len(source_by_id) != len(source_rows):
        raise ValueError("dataset source manifest has duplicate source IDs")
    selected = selection.get("selected")
    meta = selection.get("selection")
    if not isinstance(selected, list) or not isinstance(meta, dict):
        raise ValueError("selection replay selection has no selected cohort")
    selected_ids = [item.get("source_id") for item in selected if isinstance(item, dict)]
    if len(selected_ids) != len(selected) or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("selection replay selected cohort has duplicate or invalid IDs")
    for item in selected:
        source_id = item["source_id"]
        source_row = source_by_id.get(source_id)
        if source_row is None:
            raise ValueError(f"selection replay source ID is absent from manifest: {source_id}")
        for key in ("source_path", "source_sha256", "source_bytes", "status", "outcome"):
            if item.get(key) != source_row.get(key):
                raise ValueError(f"selection replay source field mismatch: {source_id}/{key}")
        if item.get("record_sha256") != experiment.sha256_json(source_row):
            raise ValueError(f"selection replay source record hash mismatch: {source_id}")
    successful_ids = {row.get("source_id") for row in source_rows if row.get("status") == "ok"}
    error_ids = {row.get("source_id") for row in source_rows if row.get("status") == "error"}
    selection_mode = meta.get("selection_mode", "bounded_sample")
    all_successful = meta.get("selection_covers_all_successful_sources") is True
    if all_successful:
        if (selection_mode != "all_successful" or set(selected_ids) != successful_ids
                or len(successful_ids) != sum(row.get("status") == "ok" for row in source_rows)
                or len(error_ids) != sum(row.get("status") == "error" for row in source_rows)
                or len(successful_ids) + len(error_ids) != len(source_rows)
                or any(not isinstance(row.get("source_id"), str) or not row.get("source_id")
                       for row in source_rows)):
            raise ValueError("selection replay all-successful cohort is incomplete")
        if (meta.get("successful_source_count") != len(successful_ids)
                or meta.get("error_source_count") != len(error_ids)
                or meta.get("total_manifest_sources") != len(source_rows)):
            raise ValueError("selection replay all-successful totals mismatch")
    elif selection_mode != "bounded_sample" or not set(selected_ids).issubset(successful_ids):
        raise ValueError("selection replay sampled cohort is invalid")
    if meta.get("count") != len(selected_ids):
        raise ValueError("selection replay selection count mismatch")

    cases = raw.get("cases")
    if not isinstance(cases, list) or len(cases) != len(selected):
        raise ValueError("selection replay raw case coverage mismatch")
    selected_by_id = {item["source_id"]: item for item in selected}
    case_ids = []
    for case in cases:
        if not isinstance(case, dict) or case.get("status") != "passed":
            raise ValueError("selection replay contains a failed case")
        if case.get("failures") != []:
            raise ValueError("selection replay passed case contains failures")
        source_id = case.get("source_id")
        case_ids.append(source_id)
        selected_item = selected_by_id.get(source_id)
        if selected_item is None:
            raise ValueError("selection replay raw case is outside selected cohort")
        for key in ("source_id", "source_path", "source_sha256", "source_bytes", "record_sha256"):
            if case.get(key) != selected_item.get(key):
                raise ValueError(f"selection replay raw case identity mismatch: {source_id}/{key}")
        for key in ("detector_evidence_sha256", "metadata_repairs", "metadata_recovered", "stratum"):
            if key in selected_item or key in case:
                if case.get(key) != selected_item.get(key):
                    raise ValueError(f"selection replay raw case evidence mismatch: {source_id}/{key}")
    if len(set(case_ids)) != len(case_ids) or set(case_ids) != set(selected_ids):
        raise ValueError("selection replay raw cases are not one-to-one with selected records")
    if raw.get("failure_count") != 0 or aggregate.get("failure_count") != 0:
        raise ValueError("selection replay reports failures")
    if aggregate.get("count") != len(selected) or aggregate.get("passed_count") != len(selected):
        raise ValueError("selection replay aggregate count mismatch")
    if aggregate.get("status_counts") != {"passed": len(selected)}:
        raise ValueError("selection replay aggregate status coverage mismatch")
    for value, name in ((raw, "raw"), (aggregate, "aggregate")):
        for key, expected in (
            ("count", len(selected)),
            ("selection_mode", selection_mode),
            ("selection_covers_all_successful_sources", all_successful),
        ):
            if key in value and value[key] != expected:
                raise ValueError(f"selection replay {name} {key} mismatch")
    for key, expected in (
        ("total_manifest_sources", len(source_rows)),
        ("successful_source_count", len(successful_ids)),
        ("error_source_count", len(error_ids)),
    ):
        if key in aggregate and aggregate[key] != expected:
            raise ValueError(f"selection replay aggregate {key} mismatch")
    if "strata_counts" in aggregate:
        expected_strata = {}
        for case in cases:
            expected_strata[case.get("stratum")] = expected_strata.get(case.get("stratum"), 0) + 1
        if aggregate["strata_counts"] != expected_strata:
            raise ValueError("selection replay aggregate strata mismatch")
    for value in (raw, aggregate):
        if value.get("selection_sha256") != selection.get("selection_sha256"):
            raise ValueError("selection replay selection hash link mismatch")
    if start.get("case_cohort_sha256") != experiment.sha256_json(start.get("case_cohort")):
        raise ValueError("selection replay case cohort hash mismatch")
    return {
        "completion_sha256": file_digest(replay / "completion_receipt.json"),
        "selection_count": len(selected),
        "passed_count": len(selected),
        "failure_count": 0,
        "selection_mode": selection_mode,
        "selection_covers_all_successful_sources": all_successful,
        "successful_source_count": len(successful_ids),
        "error_source_count": len(error_ids),
        "dataset_artifacts": expected_artifacts,
        "run_key": expected_run_key,
        "files": replay_files,
    }


def _copy_selection_replay(source: Path, target: Path, files: set[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for relative in sorted(files):
        source_path = source / relative
        target_path = target / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
    for relative in files:
        if file_digest(source / relative) != file_digest(target / relative):
            raise ValueError(f"selection replay copy changed: {relative}")


def package(dataset: Path, output: Path, *, allow_pilot=False, archive=False,
            screening: Path | None = None, selection_replay: Path | None = None) -> dict:
    dataset, output = dataset.resolve(strict=True), output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("release metadata must be outside the extraction directory")
    summary = json.loads((dataset/"summary.json").read_text())
    audit = json.loads((dataset/"audit.json").read_text())
    build_config = json.loads((dataset/"build_config.json").read_text())
    if not audit.get("passed") or audit["run_key"] != summary["run_key"]:
        raise ValueError("require a passing audit for the same extraction run")
    audit_bindings = {
        "source_manifest_sha256": dataset / "sources.jsonl",
        "phrase_manifest_sha256": dataset / "phrases.jsonl",
        "build_config_sha256": dataset / "build_config.json",
        "summary_sha256": dataset / "summary.json",
    }
    for key, path in audit_bindings.items():
        if audit.get(key) != file_digest(path):
            raise ValueError(f"audit receipt does not match {path.name}")
    full = summary.get("cohort_limit") is None and summary["source_files"] == summary.get("discovered_source_files")
    if not allow_pilot and (not full or not audit.get("full_source_coverage_required")):
        raise ValueError("a full release requires audited full source coverage")
    for name, key in (("sources.jsonl", "source_manifest_sha256"), ("phrases.jsonl", "phrase_manifest_sha256")):
        if file_digest(dataset/name) != summary[key]:
            raise ValueError("manifest changed after extraction")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("release output must be a new or empty directory")
    archive_target = output.with_suffix(".tar.gz")
    archive_receipt = archive_target.with_suffix(archive_target.suffix + ".json")
    if archive and (archive_target.exists() or archive_receipt.exists()):
        raise ValueError("archive or archive receipt already exists")
    screening_summary = None
    if screening is not None:
        screening = screening.resolve(strict=True)
        screening_summary = verify_screening(dataset, screening)
    replay_summary = None
    replay_source = None
    replay_files = None
    if selection_replay is not None:
        if selection_replay.is_symlink():
            raise ValueError("selection replay root must not be a symlink")
        replay_source = selection_replay.resolve(strict=True)
        if replay_source == output or output.is_relative_to(replay_source) or replay_source.is_relative_to(output):
            raise ValueError("selection replay must be outside the release output")
        replay_summary = _selection_replay_binding(replay_source, dataset, summary, audit, build_config)
        replay_files = replay_summary.pop("files")
    algorithm = build_config.get("algorithm", "reference")
    reextracted = audit.get("reextraction_required") is True
    audit_scope = {
        "primary_audit_passed": audit.get("passed") is True,
        "full_source_coverage_required": audit.get("full_source_coverage_required") is True,
        "selection_reextracted_for_all_successful_sources": reextracted,
        "source_records_verified": audit.get("counts", {}).get("sources_verified", 0),
        "midi_excerpts_verified": audit.get("counts", {}).get("midi_verified", 0),
        "audit_sha256": file_digest(dataset / "audit.json"),
    }
    if replay_summary is not None:
        audit_scope["selection_replay"] = replay_summary
    rows = [json.loads(line) for line in (dataset/"phrases.jsonl").read_text().split("\n") if line.strip()]
    representatives, memberships = unique_views(rows)
    # Verify payloads before creating release metadata. Never trust a stale audit.
    payloads = {}
    for row in rows:
        relative = row.get("midi_path")
        if relative is None:
            continue
        path = _contained(dataset, relative)
        if file_digest(path) != row["midi_sha256"]:
            raise ValueError(f"MIDI artifact hash mismatch: {row['phrase_id']}")
        payloads[relative] = path
    output.mkdir(parents=True, exist_ok=True)
    (output/"views").mkdir()
    for kind in ("melodic", "percussion"):
        _jsonl(output/"views"/f"{kind}.unique.jsonl", [row for row in representatives if row["kind"] == kind])
    _jsonl(output/"views"/"family_membership.jsonl", memberships)
    if screening is not None:
        target = output/"views"/"duplicate_screening"
        target.mkdir()
        for name in ("summary.json", *sorted(screening_summary["artifacts"])):
            shutil.copyfile(screening/name, target/name)
    for name in ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json", "audit.json"):
        shutil.copyfile(dataset/name, output/name)
    for optional in ("diagnostics.json", "review.html"):
        if (dataset/optional).is_file():
            shutil.copyfile(dataset/optional, output/optional)
    if (dataset/"provenance").is_dir():
        shutil.copytree(dataset/"provenance", output/"provenance")
    if replay_source is not None:
        _copy_selection_replay(replay_source, output / "evidence" / "selection_replay", replay_files)
        copied_replay = output / "evidence" / "selection_replay"
        copied_summary = _selection_replay_binding(copied_replay, dataset, summary, audit, build_config)
        copied_summary.pop("files", None)
        if copied_summary != replay_summary:
            raise ValueError("copied selection replay does not match its source")
    repository = Path(__file__).resolve().parents[1]
    if (repository/"schemas").is_dir():
        shutil.copytree(repository/"schemas", output/"schemas")
    shutil.copyfile(repository/"LICENSE", output/"SOFTWARE_LICENSE.txt")
    shutil.copyfile(repository / "docs/research/consumer_guide.md", output / "CONSUMER_GUIDE.md")
    card = f"""# SaMuGeD Earworms (Ostinato / Catchy musical hooks)

Recurring melodic phrases and separate drum patterns.

Authors: Peiyi Wu (pewu10205@uit.no), Asle Fjæran Øren (asleoren@gmail.com), Shayan Dadman (shayan.dadman@uit.no) and Almaz Ermilov (almaz.ermilov@uit.no).

Local candidate release, unpublished. Scope: {'full local corpus' if full else 'pilot only'}.

## Purpose

The collection contains repeated symbolic melodic phrases and separate drum patterns. It supports recurrence retrieval, source reconstruction and annotation experiments. It does not contain verified earworm, hook, salience or human phrase-quality labels.

## Contents

- Source files accounted for: {summary['source_files']:,}.
- Processing outcomes: {canonical_json(summary['source_outcomes'])}.
- Phrase counts: {canonical_json(summary['phrase_counts'])}.
- Unique canonical families: {len(representatives):,}.
- Exported MIDI files: {len(payloads):,}.
- Extraction algorithm: `{algorithm}`.
- Run fingerprint: `{summary['run_key']}`.

`sources.jsonl` accounts for all selected input paths, including failures and no-match files. `phrases.jsonl` keeps the per-source candidate collection. `views/*.unique.jsonl` selects one representative per canonical family, and `views/family_membership.jsonl` preserves all source links with phrase, source file and split group counts. These are file and grouping frequencies, not composition counts. Family equality is the detector's stated canonicalization, not proof of musical identity. Rows marked `overlap_excluded` must not be used as train/validation/test examples.

MIDI files use paths in `midi_path`, relative to the complete archive root. This metadata directory intentionally does not copy MIDI payloads; the optional archive includes them. Original full-song source MIDI files are not bundled. Source-relative paths and SHA256 values identify the local Lakh MIDI Clean inventory.

The [consumer guide](CONSUMER_GUIDE.md) explains archive verification, source and phrase joins, search limits, coordinate units and separate melodic and percussion access. Its research commands require the matching code checkout.

## Method and quality

Melody uses per-part onset skyline and verified recurrence under the recorded pitch/timing model. Percussion preserves simultaneous kit pitches and uses meter-aware patterns without transposition. Scores rank structural recurrence only. Detailed parameters and executable source snapshots are in `build_config.json` and `provenance/`.

The independent audit checks source reconstruction, manifest membership, splits and MIDI export semantics. A passing audit proves those recorded checks, not perceptual quality. Parse errors, search caps, shortlist truncation, imperfect voice selection, pickup assumptions and unrecognized near duplicates are visible limitations. The local HTML review packet is unlabelled; basic synthesis follows the source tempo map and does not reproduce source audio or instruments.

{'The audit also re-extracted every successful source and compared the complete selected output and detector evidence.' if reextracted else 'The full artifact audit did not repeat candidate generation and selection for every successful source. Stored candidate-order hashes and selection decisions are not fully replayed by that audit. Separate sample reextraction results, when supplied, apply only to their declared cohort.'} The precise audit scope is recorded in `release.json` and `audit.json`.

{('A supplementary completed selection replay is included in `evidence/selection_replay/`. It re-extracted ' + str(replay_summary['selection_count']) + ' selected successful sources with zero failed cases. This is separate from the primary artifact audit and does not change `audit.json`. The all-successful flag is true only when the replay cohort equals every status-ok source in the manifest; this replay covers ' + ('every status-ok source.' if replay_summary['selection_covers_all_successful_sources'] else 'a bounded sample of successful sources.') + ' Its completion receipt is bound by SHA256 in `release.json`.') if replay_summary else ''}

{('A fixed note-structure prior changes candidate ordering before closed selection. The original recurrence score remains separate from the adjusted ranking score. This optional mode prefers monophonic parts and does not establish that their phrases are hooks or preferable sampling material.') if algorithm == 'aligned_melody' else ''}

## Splits and duplicates

Artist keys, normalized title variants, exact bytes and exact normalized arrangements form connected split groups. Canonical phrase families crossing splits are excluded from later splits. Splits are deterministic for this fixed manifest. This grouping is incomplete for aliases, covers and near duplicates, and should not be presented as a leakage-free benchmark.

{('A supplementary view is included in `views/duplicate_screening/`. Join its phrase rows to `phrases.jsonl` by `phrase_id`, require a one-to-one match and use `screened_split`. It preserves the original split and quarantines whole original groups in later splits when connected by heuristic duplicate evidence. Keep `overlap_excluded` and `duplicate_excluded` out of train/validation/test. The stricter view changes the artist distribution and is a sensitivity analysis, not proof that all musical overlap is absent. Screened phrase counts: ' + canonical_json(screening_summary['phrase_split_counts']) + '.') if screening_summary else 'No supplementary near-duplicate screening view is included in this bundle.'}

## Rights and publication status

The project software uses the existing repository MIT licence, reproduced in `SOFTWARE_LICENSE.txt`. It does not grant rights to source compositions or MIDI arrangements. The upstream Lakh page states CC BY 4.0 and notes inconsistent source attribution: https://colinraffel.com/projects/lmd/

This local packaging command performs no upload. The public dataset and demo are documented in the project README. Underlying musical attribution and unresolved duplicate groups remain limitations. Listener labels are outside this release. No DOI, venue acceptance or human evaluation is claimed.

## Integrity

The metadata bundle's `SHA256SUMS` lists every metadata payload other than the checksum list itself. The optional archive contains a complete `SHA256SUMS` covering metadata and extracted MIDI payloads. `release.json` records counts and source fingerprints. Recreate outputs from the saved provenance and source corpus, then compare musical fields and hashes; runtime and local Git metadata can differ. All timestamps in the optional archive are normalized for deterministic packaging.
"""
    (output/"DATASET_CARD.md").write_text(card, encoding="utf-8")
    metadata = {"schema_version": "samuged-local-release-v1", "publication_status": "unpublished_local_candidate",
                "run_key": summary["run_key"], "full_local_corpus": full,
                "algorithm": algorithm, "audit_scope": audit_scope,
                "source_files": summary["source_files"], "phrase_rows": len(rows),
                "unique_family_counts": dict(Counter(row["kind"] for row in representatives)),
                "midi_payloads": len(payloads), "source_manifest_sha256": summary["source_manifest_sha256"],
                "phrase_manifest_sha256": summary["phrase_manifest_sha256"],
                "human_labels_collected": False, "musical_redistribution_cleared": False}
    if replay_summary is not None:
        metadata["selection_replay"] = replay_summary
    if screening_summary is not None:
        metadata["duplicate_screening"] = {
            "summary_sha256": file_digest(screening/"summary.json"),
            "phrase_split_counts": screening_summary["phrase_split_counts"],
            "excluded_source_groups": screening_summary["excluded_source_groups"],
            "duplicate_report_sha256": screening_summary["duplicate_report_sha256"],
        }
    atomic_json(output/"release.json", metadata)
    metadata_payloads = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            name = path.relative_to(output).as_posix()
            metadata_payloads[name] = path
    if set(payloads) & set(metadata_payloads):
        raise ValueError("MIDI and metadata payload names collide in archive")
    metadata_checksums = "".join(
        f"{file_digest(path)}  {name}\n" for name, path in sorted(metadata_payloads.items())
    )
    (output/"SHA256SUMS").write_text(metadata_checksums, encoding="utf-8")
    if archive:
        archive_payloads = {**payloads, **metadata_payloads}
        archive_checksums = "".join(
            f"{file_digest(path)}  {name}\n" for name, path in sorted(archive_payloads.items())
        ).encode("utf-8")
        target = archive_target
        temp = target.with_suffix(target.suffix+".tmp")
        with temp.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for name, path in sorted(archive_payloads.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = path.stat().st_size, 0o644
                    info.mtime = info.uid = info.gid = 0
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
                info = tarfile.TarInfo("SHA256SUMS")
                info.size, info.mode = len(archive_checksums), 0o644
                info.mtime = info.uid = info.gid = 0
                tar.addfile(info, io.BytesIO(archive_checksums))
        temp.replace(target)
        receipt = {"archive": target.name, "sha256": file_digest(target), "bytes": target.stat().st_size,
                   "members": len(archive_payloads) + 1, "run_key": summary["run_key"]}
        atomic_json(archive_receipt, receipt)
        metadata["archive_receipt"] = receipt
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-pilot", action="store_true")
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--screening", type=Path)
    parser.add_argument("--selection-replay", type=Path,
                        help="include a completed supplementary selection replay")
    args = parser.parse_args()
    print(json.dumps(package(args.dataset, args.output, allow_pilot=args.allow_pilot,
                             archive=args.archive, screening=args.screening,
                             selection_replay=args.selection_replay), indent=2))
