"""Assemble a static loop player from completed curation and render receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave


def _json(path: Path):
    return json.loads(path.read_text())


def _waveform(path: Path) -> list[float]:
    import numpy as np
    with wave.open(str(path)) as wav:
        if wav.getsampwidth() != 3 or wav.getnchannels() != 2 or wav.getframerate() != 48000:
            raise ValueError("expected canonical 48 kHz stereo PCM24 audio")
        raw = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.uint8).reshape(-1, 3)
    values = raw[:, 0].astype(np.int32) | raw[:, 1].astype(np.int32) << 8 | raw[:, 2].astype(np.int32) << 16
    values[values >= 1 << 23] -= 1 << 24
    amplitudes = np.abs(values.reshape(-1, 2).astype(np.float64)).max(axis=1) / (1 << 23)
    return [round(float(chunk.max()), 4) for chunk in np.array_split(amplitudes, 96)]


def _copy_render(root: Path, output: Path) -> dict:
    manifest = _json(root / "manifest.json")
    for entry in manifest["entries"]:
        for artifact in entry["artifacts"]:
            path = root / artifact["path"]
            if not path.resolve().is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("render artifact hash mismatch or path escape")
        target = output / "audio" / entry["phrase_id"]
        if target.exists():
            original = root / entry["phrase_id"]
            paths = {p.relative_to(original) for p in original.rglob("*") if p.is_file()}
            copied = {p.relative_to(target) for p in target.rglob("*") if p.is_file()}
            if paths != copied or any((original / p).read_bytes() != (target / p).read_bytes() for p in paths):
                raise ValueError("conflicting duplicate rendered phrase")
            continue
        shutil.copytree(root / entry["phrase_id"], target)
    return {r["phrase_id"]: r for r in manifest["entries"]}


def build(base: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    recurrence = _json(base / "recurrence_selection.json")
    familiar = _json(base / "familiar" / "selection.json")
    familiar_rows = {r["phrase_id"]: r for r in map(json.loads, (base / "familiar" / "phrases.jsonl").read_text().splitlines())}
    render_entries = _copy_render(base / "recurrence_audio", output)
    render_entries.update(_copy_render(base / "familiar_audio", output))
    tool_selection = base / ("tool_selection_expanded.json" if (base / "tool_selection_expanded.json").exists() else "tool_selection.json")
    tool_root = base / ("tool_audio_expanded" if (base / "tool_audio_expanded").exists() else "tool_audio")
    tool = _json(tool_selection) if tool_selection.exists() else None
    layers = base / "tool_layers"
    diagrams = _json(layers / "rhythm_diagrams.json") if layers.exists() else {}
    if tool is not None:
        render_entries.update(_copy_render(tool_root, output))
    if layers.exists():
        render_entries.update(_copy_render(layers, output))
    provenance = output / "rendering"
    provenance.mkdir()
    for name, root in (("recurrence", base / "recurrence_audio"), ("familiar", base / "familiar_audio"), ("tool", tool_root), ("tool_layers", layers)):
        if name == "tool" and tool is None:
            continue
        if name == "tool_layers" and not layers.exists():
            continue
        for filename in ("manifest.json", "receipt.json"):
            shutil.copyfile(root / filename, provenance / f"{name}_{filename}")
    shutil.copyfile(base / "recurrence_selection.json", provenance / "recurrence_selection.json")
    shutil.copyfile(base / "familiar/selection.json", provenance / "familiar_selection.json")
    if tool is not None:
        shutil.copyfile(tool_selection, provenance / "tool_selection.json")
    if layers.exists():
        shutil.copyfile(layers / "rhythm_diagrams.json", provenance / "tool_rhythm_diagrams.json")
    groups = {
        "familiar": {"title": "Familiar hooks", "description": "Nine songs from the published Hooked on Music recognition list and one frequently reported earworm song. Order follows published song recognition rank within the available songs, Journey is a separate evidence class. Exact MIDI fragments have no listener validation.", "rows": []},
        "motifs": {"title": "Repeated motifs", "description": "The fifty most repeated saved melodic motifs after a structural note diversity filter. One normalized artist and title per position. Frequencies are within MIDI arrangements, not listener popularity.", "rows": []},
        "popular": {"title": "Popular songs", "description": "Fifty motifs from exactly matched UK million selling singles. Order follows MIDI recurrence, not sales rank. Source arrangements can differ from the original songs.", "rows": []},
        "drums": {"title": "Drum patterns", "description": "The fifty most repeated saved percussion patterns. Kit pitches and simultaneous hits are preserved. These are rhythm loops, not claims about memorable melodies.", "rows": []},
    }
    if tool is not None:
        groups["tool"] = {
            "title": "Tool motifs",
            "description": "A small tribute to one of Almaz Ermilov's favourite bands. Tool turns repetition into movement through layered rhythms and shifting accents. Explore riffs alone, then add drums from the same passage. MIDI arrangements can simplify the originals.",
            "listening_note": "Listen for where the riff and drums meet, where they pull apart and how the loop returns.",
            "rows": [],
        }
    groups = {key: groups[key] for key in ("popular", "familiar", "motifs", "drums", "tool") if key in groups}
    rows_by_group = {**recurrence["views"], "familiar": familiar["candidates"]}
    if tool is not None:
        rows_by_group["tool"] = tool["candidates"]
    song_counts = {}
    for group, selections in rows_by_group.items():
        for rank, selection in enumerate(selections, 1):
            row = familiar_rows[selection["phrase_id"]] if group == "familiar" else selection
            pid = row["phrase_id"]
            metadata = _json(output / "audio" / pid / "metadata.json")
            tempo = metadata["tempo_changes"][0]["microseconds_per_beat"]
            period = metadata["period"]
            evidence = selection.get("song_evidence_type", "symbolic_recurrence")
            statement = ("Song level recognition evidence. This selected fragment has no listener recognition labels." if evidence == "hooked_on_music_song_recognition" else
                         "Song level involuntary musical imagery evidence. This selected fragment has no listener earworm labels." if group == "familiar" else
                         "Structural recurrence in the saved MIDI arrangement. No perceptual labels.")
            song_kind = (row["song_key"], row["kind"])
            if group == "tool":
                song_counts[song_kind] = song_counts.get(song_kind, 0) + 1
            title = row["title_from_path"].replace("_", " ")
            if group == "tool":
                title += f" / {'Drums' if row['kind'] == 'percussion' else 'Riff'} {song_counts[song_kind]}"
            item = {
                "rank": rank, "phrase_id": pid, "artist": row.get("chart_artist", "").title() or row["artist_from_path"].replace("_", " "),
                "title": title, "song_title": row["title_from_path"].replace("_", " "), "kind": row["kind"],
                "source_path": row["source_path"], "occurrence_count": row["occurrence_count"],
                "period_beats": period["period_beats"], "cycle_seconds": metadata["cycle_seconds"], "bpm": 60000000 / tempo,
                "program": metadata["part"]["program"], "period_method": period["policy"].replace("_", " "),
                "rationale": selection.get("rationale", "Selected by the documented recurrence ranking, then rebuilt from source part notes over a complete cycle."),
                "evidence_statement": statement, "evidence_urls": selection.get("evidence_urls", []),
                "search_limited": bool(row.get("search_limited") or selection.get("bounded_extraction", {}).get("limits", {}).get("window_limit_reached")),
                "curation_truncated": bool(row.get("curation_truncated") or selection.get("bounded_extraction", {}).get("limits", {}).get("candidate_limit_reached")),
                "waveform": _waveform(output / "audio" / pid / "loop.wav"),
            }
            if group == "tool":
                item["rhythm"] = diagrams.get(pid)
                mixed_id = pid + "-with-drums"
                if mixed_id in render_entries:
                    item["with_drums"] = {"phrase_id": mixed_id, "waveform": _waveform(output / "audio" / mixed_id / "loop.wav")}
            groups[group]["rows"].append(item)
    catalog = {"version": "samuged-loop-space-v1", "groups": groups}
    if tool is not None:
        groups["tool"]["counts"] = {
            "songs": len({row["song_title"] for row in groups["tool"]["rows"]}),
            "riffs": sum(row["kind"] == "melodic" for row in groups["tool"]["rows"]),
            "drums": sum(row["kind"] == "percussion" for row in groups["tool"]["rows"]),
            "paired": sum("with_drums" in row for row in groups["tool"]["rows"]),
        }
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2))
    safe = json.dumps(catalog, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_name("loop_player.html").read_text()
    (output / "index.html").write_text(template.replace("__CATALOG__", safe).replace('<strong>40</strong>', f'<strong>{len(render_entries)}</strong>'))
    shutil.copyfile(base / "font/usr/share/doc/fluid-soundfont-gm/copyright", output / "soundfont-license.txt")
    shutil.copytree(Path(__file__).resolve().parents[1] / "docs/assets/inter", output / "fonts")
    (output / "README.md").write_text("""---
