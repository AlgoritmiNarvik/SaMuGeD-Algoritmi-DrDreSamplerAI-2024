from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import mido
import pytest

from samuged.evaluate_themes import (
    ANNOTATORS,
    SONG_IDS,
    ThemeCase,
    _archive_case,
    agreement,
    bootstrap_song_macro,
    classification_metrics,
    prediction_indices,
    run,
)
from samuged.experiment import verify_completed_experiment
from samuged.midi import MidiSong, Note, Part


def _midi_bytes(negative, positive, *, tempo=500_000, shifted_pitch=None):
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    metadata = mido.MidiTrack()
    metadata.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    metadata.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    midi.tracks.append(metadata)
    for track_name, rows, program in (("melody", negative, 40), ("Theme Regions", positive, 73)):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=track_name, time=0))
        track.append(mido.Message("program_change", program=program, channel=5, time=0))
        events = []
        for start, end, pitch, velocity in rows:
            pitch = shifted_pitch if shifted_pitch is not None and pitch == 60 else pitch
            events.extend(((start, 1, pitch, velocity), (end, 0, pitch, 0)))
        prior = 0
        for tick, on, pitch, velocity in sorted(events, key=lambda row: (row[0], row[1])):
            track.append(mido.Message(
                "note_on" if on else "note_off", note=pitch, velocity=velocity,
                channel=5, time=tick-prior,
            ))
            prior = tick
        midi.tracks.append(track)
    stream = BytesIO()
    midi.save(file=stream)
    return stream.getvalue()


