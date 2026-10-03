import json
import subprocess
import sys

import mido
import pytest

from samuged.aligned import AlignedConfig
from samuged.audit import audit
from samuged.closed_patterns import extract_closed_patterns
from samuged.dataset import build, file_digest
from samuged.evaluate import _build_case, _write_case
from samuged.midi import MidiSong, Note, Part, load_midi
from samuged.part_ranking import (
    MELODY_PRIOR_CONFIG,
    PART_PRIOR_VERSION,
    extract_part_ranked,
    select_part_ranked_closed_candidates,
)
from samuged.phrases import Config
from scripts.validate_schema import validate_dataset


def _source(tmp_path, *, drums=False):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "phrase.mid"
    case = _build_case("legacy_contiguous_exact", "regression", 0, 30_000_000)
    _write_case(case, path)
    if drums:
        midi = mido.MidiFile(path)
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name="drums", time=0))
        for _ in range(64):
            track.append(mido.Message("note_on", channel=9, note=36, velocity=90, time=0))
            track.append(mido.Message("note_off", channel=9, note=36, velocity=0, time=120))
            track.append(mido.Message("note_on", channel=9, note=42, velocity=75, time=120))
            track.append(mido.Message("note_off", channel=9, note=42, velocity=0, time=120))
            track.append(mido.Message("note_on", channel=9, note=38, velocity=85, time=120))
            track.append(mido.Message("note_off", channel=9, note=38, velocity=0, time=120))
        midi.tracks.append(track)
        midi.save(path)
    return source, path


def _refresh_source_binding(output):
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["source_manifest_sha256"] = file_digest(output / "sources.jsonl")
    summary_path.write_text(json.dumps(summary))


def _candidate(family, part_index, score, start):
    return {
        "family_id": family,
        "part_index": part_index,
        "note_count": 8,
        "start_tick": start,
        "end_tick": start + 960,
        "recurrence_score": score,
        "score_components": {"boundary": 0.5},
        "occurrence_count": 2,
        "occurrences": [
            {"start_tick": start, "end_tick": start + 960},
            {"start_tick": start + 1920, "end_tick": start + 2880},
        ],
    }


def test_single_part_fixed_prior_preserves_closed_selection(tmp_path):
    _, path = _source(tmp_path)
    song = load_midi(path)
    closed = extract_closed_patterns(song, AlignedConfig(), algorithm="aligned_indexed")
    melody = extract_part_ranked(song, AlignedConfig())
    assert melody["phrases"] == closed["phrases"]
    assert melody["algorithm"] == "aligned_melody"
    assert melody["selection"] == PART_PRIOR_VERSION


def test_full_detector_is_invariant_to_part_metadata_after_partitioning(tmp_path):
    _, path = _source(tmp_path)
    song = load_midi(path)
    remapped = MidiSong(
        song.ticks_per_beat,
        [
            Part(
                part.index,
                part.track + 1000,
                (part.channel + 7) % 16,
                (part.program + 73) % 128,
                f"masked-{part.index}",
                part.is_drum,
                list(part.notes),
            )
            for part in song.parts
        ],
        list(song.tempos),
        list(song.meters),
        list(song.warnings),
        list(song.metadata_repairs),
    )

    def without_copied_metadata(result):
        return {
            **result,
            "phrases": [
                {
                    key: value
                    for key, value in phrase.items()
                    if key not in {"source_track", "channel", "program", "part_name"}
                }
                for phrase in result["phrases"]
            ],
        }

    assert without_copied_metadata(extract_part_ranked(song, AlignedConfig())) == (
        without_copied_metadata(extract_part_ranked(remapped, AlignedConfig()))
    )


def test_fixed_melody_prior_can_override_close_accompaniment_score():
    melody_notes = [Note(i * 240, i * 240 + 180, pitch, 90)
                    for i, pitch in enumerate([60, 62, 64, 65, 67, 69, 71, 72])]
    chord_notes = [
        Note(i * 240, i * 240 + 420, pitch, 80)
        for i in range(8)
        for pitch in (48, 52, 55)
    ]
    song = MidiSong(
        480,
        [Part(0, 1, 0, 0, "ignored", False, melody_notes),
         Part(1, 2, 4, 88, "ignored", False, chord_notes)],
        [(0, 500_000)], [(0, 4, 4)], [],
    )
    candidates = [
        _candidate("a" * 64, 1, 0.91, 0),
        _candidate("b" * 64, 0, 0.89, 5000),
    ]
    selected, evidence = select_part_ranked_closed_candidates(
        candidates, song, MELODY_PRIOR_CONFIG, top_k=1
    )
    assert selected[0]["family_id"] == "b" * 64
    assert selected[0]["recurrence_score"] == 0.89
    assert evidence["selected"][0]["adjusted_score"] > 0.91


def test_aligned_melody_schema_and_reextract_audit(tmp_path):
    source, _ = _source(tmp_path)
    output = tmp_path / "dataset"
    build(source, output, AlignedConfig(), workers=1, algorithm="aligned_melody")
    schema = validate_dataset(output)
    assert schema["invalid_rows"] == 0, schema
    checked = audit(source, output, require_full=True, reextract=True)
    assert checked["passed"], checked["failures"]


