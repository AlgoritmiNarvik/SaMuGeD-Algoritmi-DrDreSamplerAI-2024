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


def curated_popular(rows: list[dict], featured: dict) -> list[dict]:
    """Keep the source ranking intact and apply a separate listening curation."""
    remaining = [row for row in rows if row["title_from_path"].replace("_", " ").casefold() != "2 become 1"]
    result = [dict(featured), *(dict(row) for row in remaining[:49])]
    for rank, row in enumerate(result, 1):
        row["rank"] = rank
    return result


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


def attach_atlas_audio(atlas: Path, output: Path) -> None:
    """Bind every displayed atlas phrase to a verified source cycle render."""
    from scripts.make_review import script_safe_json
    shutil.copytree(Path(__file__).resolve().parents[1] / "docs/assets/adamas", atlas / "branding", dirs_exist_ok=True)
    packet = _json(atlas / "analysis.json")
    packet["audio"], bindings = {}, {}
    for pid in sorted(packet["snippets"]):
        root = output / "audio" / pid
        metadata = _json(root / "metadata.json")
        row = {"wav": f"../audio/{pid}/loop.flac", "flac": f"../audio/{pid}/loop.flac",
               "midi": f"../audio/{pid}/loop.mid", "cycle_seconds": metadata["cycle_seconds"],
               "period_beats": metadata["period"]["period_beats"], "program": metadata["part"]["program"]}
        piano = output / "audio" / (pid + "-piano")
        if piano.exists():
            row["piano"] = {key: value.replace(f"/{pid}/", f"/{pid}-piano/")
                            for key, value in row.items() if key in ("wav", "flac", "midi")}
        paired = output / "audio" / (pid + "-with-drums")
        if paired.exists():
            paired_metadata = _json(paired / "metadata.json")
            if paired_metadata["cycle_seconds"] != metadata["cycle_seconds"] or paired_metadata["period"] != metadata["period"]:
                raise ValueError("paired atlas cycle differs from the melodic cycle")
            row["with_drums"] = {key: value.replace(f"/{pid}/", f"/{pid}-with-drums/")
                                  for key, value in row.items() if key in ("wav", "flac", "midi")}
        drum_solo = output / "audio" / (pid + "-drums-only")
        if drum_solo.exists():
            row["drums_only"] = {key: value.replace(f"/{pid}/", f"/{pid}-drums-only/")
                                  for key, value in row.items() if key in ("wav", "flac", "midi")}
        row["default_mode"] = "paired" if paired.exists() else "source"
        packet["audio"][pid] = row
        bindings[pid] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in ("metadata.json", "loop.wav", "loop.mid")}
        if paired.exists():
            bindings[pid]["with_drums"] = {name: hashlib.sha256((paired / name).read_bytes()).hexdigest()
                                            for name in ("metadata.json", "loop.wav", "loop.mid")}
    shutil.copyfile(Path(__file__).with_name("loop_downloads.js"), atlas / "loop_downloads.js")
    (atlas / "analysis.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    (atlas / "index.html").write_text(Path(__file__).with_name("top_phrases.html").read_text().replace("__DATA__", script_safe_json(packet)))
    (atlas / "audio_receipt.json").write_text(json.dumps({"version": "samuged-atlas-audio-v1",
        "source_cycles": len(bindings), "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bindings": bindings}, indent=2) + "\n")
    receipt = _json(atlas / "receipt.json")
    receipt["audio_attachment"] = {"source_cycles": len(bindings), "receipt": "audio_receipt.json"}
    receipt["outputs"] = {p.relative_to(atlas).as_posix(): {"bytes": p.stat().st_size,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(atlas.rglob("*")) if p.is_file() and p.name != "receipt.json"}
    (atlas / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def build(base: Path, output: Path, compact_audio: bool = False) -> dict:
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
    for name in ("atlas_audio", "piano_audio", "schism_audio", "source_layers", "external_tool_audio", "external_tool_layers", "drum_solos", "tool_expansion_audio", "tool_expansion_layers", "tool_expansion_solos"):
        if (base / name).exists():
            render_entries.update(_copy_render(base / name, output))
    provenance = output / "rendering"
    provenance.mkdir()
    for name, root in (("recurrence", base / "recurrence_audio"), ("familiar", base / "familiar_audio"), ("tool", tool_root), ("tool_layers", layers), ("atlas", base / "atlas_audio"), ("piano", base / "piano_audio"), ("schism", base / "schism_audio"), ("source_layers", base / "source_layers"), ("external_tool", base / "external_tool_audio"), ("external_tool_layers", base / "external_tool_layers"), ("drum_solos", base / "drum_solos"), ("tool_expansion_audio", base / "tool_expansion_audio"), ("tool_expansion_layers", base / "tool_expansion_layers"), ("tool_expansion_solos", base / "tool_expansion_solos")):
        if name == "tool" and tool is None:
            continue
        if name == "tool_layers" and not layers.exists():
            continue
        if name in ("atlas", "piano", "schism", "source_layers", "external_tool", "external_tool_layers", "drum_solos", "tool_expansion_audio", "tool_expansion_layers", "tool_expansion_solos") and not root.exists():
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
        "familiar": {"title": "Familiar hooks", "description": "Nine songs from the published Hooked on Music recognition list, ordered by song recognition rank, plus Journey from a separate earworm study. These MIDI fragments have no listener validation.", "rows": []},
        "motifs": {"title": "Repeated motifs", "description": "Fifty recurring melodic motifs after a note diversity filter. One artist and title per position. Counts measure repetition within MIDI arrangements, not listener popularity.", "rows": []},
        "popular": {"title": "Popular songs", "description": "", "rows": []},
        "drums": {"title": "Drum patterns", "description": "Fifty recurring percussion patterns. Kit pitches and simultaneous hits are preserved. These rhythm loops have no listener memorability labels.", "rows": []},
    }
    if tool is not None:
        groups["tool"] = {
            "title": "Tool’s ostinatos",
            "description": "A tribute to one of Almaz Ermilov's favourite bands. Tool combines recurring riffs, shifting accents and changing meters. Hear melody and drums together, then explore each layer. MIDI arrangements can simplify the originals.",
            "listening_note": "Listen for shared accents, displaced beats and the return of the loop.",
            "rows": [],
        }
    groups = {key: groups[key] for key in ("popular", "familiar", "motifs", "drums", "tool") if key in groups}
    rows_by_group = {**recurrence["views"], "familiar": familiar["candidates"]}
    if tool is not None:
        rows_by_group["tool"] = tool["candidates"]
    schism = _json(base / "schism/selection.json") if (base / "schism/selection.json").exists() else None
    if schism:
        featured = next(row for row in schism["candidates"] if row["phrase_id"] == schism["featured_id"])
        rows_by_group["popular"] = curated_popular(rows_by_group["popular"], featured)
        rows_by_group["tool"] = [*schism["candidates"], *rows_by_group.get("tool", [])]
        shutil.copyfile(base / "schism/selection.json", provenance / "schism_selection.json")
    if (base / "external_tool/selection.json").exists():
        external = _json(base / "external_tool/selection.json")
        rows_by_group["tool"] = [*rows_by_group["tool"], *external["candidates"]]
        shutil.copyfile(base / "external_tool/selection.json", provenance / "external_tool_selection.json")
    if (base / "tool_expansion/selection.json").exists():
        expansion = _json(base / "tool_expansion/selection.json")
        rows_by_group["tool"] = [*rows_by_group["tool"], *expansion["candidates"]]
        shutil.copyfile(base / "tool_expansion/selection.json", provenance / "tool_expansion_selection.json")
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
            if selection.get("external_source_url"):
                statement = "Personal Tool selection from a separate MIDI arrangement, extracted with the same recurrence algorithm. No listener labels."
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
                "featured": bool(selection.get("featured")),
            }
            if group == "tool":
                item["rhythm"] = diagrams.get(pid)
            mixed_id = pid + "-with-drums"
            if mixed_id in render_entries:
                item["with_drums"] = {"phrase_id": mixed_id, "waveform": _waveform(output / "audio" / mixed_id / "loop.wav")}
            if group == "tool" and not item.get("rhythm"):
                paired_metadata = _json(output / "audio" / mixed_id / "metadata.json") if mixed_id in render_entries else {}
                item["rhythm"] = {"ticks_per_beat": round(period["period_ticks"] / period["period_beats"]), "period_ticks": period["period_ticks"],
                    "source_meter": metadata["meter_changes"][0], "part_name": metadata["part"]["name"],
                    "riff_onsets": [{"tick": n["relative_start_tick"], "pitch": n["pitch"], "velocity": n["velocity"]} for n in metadata["source_notes_used"]],
                    "drum_onsets": [{"tick": n["start_tick"] - metadata["cycle_start_tick"], "pitch": n["pitch"], "velocity": n["velocity"]} for n in (metadata["source_notes_used"] if row["kind"] == "percussion" else paired_metadata.get("drum_notes_used", []))]}
            drum_id = pid + "-drums-only"
            if drum_id in render_entries:
                item["drums_only"] = {"phrase_id": drum_id, "waveform": _waveform(output / "audio" / drum_id / "loop.wav")}
            item["default_layer"] = "paired" if mixed_id in render_entries else "solo"
            if pid + "-piano" in render_entries:
                item["piano"] = {"phrase_id": pid + "-piano", "waveform": _waveform(output / "audio" / (pid + "-piano") / "loop.wav")}
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
    shutil.copyfile(Path(__file__).with_name("loop_downloads.js"), output / "loop_downloads.js")
    shutil.copyfile(base / "font/usr/share/doc/fluid-soundfont-gm/copyright", output / "soundfont-license.txt")
    shutil.copytree(Path(__file__).resolve().parents[1] / "docs/assets/inter", output / "fonts")
    shutil.copytree(Path(__file__).resolve().parents[1] / "docs/assets/adamas", output / "branding")
    if (base / "atlas").exists():
        shutil.copytree(base / "atlas", output / "atlas")
        shutil.rmtree(output / "atlas/fonts")
        shutil.copytree(Path(__file__).resolve().parents[1] / "docs/assets/inter", output / "atlas/fonts")
        if schism:
            packet = _json(output / "atlas/analysis.json")
            supplement = _json(base / "schism/atlas.json")
            packet["views"]["popular"] = curated_popular(packet["views"]["popular"], supplement["featured"])
            pid = supplement["featured"]["phrase_id"]
            packet["snippets"][pid] = supplement["snippets"][pid]
            packet["listening_curation"] = {"featured_id": pid, "excluded_title": "2 Become 1", "selection_receipt": "../rendering/schism_selection.json", "claim": schism["claim"]}
            shutil.copyfile(base / "schism" / next(row["midi_path"] for row in map(json.loads, (base / "schism/phrases.jsonl").read_text().splitlines()) if row["phrase_id"] == pid), output / "atlas/midi" / f"{pid}.mid")
            (output / "atlas/analysis.json").write_text(json.dumps(packet, indent=2) + "\n")
            from scripts.analyze_top_phrases import write_csv
            write_csv(output / "atlas/top50_popular.csv", packet["views"]["popular"])
        attach_atlas_audio(output / "atlas", output)
    (output / "README.md").write_text("""---
title: SaMuGeD Earworms (Ostinato / Catchy musical hooks)
emoji: 🎹
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: other
license_name: mixed-midi-sources
license_link: https://huggingface.co/spaces/AlmazErmilov/samuged-earworms/blob/main/README.md
---

# SaMuGeD Earworms (Ostinato / Catchy musical hooks)

Recurring melodic phrases and separate drum patterns.

Authors: Peiyi Wu (pewu10205@uit.no), Asle Fjæran Øren (asleoren@gmail.com), Shayan Dadman (shayan.dadman@uit.no) and Almaz Ermilov (almaz.ermilov@uit.no).

Three top 50 collections and ten familiar song selections with continuous Web Audio buffer playback.
The Tool ostinatos tab is a personal tribute with 27 riffs, 14 drum patterns and 20 aligned riff plus drum versions from nine source songs.
Filter by song or part, compare Riff only with With drums and follow source note attacks in the rhythm diagram.
The combined versions use the same source passage. Their joint recurrence is not independently verified.
Familiar hooks use published song level recognition or earworm occurrence evidence.
The exact fragments have no listener labels. The other collections rank symbolic
recurrence, a curated popular song collection and drum patterns. The original historical sales cohort is documented in the repository.

WAV is stereo PCM 24 bit at 48 kHz. Download FLAC or loop MIDI for a DAW.
The interface uses Inter under SIL OFL, included in fonts/OFL.txt.
The Adamas wordmark is by Colorblind. The font file is not distributed. See branding/NOTICE.txt.
Both players start at 50 percent volume and provide a volume slider.
The authentic FluidR3 GM SoundFont was used with FluidSynth. Its licence is
in soundfont-license.txt. Original commercial recordings are not bundled.

Dataset https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases
Code https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSamplerAI-2024

The Lakh collection states CC BY 4.0. Underlying composition and arrangement
attribution remains incomplete. No independent clearance is claimed.
""")
    card = output / "README.md"
    text = card.read_text()
    if tool:
        counts = groups["tool"]["counts"]
        text = text.replace("27 riffs, 14 drum patterns and 20 aligned riff plus drum versions from nine source songs", f"{counts['riffs']} riffs, {counts['drums']} drum patterns and {counts['paired']} aligned riff plus drum versions from {counts['songs']} source songs")
    text = text.replace("compare Riff only with With drums", "compare Melody only with With drums")
    text += "\nAll atlas phrases use the same SoundFont audio as the main player. Source drums are selected by default where the source passage has a usable drum layer. Melody only remains available.\n"
    if schism:
        text += "\nSchism is the first Popular songs selection and a separate Tool listening supplement. Its featured position is editorial. 2 Become 1 is excluded from this listening collection. The frozen corpus and original CSV rankings are unchanged. The external Tool arrangements have no explicit redistribution license on their source pages. They are interface supplements outside the Lakh attribution claim and are not added to the dataset. See rendering/schism_selection.json, rendering/external_tool_selection.json and rendering/tool_expansion_selection.json when present for source and extraction receipts.\n"
    text += "\nPlayback uses lossless FLAC. The WAV button decodes it at 48 kHz and exports stereo PCM 24 bit in the browser. Playback volume does not change downloads. This avoids storing two copies of the same audio in the Space. Original render hashes remain in the rendering receipts.\n"
    card.write_text(text)
    if compact_audio:
        for path in (output / "audio").glob("*/loop.wav"):
            path.unlink()
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compact-audio", action="store_true", help="serve lossless FLAC and generate WAV downloads in the browser")
    args = parser.parse_args()
    catalog = build(args.base, args.output, compact_audio=args.compact_audio)
    print({key: len(value["rows"]) for key, value in catalog["groups"].items()})
