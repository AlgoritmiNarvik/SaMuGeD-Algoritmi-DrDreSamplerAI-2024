"""Rank saved recurrence candidates, with a byte-bound chart cohort and listening UI."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import unicodedata

from scripts.make_review import _file_sha256, _review_candidate, script_safe_json

CHART_URL = "https://www.officialcharts.com/chart-news/the-best-selling-singles-of-all-time-on-the-official-uk-chart__21298/"
VERSION = "samuged-top-phrases-v1"


class ChartTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        if self.table is not None and tag == "tr":
            self.row = []
        if self.row is not None and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())


def artist_key(text):
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())
    return "".join(sorted(token for token in tokens if token != "the"))


def chart_rows(path):
    parser = ChartTable()
    parser.feed(path.read_text(encoding="utf-8"))
    tables = [table for table in parser.tables if table and table[0] == ["POS", "TITLE", "ARTIST", "YEAR", "PEAK"]]
    if len(tables) != 1:
        raise ValueError("expected exactly one Official Charts sales table")
    rows = []
    for cells in tables[0][1:]:
        if len(cells) != 5 or not cells[0].isdigit():
            raise ValueError("unexpected chart row")
        rows.append(dict(chart_rank=int(cells[0]), chart_title=cells[1], chart_artist=cells[2], year=cells[3], peak=cells[4]))
    if len({row["chart_rank"] for row in rows}) != len(rows):
        raise ValueError("duplicate chart ranks")
    return rows


def motif_eligible(row):
    """Explicit structural filter, never a perceptual quality judgment."""
    return (
        row["kind"] == "melodic"
        and row["note_count"] >= 8
        and len(set(row["pitches"])) >= 4
        and row["duration_beats"] >= 4
        and not 32 <= row["program"] <= 39
        and not re.search(r"\b(bass|basse|bajo|drums?|percussion|beat box)\b", row["part_name"], re.I)
    )


def rank_key(row):
    return (-row["occurrence_count"], -row["duration_beats"], -row["note_count"], -row["recurrence_score"], row["source_path"], row["phrase_id"])


def compact(row):
    keys = ("phrase_id", "source_id", "song_key", "family_id", "source_path", "artist_from_path", "title_from_path", "kind", "occurrence_count", "duration_beats", "note_count", "recurrence_score", "program", "part_name")
    out = {key: row.get(key) for key in keys}
    out["unique_pitches"] = len(set(row["pitches"]))
    if row["kind"] == "percussion":
        out["note_count"] = row.get("hit_count", len(row["pitches"]))
    return out


def keep_best(mapping, key, row):
    if key not in mapping or rank_key(row) < rank_key(mapping[key]):
        mapping[key] = row


def verify_occurrences(row):
    occurrences = row["occurrences"]
    if len(occurrences) != row["occurrence_count"]:
        raise ValueError("occurrence count disagrees with coordinates")
    ordered = sorted(occurrences, key=lambda value: value["start_tick"])
    if any(value["end_tick"] <= value["start_tick"] for value in ordered):
        raise ValueError("nonpositive occurrence span")
    if any(left["end_tick"] > right["start_tick"] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("overlapping occurrences")
    if not any(value["start_tick"] == row["start_tick"] and value["end_tick"] == row["end_tick"] for value in occurrences):
        raise ValueError("prototype is absent from occurrence count")


def write_csv(path, rows):
    fields = ["rank", "artist_from_path", "title_from_path", "chart_artist", "chart_title", "occurrence_count", "distinct_songs", "total_occurrences_song_max", "duration_beats", "note_count", "unique_pitches", "chart_rank", "search_limited", "curation_truncated", "source_path", "phrase_id", "family_id", "midi_file"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(dataset, source_root, chart_path, output, count=50):
    output.mkdir(parents=True, exist_ok=False)
    chart = chart_rows(chart_path)
    chart_index = {(artist_key(row["chart_artist"]), normalize(row["chart_title"])): row for row in chart}
    groups = {key: {} for key in ("motifs", "popular", "raw", "drums")}
    families = defaultdict(dict)
    counts, eligible_count, matched_chart = Counter(), 0, set()
    manifest = dataset / "phrases.jsonl"
    for line in manifest.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        counts[row["kind"]] += 1
        candidate = compact(row)
        if row["kind"] == "percussion":
            keep_best(groups["drums"], row["song_key"], candidate)
            continue
        keep_best(groups["raw"], row["song_key"], candidate)
        keep_best(families[row["family_id"]], row["song_key"], candidate)
        match = chart_index.get((artist_key(row["artist_from_path"]), normalize(row["title_from_path"])))
        if match:
            matched_chart.add(match["chart_rank"])
            candidate = {**candidate, **match}
        if motif_eligible(row):
            eligible_count += 1
            keep_best(groups["motifs"], row["song_key"], candidate)
            if match:
                keep_best(groups["popular"], row["song_key"], candidate)
    views = {key: [dict(row, rank=index + 1) for index, row in enumerate(sorted(values.values(), key=rank_key)[:count])] for key, values in groups.items()}
    family_rows = []
    for values in families.values():
        representative = min(values.values(), key=rank_key)
        family_rows.append(dict(representative, distinct_songs=len(values), total_occurrences_song_max=sum(value["occurrence_count"] for value in values.values()), song_examples=[{"artist": value["artist_from_path"], "title": value["title_from_path"], "occurrences": value["occurrence_count"]} for value in sorted(values.values(), key=rank_key)[:8]]))
    family_rows.sort(key=lambda row: (-row["distinct_songs"], -row["total_occurrences_song_max"], *rank_key(row)))
    views["families"] = [dict(row, rank=index + 1) for index, row in enumerate(family_rows[:count])]
    if any(len(rows) != count for rows in views.values()):
        raise ValueError(f"not enough candidates for each requested top {count}")
    selected = {row["phrase_id"]: row for rows in views.values() for row in rows}
    details = {}
    for line in manifest.open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            if row["phrase_id"] in selected:
                verify_occurrences(row)
                details[row["phrase_id"]] = row
    wanted_sources = {row["source_id"] for row in selected.values()}
    sources, source_count = {}, 0
    for line in (dataset / "sources.jsonl").open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            source_count += 1
            if row["source_id"] in wanted_sources:
                sources[row["source_id"]] = row
    snippets, song_cache = {}, {}
    (output / "midi").mkdir()
    for phrase_id, row in details.items():
        source = sources[row["source_id"]]
        packet = _review_candidate(row, source, source_root.resolve(), phrase_id, song_cache)
        snippets[phrase_id] = packet["snippets"]
        midi = dataset / row["midi_path"]
        if _file_sha256(midi) != row["midi_sha256"]:
            raise ValueError(f"MIDI export hash mismatch: {phrase_id}")
        shutil.copyfile(midi, output / "midi" / f"{phrase_id}.mid")
        selected[phrase_id].update(search_limited=source["search_limited"], curation_truncated=source["curation_truncated"], midi_file=f"midi/{phrase_id}.mid", source_sha256=row["source_sha256"], midi_sha256=row["midi_sha256"], occurrence_ticks=[{"start": value["start_tick"], "end": value["end_tick"]} for value in row["occurrences"]])
    for rows in views.values():
        for row in rows:
            row.update({key: selected[row["phrase_id"]][key] for key in ("search_limited", "curation_truncated", "midi_file", "source_sha256", "midi_sha256", "occurrence_ticks")})
    summary = {"schema_version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(), "algorithm": "aligned_closed", "source_files": source_count, "phrase_counts": dict(counts), "structurally_filtered_candidates": eligible_count, "eligible_distinct_songs": len(groups["motifs"]), "chart_rows": len(chart), "chart_matches_with_melodic_candidates": len(matched_chart), "chart_matches_after_structural_filter": len(groups["popular"]), "view_sizes": {key: len(rows) for key, rows in views.items()}, "unique_listening_candidates": len(details), "verified_sources": len(sources), "ranking": "descending nonoverlapping occurrence count, duration beats, note count, recurrence score; stable source path and phrase ID ties", "deduplication": "one phrase per normalized artist/title song_key; choose the maximum observed candidate across arrangements, never sum arrangement counts", "family_ranking": "descending distinct song_keys sharing the saved family_id; sum of per-song maximum counts; not a cover-song identity test", "motif_filter": "melodic, >=8 notes, >=4 distinct pitches, >=4 beats; exclude GM bass programs 32..39 and bass/drum-labelled parts", "popularity": "membership in Official Charts UK physical/download million sellers, exact normalized title and sorted artist tokens (ignoring 'the'); no fuzzy matches, aliases or current streaming inference", "name_identity": "artist and title are corpus path labels, not verified recording identities", "human_labels": 0, "claim": "algorithmic recurrence candidates; perceptual earworm status is unmeasured", "search_scope": "rankings over saved top-three-per-kind candidates per MIDI, not exhaustive searches over all possible phrases", "chart_url": CHART_URL}
    inputs = {str(path.resolve()): {"sha256": _file_sha256(path), "bytes": path.stat().st_size} for path in (manifest, dataset / "sources.jsonl", dataset / "summary.json", dataset / "build_config.json", dataset / "audit.json", dataset / "schema_validation.json", chart_path, Path(__file__), Path(__file__).with_name("top_phrases.html"), Path("scripts/make_review.py"), Path("samuged/midi.py"), Path("samuged/phrases.py"), Path("samuged/drums.py"))}
    dataset_summary = json.loads((dataset / "summary.json").read_text())
    for name, key in (("phrases.jsonl", "phrase_manifest_sha256"), ("sources.jsonl", "source_manifest_sha256")):
        if inputs[str((dataset / name).resolve())]["sha256"] != dataset_summary[key]:
            raise ValueError(f"dataset summary hash mismatch: {name}")
    receipt = {"schema_version": VERSION, "inputs": inputs, "checks": {"occurrence_counts": "pass", "nonoverlap": "pass", "prototype_counted_once": "pass", "source_hash_and_note_coordinates": "pass", "midi_export_hashes": "pass"}, "scope": {"listening_candidates": len(details), "sources": len(sources)}}
    packet = {"summary": summary, "views": views, "snippets": snippets}
    (output / "analysis.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, rows in views.items():
        write_csv(output / f"top50_{key}.csv", rows)
    template = Path(__file__).with_name("top_phrases.html").read_text(encoding="utf-8")
    # Standalone analytics has detector snippets, but no rendered source note maps.
    for asset in ('<link rel="stylesheet" href="../note_explorer.css">',
                  '<script src="../player_notes.js"></script>',
                  '<script src="../atlas_notes.js"></script>'):
        template = template.replace(asset, "")
    font_root = Path(__file__).resolve().parents[1] / "docs" / "assets" / "inter"
    shutil.copytree(font_root, output / "fonts")
    for path in sorted(font_root.iterdir()):
        receipt["inputs"][str(path.resolve())] = {"sha256": _file_sha256(path), "bytes": path.stat().st_size}
    branding_root = font_root.parent / "merkur"
    shutil.copytree(branding_root, output / "branding")
    for path in sorted(branding_root.iterdir()):
        receipt["inputs"][str(path.resolve())] = {"sha256": _file_sha256(path), "bytes": path.stat().st_size}
    shutil.copyfile(Path(__file__).with_name("loop_downloads.js"), output / "loop_downloads.js")
    (output / "index.html").write_text(template.replace("__DATA__", script_safe_json(packet)), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt["outputs"] = {str(path.relative_to(output)): {"sha256": _file_sha256(path), "bytes": path.stat().st_size} for path in sorted(output.rglob("*")) if path.is_file()}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--chart-html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.dataset, args.source, args.chart_html, args.output)


if __name__ == "__main__":
    main()
