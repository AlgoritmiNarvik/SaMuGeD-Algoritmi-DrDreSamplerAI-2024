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


def package(dataset: Path, output: Path, *, allow_pilot=False, archive=False,
            screening: Path | None = None) -> dict:
    dataset, output = dataset.resolve(strict=True), output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("release metadata must be outside the extraction directory")
    summary = json.loads((dataset/"summary.json").read_text())
    audit = json.loads((dataset/"audit.json").read_text())
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
    rows = [json.loads(line) for line in (dataset/"phrases.jsonl").read_text().splitlines()]
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
    repository = Path(__file__).resolve().parents[1]
    if (repository/"schemas").is_dir():
        shutil.copytree(repository/"schemas", output/"schemas")
    shutil.copyfile(repository/"LICENSE", output/"SOFTWARE_LICENSE.txt")
    card = f"""# SaMuGeD recurring phrase candidates

Local candidate release, unpublished. Scope: {'full local corpus' if full else 'pilot only'}.

## Purpose

The collection contains repeated symbolic melodic phrases and separate drum patterns. It supports recurrence retrieval, source reconstruction and annotation experiments. It does not contain verified earworm, hook, salience or human phrase-quality labels.

## Contents

- Source files accounted for: {summary['source_files']:,}.
- Processing outcomes: {canonical_json(summary['source_outcomes'])}.
- Phrase counts: {canonical_json(summary['phrase_counts'])}.
- Unique canonical families: {len(representatives):,}.
- Exported MIDI files: {len(payloads):,}.
- Run fingerprint: `{summary['run_key']}`.

`sources.jsonl` accounts for all selected input paths, including failures and no-match files. `phrases.jsonl` keeps the per-source candidate collection. `views/*.unique.jsonl` selects one representative per canonical family, and `views/family_membership.jsonl` preserves all source links with phrase, source file and split group counts. These are file and grouping frequencies, not composition counts. Family equality is the detector's stated canonicalization, not proof of musical identity. Rows marked `overlap_excluded` must not be used as train/validation/test examples.

MIDI files use paths in `midi_path`, relative to the complete archive root. This metadata directory intentionally does not copy MIDI payloads; the optional archive includes them. Original full-song source MIDI files are not bundled. Source-relative paths and SHA256 values identify the local Lakh MIDI Clean inventory.

## Method and quality

Melody uses per-part onset skyline and verified recurrence under the recorded pitch/timing model. Percussion preserves simultaneous kit pitches and uses meter-aware patterns without transposition. Scores rank structural recurrence only. Detailed parameters and executable source snapshots are in `build_config.json` and `provenance/`.

The independent audit checks source reconstruction, manifest membership, splits and MIDI export semantics. A passing audit proves those recorded checks, not perceptual quality. Parse errors, search caps, shortlist truncation, imperfect voice selection, pickup assumptions and unrecognized near duplicates are visible limitations. The local HTML review packet is unlabelled; basic synthesis follows the source tempo map and does not reproduce source audio or instruments.

## Splits and duplicates

Artist keys, normalized title variants, exact bytes and exact normalized arrangements form connected split groups. Canonical phrase families crossing splits are excluded from later splits. Splits are deterministic for this fixed manifest. This grouping is incomplete for aliases, covers and near duplicates, and should not be presented as a leakage-free benchmark.

{('A supplementary view is included in `views/duplicate_screening/`. Join its phrase rows to `phrases.jsonl` by `phrase_id`, require a one-to-one match and use `screened_split`. It preserves the original split and quarantines whole original groups in later splits when connected by heuristic duplicate evidence. Keep `overlap_excluded` and `duplicate_excluded` out of train/validation/test. The stricter view changes the artist distribution and is a sensitivity analysis, not proof that all musical overlap is absent. Screened phrase counts: ' + canonical_json(screening_summary['phrase_split_counts']) + '.') if screening_summary else 'No supplementary near-duplicate screening view is included in this bundle.'}

## Rights and publication status

The project software uses the existing repository MIT licence, reproduced in `SOFTWARE_LICENSE.txt`. It does not grant rights to source compositions or MIDI arrangements. The upstream Lakh page states CC BY 4.0 and notes inconsistent source attribution: https://colinraffel.com/projects/lmd/

No content has been published or uploaded. Before public release, resolve musical redistribution rights, confirm author and citation metadata, collect independent human labels and review unresolved duplicate groups. No DOI, venue acceptance or human evaluation is claimed.

## Integrity

The metadata bundle's `SHA256SUMS` lists every metadata payload other than the checksum list itself. The optional archive contains a complete `SHA256SUMS` covering metadata and extracted MIDI payloads. `release.json` records counts and source fingerprints. Recreate outputs from the saved provenance and source corpus, then compare musical fields and hashes; runtime and local Git metadata can differ. All timestamps in the optional archive are normalized for deterministic packaging.
"""
    (output/"DATASET_CARD.md").write_text(card, encoding="utf-8")
    metadata = {"schema_version": "samuged-local-release-v1", "publication_status": "unpublished_local_candidate",
                "run_key": summary["run_key"], "full_local_corpus": full,
                "source_files": summary["source_files"], "phrase_rows": len(rows),
                "unique_family_counts": dict(Counter(row["kind"] for row in representatives)),
                "midi_payloads": len(payloads), "source_manifest_sha256": summary["source_manifest_sha256"],
                "phrase_manifest_sha256": summary["phrase_manifest_sha256"],
                "human_labels_collected": False, "musical_redistribution_cleared": False}
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
    args = parser.parse_args()
    print(json.dumps(package(args.dataset, args.output, allow_pilot=args.allow_pilot,
                             archive=args.archive, screening=args.screening), indent=2))
