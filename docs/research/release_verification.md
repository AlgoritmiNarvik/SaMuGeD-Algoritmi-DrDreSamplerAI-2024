# Portable release verification

## Purpose

`scripts/verify_release.py` verifies a local SaMuGeD metadata release without access to the source MIDI corpus. It can also verify the optional package archive without extracting it, or verify a complete tree that was safely extracted from the archive.

The verifier writes one JSON report only after every requested check passes. It refuses to overwrite an existing report, write inside the release directory or replace the archive or its receipt.

## Metadata checks

For a metadata directory, the verifier:

- Rejects symbolic links, special files and unsafe relative paths.
- Requires `SHA256SUMS` to list every regular metadata file except the checksum list itself, exactly once.
- Recomputes every listed file hash and rejects unlisted or stale entries.
- Reads JSONL records using LF bytes as separators. Unicode line controls such as U+0085 inside JSON strings do not create records.
- Checks unique source and phrase IDs, source references, phrase kind counts, family counts and known MIDI paths and hashes.
- Recomputes `ok` and `error` source counts. It compares them with `summary.json` and the audit counts for verified sources and reported input errors. Missing zero valued count keys are treated consistently as zero.
- Compares the audit MIDI verification count with the number of unique MIDI payload paths in the phrase manifest.
- Checks one run key across `release.json`, `summary.json`, `audit.json` and `build_config.json`.
- Checks the audit bindings to `sources.jsonl`, `phrases.jsonl`, `summary.json` and `build_config.json`.
- Checks the detailed `audit_scope` summary when it is present. Early schema v1 packages can omit this later optional field because the bound `audit.json` remains the primary evidence.
- Recomputes optional duplicate screening through `verify_screening`.
- Recomputes an included selection replay binding through `package_dataset._selection_replay_binding` and compares it with both summaries recorded in `release.json`.
- Repeats the complete metadata file inventory, hashes and sizes immediately before writing the report. A file added, removed or changed during verification causes failure.

A metadata only result proves byte integrity and consistency among the recorded metadata files. It does not verify MIDI payload bytes because those files are intentionally absent from the metadata directory.

## Extracted archive checks

With `--extracted`, the release path must be the flat root produced by safely extracting one package archive. The archive `SHA256SUMS` must list every regular payload in that tree, including metadata and MIDI, exactly once. The verifier rejects symbolic links, special files, unlisted files, stale checksum entries and unsafe paths.

Every MIDI path must use the declared kind and phrase ID. Every declared MIDI file must be present and its checksum must match both `SHA256SUMS` and `phrases.jsonl`. Undeclared files below `midi/` are rejected. The report records metadata and MIDI file and byte counts separately. Optional screening and selection replay evidence is verified in the same way as metadata mode. A complete inventory, hash and size check is repeated immediately before the report is written.

This mode is intended for an archive recipient who does not also have the metadata sibling directory. It verifies the extracted bytes and their internal bindings. It cannot verify the compressed archive hash or its sibling receipt after extraction and it does not authenticate the publisher. It also does not repeat extraction from the absent full song sources.

## Archive checks

With `--archive`, the verifier reads the gzip tar stream without extracting members. It rejects duplicate members, links, directories, special members, unsafe paths and any member outside the exact expected set.

The archive must contain every metadata payload listed by the directory checksum file, every unique MIDI path and hash declared by `phrases.jsonl` and one archive `SHA256SUMS`. The archive checksum list must cover every payload member exactly. Metadata member hashes and sizes are compared with the release directory. MIDI member hashes are compared with the phrase manifest.

The sibling `<archive>.json` receipt must match the archive filename, compressed byte count, SHA256, member count and release run key.

The verifier hashes the archive and receipt again after reading every archive member. This endpoint check rejects an archive or receipt that changes during verification.

These checks establish internal byte consistency. They do not authenticate the publisher, validate the absent full song sources, repeat musical extraction, assess phrase quality or establish redistribution rights. A separate signature or trusted publication channel is needed for authenticity.

The report records SHA256 and byte size for the verifier, package and screening code and their statically discovered local import closure. These hashes identify the local verification implementation. They are not authenticated publisher provenance.

## Commands

Activate the project environment first:

```bash
source .venv/bin/activate
```

Verify metadata only:

```bash
python scripts/verify_release.py \
  --release research_local/releases/reference_v03 \
  --output research_local/releases/reference_v03.metadata_verification.json
```

Verify metadata and the archive:

```bash
python scripts/verify_release.py \
  --release research_local/releases/reference_v03 \
  --archive research_local/releases/reference_v03.tar.gz \
  --output research_local/releases/reference_v03.portable_verification_v02.json
```

Verify a safely extracted archive tree when the separate metadata directory is unavailable:

```bash
python scripts/verify_release.py \
  --release /path/to/new-empty-directory-after-extraction \
  --extracted \
  --output /path/to/extracted-tree.verification.json
```

`--archive` and `--extracted` cannot be combined. The successful report uses scope `metadata_only` for the metadata directory, `metadata_and_archive` for the stream checked archive or `metadata_and_extracted_midi` for the extracted tree.
