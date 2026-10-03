"""Build public archives and Parquet views from verified local release snapshots.

This command performs no upload. It preserves the old snapshots and their
musical payloads, replacing only public presentation and publication metadata.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def public_card(release: dict) -> str:
    replay = release.get("selection_replay", {})
    return f"""# SaMuGeD Earworms (Ostinato / Catchy musical hooks)

Recurring melodic phrases and separate drum patterns.

Authors: Peiyi Wu (pewu10205@uit.no), Asle Fjæran Øren (asleoren@gmail.com), Shayan Dadman (shayan.dadman@uit.no) and Almaz Ermilov (almaz.ermilov@uit.no).

Research release from the processed Lakh MIDI Clean snapshot.

The archive contains {release['phrase_rows']:,} source verified MIDI phrases
under the `{release['algorithm']}` method. It includes melodic phrases and
separate percussion patterns. Full source songs are not bundled.

Read CONSUMER_GUIDE.md for ticks, splits, search limits and verification.
The complete artifact audit passed. Selection replay covered
{replay.get('selection_count', 0):,} successful sources. These checks establish
recorded symbolic consistency, not catchiness or recognition.

There are no listener ratings. Published recognition or earworm findings
used in the separate demo support song level evidence only.

## License and attribution

The upstream Lakh collection states CC BY 4.0. See
https://colinraffel.com/projects/lmd/ and cite Colin Raffel (2016),
Learning Based Methods for Comparing Sequences, with Applications to
Audio to MIDI Alignment and Matching. Lakh attribution is incomplete.
No independent clearance of underlying compositions or arrangements is claimed.
The project code uses MIT, reproduced in SOFTWARE_LICENSE.txt.
External evaluation datasets are excluded from this release.

Dataset https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases
Demo https://huggingface.co/spaces/AlmazErmilov/samuged-earworms
Code https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSamplerAI-2024
"""


def repackage(metadata: Path, archive: Path, output: Path, name: str) -> dict:
    target = output / "metadata" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(metadata, target)
    release = json.loads((target / "release.json").read_text())
    release["publication_status"] = "public_research_release"
    release["collection_license"] = "CC-BY-4.0"
    release["upstream_collection"] = "https://colinraffel.com/projects/lmd/"
    (target / "release.json").write_text(json.dumps(release, sort_keys=True) + "\n")
    (target / "DATASET_CARD.md").write_text(public_card(release))
    review = target / "review.html"
    if review.exists():
        review.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>SaMuGeD Earworms</title><h1>SaMuGeD Earworms</h1><p>Ostinato / Catchy musical hooks.</p><p><a href="https://huggingface.co/spaces/AlmazErmilov/samuged-earworms">Open the loop player</a></p><p>Listener labels are not part of this release.</p></html>')
    metadata_files = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
    metadata_hashes = {n: digest(p) for n, p in metadata_files.items()}
    (target / "SHA256SUMS").write_text("".join(f"{v}  {n}\n" for n, v in sorted(metadata_hashes.items())))
    destination = output / "archives" / f"{name}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    checksums = {}
    with destination.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w|") as out, tarfile.open(archive, "r|gz") as src:
            for member in src:
                path = PurePosixPath(member.name)
                if (not member.isreg() or path.is_absolute() or ".." in path.parts
                        or member.name != path.as_posix() or any(c in member.name for c in ("\\", "\n", "\r"))
                        or member.name in seen):
                    raise ValueError("unsafe or duplicate archive member")
                seen.add(member.name)
                if member.name == "SHA256SUMS":
                    continue
                payload = metadata_files[member.name].read_bytes() if member.name in metadata_files else src.extractfile(member).read()
                checksums[member.name] = hashlib.sha256(payload).hexdigest()
                info = tarfile.TarInfo(member.name)
                info.size, info.mode = len(payload), 0o644
                out.addfile(info, io.BytesIO(payload))
            if not set(metadata_files) <= seen:
                raise ValueError("metadata member absent from original archive")
            payload = "".join(f"{v}  {n}\n" for n, v in sorted(checksums.items())).encode()
            info = tarfile.TarInfo("SHA256SUMS")
            info.size, info.mode = len(payload), 0o644
            out.addfile(info, io.BytesIO(payload))
    receipt = {"archive": destination.name, "sha256": digest(destination), "bytes": destination.stat().st_size,
               "members": len(checksums) + 1, "run_key": release["run_key"], "original_archive_sha256": digest(archive)}
    destination.with_suffix(".gz.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    return receipt


def parquet_views(dataset: Path, output: Path, name: str) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields = [pa.field(k, pa.string()) for k in (
        "phrase_id", "source_id", "source_path", "source_sha256", "artist", "title", "kind",
        "family_id", "split", "split_group", "part_name", "occurrences_json", "matcher_flags_json")]
    fields += [pa.field(k, pa.int64()) for k in ("start_tick", "end_tick", "ticks_per_beat", "note_count", "occurrence_count", "program")]
    fields += [pa.field("duration_beats", pa.float64()), pa.field("recurrence_score", pa.float64())]
    fields += [pa.field(k, pa.list_(pa.float64())) for k in ("onsets_beats", "durations_beats")]
    fields += [pa.field(k, pa.list_(pa.int64())) for k in ("pitches", "velocities")]
    fields += [pa.field("midi_bytes", pa.binary()), pa.field("midi_sha256", pa.string())]
    schema = pa.schema(fields)
    writers, buffers, counts = {}, {}, {}
    try:
        for kind in ("melodic", "percussion"):
            path = output / "data" / f"{name}_{kind}" / "all.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            writers[kind] = pq.ParquetWriter(path, schema, compression="zstd")
            buffers[kind], counts[kind] = [], 0
        with (dataset / "phrases.jsonl").open() as stream:
            for line in stream:
                r = json.loads(line)
                midi = dataset / r["midi_path"]
                if not midi.resolve().is_relative_to(dataset.resolve()) or digest(midi) != r["midi_sha256"]:
                    raise ValueError("MIDI hash or path mismatch")
                v = {k: r.get(k) for k in schema.names}
                v.update(artist=r["artist_from_path"], title=r["title_from_path"],
                         occurrences_json=json.dumps(r["occurrences"], separators=(",", ":")),
                         matcher_flags_json=json.dumps(r.get("matcher_flags", {}), sort_keys=True), midi_bytes=midi.read_bytes())
                kind = r["kind"]
                buffers[kind].append(v)
                counts[kind] += 1
                if len(buffers[kind]) == 1000:
                    writers[kind].write_table(pa.Table.from_pylist(buffers[kind], schema=schema))
                    buffers[kind].clear()
        for kind in writers:
            if buffers[kind]:
                writers[kind].write_table(pa.Table.from_pylist(buffers[kind], schema=schema))
    finally:
        for writer in writers.values():
            writer.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--releases", type=Path, default=Path("research_local/releases"))
    parser.add_argument("--closed-dataset", type=Path, default=Path("research_local/lakh_aligned_closed_v01"))
    parser.add_argument("--reference-dataset", type=Path, default=Path("research_local/lakh_phrases_v03"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {}
    for old, name, dataset in (("closed_v01", "closed", args.closed_dataset), ("reference_v04", "reference", args.reference_dataset)):
        result[name] = {"archive": repackage(args.releases / old, args.releases / f"{old}.tar.gz", args.output, name),
                        "rows": parquet_views(dataset, args.output, name)}
    (args.output / "build_receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