@pytest.mark.parametrize("tamper", ["feature", "selection"])
def test_aligned_melody_audit_rejects_ranking_tampering(tmp_path, tamper):
    source, _ = _source(tmp_path)
    output = tmp_path / "dataset"
    build(source, output, AlignedConfig(), workers=1, algorithm="aligned_melody")
    row = json.loads((output / "sources.jsonl").read_text())
    if tamper == "feature":
        key = next(iter(row["part_ranking"]["part_features"]))
        row["part_ranking"]["part_features"][key]["onset_monophony"] = 0.0
    else:
        row["part_ranking"]["selected"][0]["adjusted_score"] = 0.0
    (output / "sources.jsonl").write_text(json.dumps(row) + "\n")
    _refresh_source_binding(output)
    checked = audit(source, output, require_full=True)
    assert not checked["passed"]
    expected = "part features differ" if tamper == "feature" else "adjusted score differs"
    assert any(expected in item["reason"] for item in checked["failures"])


def test_reextract_audit_rejects_candidate_order_digest_tampering(tmp_path):
    source, _ = _source(tmp_path)
    output = tmp_path / "dataset"
    build(source, output, AlignedConfig(), workers=1, algorithm="aligned_melody")
    row = json.loads((output / "sources.jsonl").read_text())
    row["part_ranking"]["candidate_order_sha256"] = "0" * 64
    (output / "sources.jsonl").write_text(json.dumps(row) + "\n")
    _refresh_source_binding(output)
    checked = audit(source, output, require_full=True, reextract=True)
    assert not checked["passed"]
    assert any(
        item["reason"] == "re-extracted part_ranking differs"
        for item in checked["failures"]
    )


def test_percussion_payload_is_unchanged_by_part_ranking(tmp_path):
    source, _ = _source(tmp_path, drums=True)
    closed_output = tmp_path / "closed"
    melody_output = tmp_path / "melody"
    build(source, closed_output, AlignedConfig(), workers=1,
          algorithm="aligned_closed", percussion=True, export=False)
    build(source, melody_output, AlignedConfig(), workers=1,
          algorithm="aligned_melody", percussion=True, export=False)
    closed = json.loads((closed_output / "sources.jsonl").read_text())
    melody = json.loads((melody_output / "sources.jsonl").read_text())
    assert melody["drum_stats"] == closed["drum_stats"]
    def payload(row):
        return [
            {key: value for key, value in phrase.items()
             if key not in {"phrase_id", "rank_in_file"}}
            for phrase in row["phrases"] if phrase["kind"] == "percussion"
        ]
    assert payload(melody) == payload(closed)


def test_reference_remains_the_build_default(tmp_path):
    source, _ = _source(tmp_path)
    output = tmp_path / "reference"
    build(source, output, Config(), workers=1, export=False)
    config = json.loads((output / "build_config.json").read_text())
    assert config["algorithm"] == "reference"


def test_aligned_melody_is_an_explicit_cli_option(tmp_path):
    source, _ = _source(tmp_path)
    output = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable, "-m", "samuged.cli", "build",
            "--source", str(source), "--output", str(output),
            "--algorithm", "aligned_melody", "--workers", "1", "--no-midi",
            "--seed-bucket-limit", "768",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads((output / "build_config.json").read_text())
    assert config["algorithm"] == "aligned_melody"
    assert config["config"]["max_bucket"] == 768


@pytest.mark.parametrize("algorithm,limit", [("reference", "768"), ("aligned_melody", "0"), ("aligned_indexed", "2049")])
def test_cli_rejects_unsupported_seed_limits_before_creating_output(tmp_path, algorithm, limit):
    output = tmp_path / "invalid"
    result = subprocess.run(
        [sys.executable, "-m", "samuged.cli", "build", "--source", str(tmp_path / "missing"),
         "--output", str(output), "--algorithm", algorithm, "--seed-bucket-limit", limit],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "--seed-bucket-limit" in result.stderr
    assert not output.exists()


def test_build_silences_optional_git_probe_errors(tmp_path, monkeypatch):
    import samuged.dataset as dataset_module

    source, _ = _source(tmp_path)
    calls = []

    def unavailable(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(dataset_module.subprocess, "check_output", unavailable)
    output = tmp_path / "outside-git"
    build(source, output, Config(), workers=1, export=False)
    assert calls
    assert calls[0][1]["stderr"] is subprocess.DEVNULL
    assert json.loads((output / "build_config.json").read_text())["git_head"] is None


def test_build_does_not_resume_across_runtime_version_change(tmp_path, monkeypatch):
    import samuged.dataset as dataset_module

    source, _ = _source(tmp_path)
    output = tmp_path / "runtime-bound"
    first = {
        "python_implementation": "CPython",
        "python_version": "3.12.1",
        "mido_version": "1.3.3",
    }
    monkeypatch.setattr(dataset_module, "runtime_metadata", lambda: first)
    build(source, output, Config(), workers=1, export=False)
    saved = json.loads((output / "build_config.json").read_text())
    assert saved["runtime"] == first
    second = {**first, "mido_version": "1.3.4"}
    monkeypatch.setattr(dataset_module, "runtime_metadata", lambda: second)
    with pytest.raises(ValueError, match="another code/config fingerprint"):
        build(source, output, Config(), workers=1, export=False)


def test_audit_rejects_a_different_numeric_runtime(tmp_path, monkeypatch):
    import samuged.audit as audit_module

    source, _ = _source(tmp_path)
    output = tmp_path / "runtime-audit"
    build(source, output, Config(), workers=1, export=False)
    recorded = json.loads((output / "build_config.json").read_text())["runtime"]
    monkeypatch.setattr(
        audit_module,
        "runtime_metadata",
        lambda: {**recorded, "mido_version": recorded["mido_version"] + ".different"},
    )
    checked = audit_module.audit(source, output, require_full=True)
    assert not checked["passed"]
    assert any(
        item["reason"] == "runtime fingerprint differs from current environment"
        for item in checked["failures"]
    )
