"""Prepare a bounded POP909 MIDI cohort for an external part-role study.

The selection manifest is written before any selected MIDI bytes are fetched.
This script does not run a detector or assign a role label.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from samuged.midi import load_midi


SCHEMA_VERSION = "samuged-pop909-role-v1"
SELECTION_VERSION = "samuged-pop909-role-selection-v1"
NAMESPACE = "samuged-pop909-role-v1"
REPOSITORY = "https://github.com/music-x-lab/POP909-Dataset"
COMMIT = "d83e6edba6872a704f5d3b8b32f5cb540088dae6"
TREE_URL = f"https://api.github.com/repos/music-x-lab/POP909-Dataset/git/trees/{COMMIT}?recursive=1"
RAW_TEMPLATE = f"https://raw.githubusercontent.com/music-x-lab/POP909-Dataset/{COMMIT}/POP909/{{song_id}}/{{song_id}}.mid"
LICENSE_URL = f"{REPOSITORY}/blob/{COMMIT}/LICENSE"
README_URL = f"{REPOSITORY}/blob/{COMMIT}/README.md"
EXCLUDED_IDS = ("065", "284", "310", "422", "449", "464")
TOTAL_SELECTED = 180
DEVELOPMENT_COUNT = 60
MAX_TOTAL_BYTES = 100 * 1024 * 1024
SONG_PATH = re.compile(r"^POP909/(?P<song_id>[0-9]{3})/(?P=song_id)\.mid$")


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(_canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _get_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "samuged-pop909-role-preparer/1"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _tree_song_ids(tree: dict[str, Any]) -> list[str]:
    if tree.get("sha") != COMMIT or tree.get("truncated"):
        raise ValueError("official repository tree is not the requested immutable commit")
    ids = []
    for item in tree.get("tree", []):
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        match = SONG_PATH.fullmatch(str(item.get("path", "")))
        if match:
            ids.append(match.group("song_id"))
    ids = sorted(set(ids))
    if len(ids) < TOTAL_SELECTED + len(EXCLUDED_IDS):
        raise ValueError(f"official tree contains too few POP909 song files: {len(ids)}")
    return ids


def _selection(song_ids: list[str]) -> dict[str, Any]:
    eligible = [song_id for song_id in song_ids if song_id not in EXCLUDED_IDS]
    ranked = sorted(
        eligible,
        key=lambda song_id: (
            sha256(f"{NAMESPACE}\0{song_id}".encode()).hexdigest(),
            song_id,
        ),
    )
    selected = ranked[:TOTAL_SELECTED]
    records = [
        {
            "song_id": song_id,
            "rank_sha256": sha256(f"{NAMESPACE}\0{song_id}".encode()).hexdigest(),
            "split": "development" if index < DEVELOPMENT_COUNT else "heldout",
            "upstream_path": f"POP909/{song_id}/{song_id}.mid",
        }
        for index, song_id in enumerate(selected)
    ]
    payload = {
        "schema_version": SELECTION_VERSION,
        "namespace": NAMESPACE,
        "upstream": {
            "repository": REPOSITORY,
            "commit_sha": COMMIT,
            "tree_url": TREE_URL,
            "path_template": "POP909/{song_id}/{song_id}.mid",
            "license_url": LICENSE_URL,
            "readme_url": README_URL,
        },
        "excluded_song_ids": list(EXCLUDED_IDS),
        "candidate_song_count": len(eligible),
        "selected_song_count": len(records),
        "development_count": DEVELOPMENT_COUNT,
        "heldout_count": len(records) - DEVELOPMENT_COUNT,
        "selected": records,
    }
    payload["selection_sha256"] = sha256(_canonical(payload)).hexdigest()
    return payload


class DownloadLimitExceeded(RuntimeError):
    pass


def _download(url: str, target: Path, downloaded: int) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "samuged-pop909-role-preparer/1"})
    with urlopen(request, timeout=120) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None and downloaded + int(declared) > MAX_TOTAL_BYTES:
            raise DownloadLimitExceeded("download cap of 100 MiB would be exceeded")
        total = 0
        digest = sha256()
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("wb", dir=target.parent, prefix=f".{target.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if downloaded + total + len(chunk) > MAX_TOTAL_BYTES:
                    temporary.unlink(missing_ok=True)
                    raise DownloadLimitExceeded("download cap of 100 MiB was exceeded")
                stream.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    return total, digest.hexdigest()


def _source_record(selection: dict[str, Any], selected: dict[str, Any], target: Path,
                   source_bytes: int | None, source_sha256: str | None,
                   parse: dict[str, Any]) -> dict[str, Any]:
    record = {
        "song_id": selected["song_id"],
        "split": selected["split"],
        "selection_rank_sha256": selected["rank_sha256"],
        "upstream_path": selected["upstream_path"],
        "upstream_url": RAW_TEMPLATE.format(song_id=selected["song_id"]),
        "local_path": target.relative_to(target.parents[1]).as_posix(),
        "source_bytes": source_bytes,
        "source_sha256": source_sha256,
        **parse,
    }
    return record


def prepare(output: Path) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise FileExistsError(f"output must be a new or empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    tree = _get_json(TREE_URL)
    song_ids = _tree_song_ids(tree)
    selection = _selection(song_ids)
    # This is intentionally the first local artifact. It freezes the cohort
    # before any selected MIDI request or role inspection is attempted.
    _write_json(output / "selection_manifest.json", selection)
    selection_hash = sha256((output / "selection_manifest.json").read_bytes()).hexdigest()

    records: list[dict[str, Any]] = []
    total_bytes = 0
    errors = 0
    for selected in selection["selected"]:
        song_id = selected["song_id"]
        target = output / "midi" / f"{song_id}.mid"
        url = RAW_TEMPLATE.format(song_id=song_id)
        try:
            source_bytes, source_sha256 = _download(url, target, total_bytes)
            total_bytes += source_bytes
            song = load_midi(target)
            parts = [
                {
                    "part_index": part.index,
                    "track": part.track,
                    "channel": part.channel,
                    "program": part.program,
                    "name": part.name,
                    "is_drum": part.is_drum,
                    "note_count": len(part.notes),
                }
                for part in song.parts
            ]
            parse = {
                "parse_status": "ok",
                "ticks_per_beat": song.ticks_per_beat,
                "part_count": len(parts),
                "parts": parts,
                "warnings": song.warnings,
            }
        except DownloadLimitExceeded:
            raise
        except (HTTPError, URLError, OSError, ValueError, TypeError) as exc:
            errors += 1
            source_bytes = target.stat().st_size if target.is_file() else None
            source_sha256 = sha256(target.read_bytes()).hexdigest() if target.is_file() else None
            parse = {
                "parse_status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            }
        records.append(_source_record(selection, selected, target, source_bytes, source_sha256, parse))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "selection_manifest_sha256": selection_hash,
        "selection_manifest": "selection_manifest.json",
        "upstream": selection["upstream"],
        "source_root": "midi",
        "selected_song_count": len(records),
        "downloaded_bytes": total_bytes,
        "parse_ok": sum(record["parse_status"] == "ok" for record in records),
        "parse_errors": errors,
        "records": records,
    }
    manifest["manifest_sha256"] = sha256(_canonical(manifest)).hexdigest()
    _write_json(output / "source_manifest.json", manifest)
    receipt = {
        "schema_version": "samuged-pop909-role-receipt-v1",
        "status": "completed" if errors == 0 else "completed_with_errors",
        "selection_manifest_sha256": selection_hash,
        "source_manifest_sha256": manifest["manifest_sha256"],
        "selected_song_count": len(records),
        "downloaded_bytes": total_bytes,
        "parse_errors": errors,
        "download_limit_bytes": MAX_TOTAL_BYTES,
        "upstream": selection["upstream"],
        "claim_boundary": "external POP909 source cohort only; no detector evaluation or role labels",
    }
    receipt["receipt_sha256"] = sha256(_canonical(receipt)).hexdigest()
    _write_json(output / "download_receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = prepare(args.output)
    except (FileExistsError, OSError, RuntimeError, ValueError, HTTPError, URLError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