def _archive_fixture(tmp_path, *, mismatch=False):
    song_id = "065"
    universe = [
        (0, 120, 60, 80), (240, 360, 62, 81),
        (480, 600, 64, 82), (720, 840, 65, 83),
    ]
    partitions = (
        (universe[:2], universe[2:]),
        (universe[::2], universe[1::2]),
        (universe[1:3], (universe[0], universe[3])),
    )
    members = {}
    for annotator, (negative, positive) in enumerate(partitions):
        data = _midi_bytes(
            negative, positive, tempo=500_000 + annotator,
            shifted_pitch=61 if mismatch and annotator == 2 else None,
        )
        members[f"{song_id}/{song_id}_Annotator_{annotator}.mid"] = data
    for index, suffix in enumerate(("Cl", "Cl_wo_NoteDur", "Cl_wo_PthSft", "Cm", "Cosiatec")):
        changed = [(start + 10 + index, end + 10 + index, pitch, velocity)
                   for start, end, pitch, velocity in universe]
        members[f"{song_id}/{song_id}_{suffix}.mid"] = _midi_bytes(changed[:2], changed[2:])
    archive_path = tmp_path / f"{song_id}.zip"
    with ZipFile(archive_path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    archive_data = archive_path.read_bytes()
    audit_song = {
        "archive_sha256": sha256(archive_data).hexdigest(),
        "midi_members": [
            {"name": name, "sha256": sha256(data).hexdigest()}
            for name, data in members.items()
        ],
    }
    receipt = {
        "sha256": sha256(archive_data).hexdigest(),
        "bytes": len(archive_data),
        "url": "https://example.invalid/065.zip",
    }
    return song_id, audit_song, receipt


def test_archive_adapter_strips_annotation_identity_and_keeps_exact_labels(tmp_path):
    song_id, audit_song, receipt = _archive_fixture(tmp_path)

    case = _archive_case(tmp_path, song_id, audit_song, receipt)

    assert len(case.song.parts) == 1
    part = case.song.parts[0]
    assert (part.index, part.track, part.channel, part.program, part.name, part.is_drum) == (
        0, 0, 0, 0, "canonical_melody", False,
    )
    assert len(part.notes) == 4
    assert case.labels == {"0": {2, 3}, "1": {1, 3}, "2": {0, 3}}
    assert case.metadata["meters_equal"] is True
    assert case.metadata["tempos_equal"] is False
    assert all(not row["exact_universe_match"] for row in case.baseline_input_coverage)


def test_archive_adapter_fails_closed_on_annotation_universe_mismatch(tmp_path):
    song_id, audit_song, receipt = _archive_fixture(tmp_path, mismatch=True)

    with pytest.raises(ValueError, match="note universe mismatch"):
        _archive_case(tmp_path, song_id, audit_song, receipt)


def test_prediction_join_uses_skyline_source_indices_and_verified_bounds():
    notes = [
        Note(0, 120, 60, 80),
        Note(0, 180, 72, 90),
        Note(240, 360, 74, 90),
        Note(480, 600, 76, 90),
    ]
    song = MidiSong(480, [Part(0, 0, 0, 0, "canonical_melody", False, notes)],
                    [(0, 500_000)], [(0, 4, 4)], [])
    phrases = [{
        "part_index": 0,
        "note_count": 2,
        "occurrences": [{
            "note_index": 0, "note_count": 2, "start_tick": 0, "end_tick": 360,
            "source_verified": True,
        }],
    }]

    assert prediction_indices(
        song, phrases, top_n=1, onset_merge_beats=1/24, require_source_verified=True
    ) == {1, 2}
    phrases[0]["occurrences"][0]["source_verified"] = False
    with pytest.raises(ValueError, match="not source verified"):
        prediction_indices(
            song, phrases, top_n=1, onset_merge_beats=1/24, require_source_verified=True
        )
    phrases[0]["occurrences"][0].update(source_verified=True, end_tick=361)
    with pytest.raises(ValueError, match="end does not match"):
        prediction_indices(
            song, phrases, top_n=1, onset_merge_beats=1/24, require_source_verified=True
        )


def test_metric_boundaries_and_pairwise_agreement():
    assert classification_metrics(set(), set())["f1"] == 1
    empty_prediction = classification_metrics({1}, set())
    assert empty_prediction["precision"] == empty_prediction["recall"] == 0
    false_positive = classification_metrics(set(), {1})
    assert false_positive["precision"] == false_positive["f1"] == 0
    assert false_positive["recall"] == 0
    assert classification_metrics({1, 2}, {2, 3}) == {
        "true_positive": 1, "false_positive": 1, "false_negative": 1,
        "precision": 0.5, "recall": 0.5, "f1": 0.5,
    }
    assert agreement(set(), set(), 4) == {"raw_agreement": 1, "cohen_kappa": None}
    opposed = agreement({0, 1}, {2, 3}, 4)
    assert opposed["raw_agreement"] == 0
    assert opposed["cohen_kappa"] == -1


def test_song_cluster_bootstrap_is_deterministic_and_retains_song_estimate():
    rows = {
        "a": {"precision": 0.0, "recall": 0.5, "f1": 0.25},
        "b": {"precision": 1.0, "recall": 0.5, "f1": 0.75},
    }
    first = bootstrap_song_macro(rows, samples=200, seed=17)
    second = bootstrap_song_macro(rows, samples=200, seed=17)
    assert first == second
    assert first["precision"]["estimate"] == 0.5
    assert first["recall"]["ci95_low"] == first["recall"]["ci95_high"] == 0.5


def test_run_writes_a_completed_receipt_without_mutating_start_receipt(tmp_path, monkeypatch):
    notes = [Note(i * 120, i * 120 + 60, 60 + i % 4, 80) for i in range(8)]
    song = MidiSong(480, [Part(0, 0, 0, 0, "canonical_melody", False, notes)],
                    [(0, 500_000)], [(0, 4, 4)], [])
    cases = []
    for song_id in SONG_IDS:
        cases.append(ThemeCase(
            song_id, song, {str(a): {0, 1, 4, 5} for a in ANNOTATORS},
            "a" * 64, {}, "b" * 64, {str(a): "c" * 64 for a in ANNOTATORS},
            {"meters_equal": True, "tempos_equal": True}, [], "https://example.invalid",
        ))
    monkeypatch.setattr(
        "samuged.evaluate_themes.load_cases",
        lambda *_: (cases, {
            "input_audit_sha256": "d" * 64,
            "official_source_comparison": {"all_official_melody_unions_exact_match_canonical": False},
        }),
    )

    def fake_detect(method, source, config):
        verified = method == "aligned_indexed"
        return {
            "phrases": [{
                "part_index": 0, "note_count": 2,
                "occurrences": [
                    {"note_index": 0, "note_count": 2, "start_tick": 0, "end_tick": 180,
                     **({"source_verified": True} if verified else {})},
                    {"note_index": 4, "note_count": 2, "start_tick": 480, "end_tick": 660,
                     **({"source_verified": True} if verified else {})},
                ],
            }],
            "search_limited": False, "curation_truncated": False,
            "candidate_count": 1, "part_stats": [],
        }

    monkeypatch.setattr("samuged.evaluate_themes._detect", fake_detect)
    output = tmp_path / "result"
    result = run(tmp_path, tmp_path / "audit.json", output)

    assert result["song_count"] == 6
    assert json.loads((output / "experiment_receipt.json").read_text())["status"] == "started"
    completion = verify_completed_experiment(output)
    assert completion["status"] == "completed"
    assert set(completion["artifacts"]) == {"aggregate.json", "raw_results.json"}