title: SaMuGeD Earworms (Ostinato / Catchy musical hooks)
emoji: 🎹
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: cc-by-4.0
---

# SaMuGeD Earworms (Ostinato / Catchy musical hooks)

Recurring melodic phrases and separate drum patterns.

Authors: Peiyi Wu (pewu10205@uit.no), Asle Fjæran Øren (asleoren@gmail.com), Shayan Dadman (shayan.dadman@uit.no) and Almaz Ermilov (almaz.ermilov@uit.no).

Three top 50 collections and ten familiar song selections with continuous Web Audio buffer playback.
The Tool motifs tab is a personal tribute with 27 riffs, 14 drum patterns and 20 aligned riff plus drum versions from nine source songs.
Filter by song or part, compare Riff only with With drums and follow source note attacks in the rhythm diagram.
The combined versions use the same source passage. Their joint recurrence is not independently verified.
Familiar hooks use published song level recognition or earworm occurrence evidence.
The exact fragments have no listener labels. The other collections rank symbolic
recurrence, popular songs from a historical UK sales cohort and drum patterns.

WAV is stereo PCM 24 bit at 48 kHz. Download FLAC or loop MIDI for a DAW.
The interface uses Inter under SIL OFL, included in fonts/OFL.txt.
The authentic FluidR3 GM SoundFont was used with FluidSynth. Its licence is
in soundfont-license.txt. Original commercial recordings are not bundled.

Dataset https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases
Code https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSamplerAI-2024

The Lakh collection states CC BY 4.0. Underlying composition and arrangement
attribution remains incomplete. No independent clearance is claimed.
""")
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = build(args.base, args.output)
    print({key: len(value["rows"]) for key, value in catalog["groups"].items()})
