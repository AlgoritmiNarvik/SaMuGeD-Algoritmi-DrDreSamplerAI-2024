from __future__ import annotations

from pathlib import Path
import json

import mido

from samuged.audit import audit
from samuged.dataset import build, file_digest
from samuged.phrases import Config
from scripts.make_review import build_packet
from scripts.package_dataset import package
from scripts.screen_splits import screen
from scripts.summarize_dataset import summarize


SEPARATORS = "\u0085\u2028\u2029"


def _write_repeated_song(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    # SMF metadata commonly uses Latin-1. U+0085 is also a legal track-name
    # byte and caused the observed full-corpus reader failure.
    track.append(mido.MetaMessage("track_name", name="Lead\u0085part"))
    pitches = (60, 62, 65, 64, 67, 65, 62, 60, 64, 65, 69, 67)
    for repetition in range(3):
        for index, pitch in enumerate(pitches):
            delay = 24 + (2_880 if repetition and index == 0 else 0)
            track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=delay))
            track.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=216))
    midi.save(path)


def test_unicode_line_separators_survive_real_build_audit_and_consumers(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "dataset"
    relative = f"Artist/Song{SEPARATORS}.mid"
    _write_repeated_song(source / relative)

    build(source, output, Config(lengths=(12,), mode="exact"), workers=1,
          percussion=False, export=True)
    # The source path itself carries U+0085, U+2028 and U+2029 through both
    # JSONL manifests. This is a real extraction, not a parser-only fixture.
    source_rows = [json.loads(line) for line in (output / "sources.jsonl").read_text().split("\n") if line.strip()]
    phrase_rows = [json.loads(line) for line in (output / "phrases.jsonl").read_text().split("\n") if line.strip()]
    assert source_rows[0]["source_path"] == relative
    assert phrase_rows and phrase_rows[0]["source_path"] == relative
    assert "\u0085" in (output / "phrases.jsonl").read_text()

    result = audit(source, output, require_full=True)
    assert result["passed"], result["failures"]
    assert result["source_files"] == 1

    summary = summarize(output)
    assert summary["source_files"] == 1
    assert summary["parsed_files"] == 1

    review = build_packet(source, output, tmp_path / "review.html", count=1)
    assert review["config"]["selected_count"] == 1

    release = package(output, tmp_path / "release", allow_pilot=True)
    assert release["source_files"] == 1

    report = {
        "manifest_sha256": file_digest(output / "sources.jsonl"),
        "method_key": "unicode-test-v1",
        "fingerprint_method_key_counts": {"unicode-test-v1": 1},
        "generation": {
            "pair_generation_limit_reached": False,
            "pair_verification_limit_reached": False,
            "candidate_report_limit_reached": False,
        },
        "candidates": [],
    }
    duplicate_report = tmp_path / "duplicate_report.json"
    duplicate_report.write_text(json.dumps(report) + "\n", encoding="utf-8")
    screening = screen(output, duplicate_report, tmp_path / "screening")
    assert screening["candidate_edges"] == 0
    assert screening["source_split_counts"]
