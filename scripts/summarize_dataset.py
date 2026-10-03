"""Produce aggregate corpus diagnostics without copying musical note arrays."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median

from samuged.dataset import atomic_json, file_digest


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": values[0], "median": median(values),
            "p90": values[round((len(values)-1)*.9)],
            "p99": values[round((len(values)-1)*.99)], "max": values[-1]}


def summarize(dataset: Path) -> dict:
    sources = [json.loads(line) for line in (dataset/"sources.jsonl").read_text().split("\n") if line.strip()]
    phrases = [json.loads(line) for line in (dataset/"phrases.jsonl").read_text().split("\n") if line.strip()]
    summary = json.loads((dataset/"summary.json").read_text())
    if file_digest(dataset/"sources.jsonl") != summary["source_manifest_sha256"] or file_digest(dataset/"phrases.jsonl") != summary["phrase_manifest_sha256"]:
        raise ValueError("manifest hash mismatch")
    ok = [s for s in sources if s["status"] == "ok"]
    part_stats = [p for s in ok for p in s.get("part_stats", [])]
    result = {
        "run_key": summary["run_key"],
        "source_manifest_sha256": summary["source_manifest_sha256"],
        "phrase_manifest_sha256": summary["phrase_manifest_sha256"],
        "source_files": len(sources), "parsed_files": len(ok),
        "source_outcomes": dict(Counter(s["outcome"] for s in sources)),
        "parse_error_types": dict(Counter(s.get("error_type", "unknown") for s in sources if s["status"] != "ok")),
        "unique_artist_keys": len({s["artist_key"] for s in sources}),
        "unique_title_groups": len({s["song_key"] for s in sources}),
        "source_split_counts": dict(Counter(s["split"] for s in sources)),
        "split_group_count": len({s["split_group"] for s in sources}),
        "normalized_arrangement_groups": distribution(Counter(s["musical_sha256"] for s in ok if s.get("note_count", 0)).values()),
        "source_notes": distribution(s["note_count"] for s in ok),
        "source_parts": distribution(s["part_count"] for s in ok),
        "worker_seconds_per_file": distribution(s["elapsed_seconds"] for s in sources),
        "warning_files": sum(bool(s.get("warnings")) for s in sources),
        "metadata_recovered_files": sum(bool(s.get("metadata_repairs")) for s in sources),
        "metadata_repair_events": sum(len(s.get("metadata_repairs", [])) for s in sources),
        "melodic_search_limited_files": sum(bool(s.get("search_limited")) for s in sources),
        "melodic_curation_truncated_files": sum(bool(s.get("curation_truncated")) for s in sources),
        "percussion_search_limited_files": sum(bool(s.get("drum_stats", {}).get("search_limited")) for s in sources),
        "melodic_parts_with_comparison_limit": sum(bool(p.get("comparison_limit_reached")) for p in part_stats),
        "melodic_parts_with_note_limit": sum(bool(p.get("note_limit_reached")) for p in part_stats),
        "melodic_parts_with_window_limit": sum(bool(p.get("window_limit_reached")) for p in part_stats),
        "melodic_parts_with_seed_saturation": sum(bool(p.get("saturated_seed_buckets")) for p in part_stats),
        "kinds": {},
        "claim_boundary": "descriptive extraction statistics; no human quality labels or memorability measurement",
    }
    for kind in sorted({p["kind"] for p in phrases}):
        rows = [p for p in phrases if p["kind"] == kind]
        families = Counter(p["family_id"] for p in rows)
        result["kinds"][kind] = {
            "phrases": len(rows), "source_files": len({p["source_id"] for p in rows}),
            "unique_families": len(families), "family_multiplicity": distribution(families.values()),
            "split_counts": dict(Counter(p["split"] for p in rows)),
            "note_count": distribution(p["note_count"] for p in rows),
            "duration_beats": distribution((p["end_tick"]-p["start_tick"])/p["ticks_per_beat"] for p in rows),
            "occurrence_count": distribution(p["occurrence_count"] for p in rows),
            "recurrence_score": distribution(p["recurrence_score"] for p in rows),
            "program_counts": dict(sorted(Counter(p.get("program", "ensemble") for p in rows).items(), key=lambda item: str(item[0]))),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.dataset)
    atomic_json(args.output, result)
    print(json.dumps({"output": str(args.output), "source_files": result["source_files"],
                      "parsed_files": result["parsed_files"]}, indent=2))
