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
            raise ValueError("duplicate rendered phrase")
        shutil.copytree(root / entry["phrase_id"], target)
    return {r["phrase_id"]: r for r in manifest["entries"]}


def build(base: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    recurrence = _json(base / "recurrence_selection.json")
    familiar = _json(base / "familiar" / "selection.json")
    familiar_rows = {r["phrase_id"]: r for r in map(json.loads, (base / "familiar" / "phrases.jsonl").read_text().splitlines())}
    render_entries = _copy_render(base / "recurrence_audio", output)
    render_entries.update(_copy_render(base / "familiar_audio", output))
    groups = {
        "familiar": {"title": "Familiar hooks", "description": "Nine songs from the published Hooked on Music recognition list and one frequently reported earworm song. Order follows published song recognition rank within the available songs, Journey is a separate evidence class. Exact MIDI fragments have no listener validation.", "rows": []},
        "motifs": {"title": "Repeated motifs", "description": "The ten most repeated saved melodic motifs after a structural note diversity filter. One normalized artist and title per position. Frequencies are within MIDI arrangements, not listener popularity.", "rows": []},
        "popular": {"title": "Popular songs", "description": "Ten motifs from exactly matched UK million selling singles. Order follows MIDI recurrence, not sales rank. Source arrangements can differ from the original songs.", "rows": []},
        "drums": {"title": "Drum patterns", "description": "The ten most repeated saved percussion patterns. Kit pitches and simultaneous hits are preserved. These are rhythm loops, not claims about memorable melodies.", "rows": []},
    }
    rows_by_group = {**recurrence["views"], "familiar": familiar["candidates"]}
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
            groups[group]["rows"].append({
                "rank": rank, "phrase_id": pid, "artist": row.get("chart_artist", "").title() or row["artist_from_path"], "title": row["title_from_path"],
                "source_path": row["source_path"], "occurrence_count": row["occurrence_count"],
                "period_beats": period["period_beats"], "cycle_seconds": metadata["cycle_seconds"], "bpm": 60000000 / tempo,
                "program": metadata["part"]["program"], "period_method": period["policy"].replace("_", " "),
                "rationale": selection.get("rationale", "Selected by the documented recurrence ranking, then rebuilt from source part notes over a complete cycle."),
                "evidence_statement": statement, "evidence_urls": selection.get("evidence_urls", []),
                "search_limited": bool(row.get("search_limited") or selection.get("bounded_extraction", {}).get("limits", {}).get("window_limit_reached")),
                "curation_truncated": bool(row.get("curation_truncated") or selection.get("bounded_extraction", {}).get("limits", {}).get("candidate_limit_reached")),
                "waveform": _waveform(output / "audio" / pid / "loop.wav"),
            })
    catalog = {"version": "samuged-loop-space-v1", "groups": groups}
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2))
    safe = json.dumps(catalog, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_name("loop_player.html").read_text()
    (output / "index.html").write_text(template.replace("__CATALOG__", safe).replace('<strong>40</strong>', f'<strong>{len(render_entries)}</strong>'))
    shutil.copyfile(base / "font/usr/share/doc/fluid-soundfont-gm/copyright", output / "soundfont-license.txt")
    (output / "README.md").write_text("""---
title: SaMuGeD earworm loops
emoji: 🎹
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: cc-by-4.0
---

# SaMuGeD loop library

Four collections of ten source derived loops with continuous Web Audio buffer playback.
Familiar hooks use published song level recognition or earworm occurrence evidence.
The exact fragments have no listener labels. The other collections rank symbolic
recurrence, popular songs from a historical UK sales cohort and drum patterns.

WAV is stereo PCM 24 bit at 48 kHz. Download FLAC or loop MIDI for a DAW.
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
