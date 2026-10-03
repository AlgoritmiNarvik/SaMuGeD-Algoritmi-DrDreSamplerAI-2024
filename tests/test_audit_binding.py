from __future__ import annotations

import importlib
import json
from pathlib import Path

import mido
import pytest

from samuged.dataset import atomic_json, build, file_digest
from samuged.phrases import Config


@pytest.fixture
def auditable_dataset(tmp_path: Path) -> tuple[Path, Path]:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    pitches = (60, 62, 65, 64, 67, 69, 65, 62)
    for repetition in range(2):
        for index, pitch in enumerate(pitches):
            track.append(
                mido.Message(
                    "note_on",
                    note=pitch,
                    velocity=80,
                    time=1920 if repetition and index == 0 else 0,
                )
            )
            track.append(mido.Message("note_off", note=pitch, time=240))
    midi.save(source / "song.mid")
    build(
        source,
        output,
        Config(lengths=(8,), mode="exact"),
        workers=1,
        export=False,
    )
    return source, output


def test_audit_rejects_input_mutation_during_source_verification(
    auditable_dataset: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = auditable_dataset
    audit_module = importlib.import_module("samuged.audit")
    original_load_midi = audit_module.load_midi
    summary_path = output / "summary.json"
    initial_summary_hash = file_digest(summary_path)
    mutated = False

    def load_and_mutate_summary(path: Path, **kwargs):
        nonlocal mutated
        song = original_load_midi(path, **kwargs)
        if not mutated:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["concurrent_mutation_probe"] = True
            atomic_json(summary_path, summary)
            mutated = True
        return song

    monkeypatch.setattr(audit_module, "load_midi", load_and_mutate_summary)

    result = audit_module.audit(source, output, require_full=True)

    assert mutated
    assert not result["passed"]
    assert result["summary_sha256"] == initial_summary_hash
    assert result["summary_sha256"] != file_digest(summary_path)
    assert {
        "where": "summary.json",
        "reason": "audit input changed while audit was running",
    } in result["failures"]
