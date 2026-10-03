"""Select a documented Schism listening supplement from a separate detector build."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from scripts.analyze_top_phrases import compact, verify_occurrences
from scripts.make_review import _review_candidate

SOURCE_SHA256 = "d61a717456e9d5004f2848c648893c70010c1bc857aba78e93d0b29678df1db0"
SOURCE_URL = "https://midifind.com/files/t/tool/tool_schism_7/1822-1-0-60610"
FEATURED_ID = "39970bcef6d53dae542b2402daee94aa"
SELECTED_IDS = (FEATURED_ID, "8dc288ecbf4573626f69174254521834",
                "1dcc2baffdcfd162e0b4c22ae84619b2", "e30bf44c23d800be07227032dbc16dff",
                "79382eaaff3b339f5db75a5ba06bd5e2", "c62797936df53a48c10527628a39fbbc")


def curate(dataset: Path, sources: Path, output: Path) -> dict:
    rows = {r["phrase_id"]: r for r in map(json.loads, (dataset / "phrases.jsonl").read_text().splitlines())}
    source = json.loads((dataset / "sources.jsonl").read_text())
    if source["source_sha256"] != SOURCE_SHA256:
        raise ValueError("Schism source differs from the reviewed arrangement")
    output.mkdir(parents=True, exist_ok=False)
    selected, snippets = [], {}
    for rank, pid in enumerate(SELECTED_IDS, 1):
        row = rows[pid]
        verify_occurrences(row)
        target = output / row["midi_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (dataset / row["midi_path"]).read_bytes()
        if sha256(data).hexdigest() != row["midi_sha256"]:
            raise ValueError("detector MIDI hash mismatch")
        target.write_bytes(data)
        candidate = compact(row)
        candidate.update(rank=rank, source_sha256=SOURCE_SHA256, midi_sha256=row["midi_sha256"],
            midi_file=f"midi/{pid}.mid", search_limited=source["search_limited"],
            curation_truncated=source["curation_truncated"],
            occurrence_ticks=[{"start": o["start_tick"], "end": o["end_tick"]} for o in row["occurrences"]],
            rationale="Personal listening selection of contrasting bass, guitar and drum phrases. Extracted by aligned_closed from a separate downloaded MIDI arrangement.",
            external_source_url=SOURCE_URL, featured=pid == FEATURED_ID)
        selected.append(candidate)
        snippets[pid] = _review_candidate(row, source, sources.resolve(), pid, {})["snippets"]
    packet = {"version": "samuged-schism-listening-v1", "candidates": selected,
              "featured_id": FEATURED_ID, "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
              "rights": "External MIDI arrangement. The page offers downloads but gives no explicit redistribution license. This supplement is not covered by the Lakh attribution claim.",
              "claim": "Curated listening supplement outside the audited Lakh corpus. Featured position is editorial, not a recurrence or popularity rank.",
              "inputs": {n: sha256((dataset / n).read_bytes()).hexdigest() for n in ("phrases.jsonl", "sources.jsonl", "build_config.json")}}
    (output / "selection.json").write_text(json.dumps(packet, indent=2) + "\n")
    (output / "atlas.json").write_text(json.dumps({"snippets": snippets, "featured": selected[0]}, indent=2) + "\n")
    for name in ("phrases.jsonl", "sources.jsonl", "build_config.json", "summary.json"):
        shutil.copyfile(dataset / name, output / name)
    return packet


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(len(curate(args.dataset, args.source, args.output)["candidates"]))
