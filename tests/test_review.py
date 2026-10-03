from hashlib import sha256
import json
from pathlib import Path
import re

import mido
import pytest

import scripts.make_review as review_module
from scripts.make_review import build_packet, sample_rows, _snippet
from samuged.midi import MidiSong, Note
from samuged.midi import load_midi as strict_load_midi


def _write_midi(
    path: Path, *, drum: bool = False, third_occurrence: bool = False,
    variable_occurrence: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    channel = 9 if drum else 0
    events = []
    second = (36, 42, 38, 42) if drum else (65, 67, 69, 70)
    if variable_occurrence and not drum:
        second = (*second, 72)
    patterns = (
        (0, (36, 42, 38, 42) if drum else (60, 62, 64, 65)),
        (960, second),
    )
    if third_occurrence:
        patterns += ((1920, (36, 42, 38, 42) if drum else (67, 69, 71, 72)),)
    for origin, pitches in patterns:
        for index, pitch in enumerate(pitches):
            start = origin + index * 120
            events.append((start, 1, mido.Message("note_on", channel=channel, note=pitch, velocity=90)))
            events.append((start + 60, 0, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))
    previous = 0
    for tick, _order, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = tick - previous
        track.append(message)
        previous = tick
    midi.save(path)


def _manifests(
    dataset: Path,
    source_path: str,
    source_hash: str,
    *,
    kind: str = "melodic",
    phrase_id: str = "phrase-1",
    source_id: str = "source-1",
) -> dict:
    dataset.mkdir(parents=True, exist_ok=True)
    source = {
        "source_id": source_id,
        "source_path": source_path,
        "source_sha256": source_hash,
        "status": "ok",
    }
    phrase = {
        "source_id": source_id,
        "source_path": source_path,
        "source_sha256": source_hash,
        "phrase_id": phrase_id,
        "kind": kind,
        "part_index": -1 if kind == "percussion" else 0,
        "start_tick": 0,
        "end_tick": 420,
        "recurrence_score": 0.8125,
        "note_count": 4,
        "prototype_note_index": 0,
        "occurrences": [
            {"start_tick": 0, "end_tick": 420, "note_index": 0},
            {"start_tick": 960, "end_tick": 1380, "note_index": 4},
        ],
        # Deliberately unrelated. The review packet must read source MIDI notes.
        "pitches": [1, 2, 3, 4],
    }
    (dataset / "sources.jsonl").write_text(json.dumps(source) + "\n", encoding="utf-8")
    (dataset / "phrases.jsonl").write_text(json.dumps(phrase) + "\n", encoding="utf-8")
    return phrase


def _embedded_packet(text: str) -> dict:
    match = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>',
        text,
        flags=re.DOTALL,
    )
    assert match
    return json.loads(match.group(1))


def test_hash_sample_is_deterministic_stratified_and_one_per_source() -> None:
    rows = []
    for kind in ("melodic", "percussion"):
        for index in range(5):
            rows.append(
                {
                    "kind": kind,
                    "source_id": f"{kind}-{index}",
                    "phrase_id": f"{kind}-phrase-{index}",
                    "split_group": f"group-{kind}-{index}",
                    "family_id": f"family-{kind}-{index}",
                }
            )
    rows.extend(
        [
            {"kind": "melodic", "source_id": "shared", "phrase_id": "shared-m"},
            {"kind": "percussion", "source_id": "shared", "phrase_id": "shared-p"},
        ]
    )

    first = sample_rows(rows, 8, "fixed-seed")
    second = sample_rows(reversed(rows), 8, "fixed-seed")

    assert [row["phrase_id"] for row in first] == [row["phrase_id"] for row in second]
    assert {row["kind"] for row in first} == {"melodic", "percussion"}
    assert sum(row["kind"] == "melodic" for row in first) == 4
    assert len({row["source_id"] for row in first}) == len(first)


def test_sample_separates_source_split_group_and_canonical_family() -> None:
    rows = []
    for kind in ("melodic", "percussion"):
        for index in range(6):
            rows.append(
                {
                    "kind": kind,
                    "source_id": f"{kind}-source-{index}",
                    "split_group": f"{kind}-group-{index}",
                    "family_id": f"{kind}-family-{index}",
                    "phrase_id": f"{kind}-phrase-{index}",
                }
            )
    rows.extend(
        [
            {
                "kind": "melodic",
                "source_id": "family-a",
                "split_group": "family-group-a",
                "family_id": "shared-family",
                "phrase_id": "family-a-phrase",
            },
            {
                "kind": "percussion",
                "source_id": "family-b",
                "split_group": "family-group-b",
                "family_id": "shared-family",
                "phrase_id": "family-b-phrase",
            },
            {
                "kind": "melodic",
                "source_id": "group-a",
                "split_group": "shared-group",
                "family_id": "group-family-a",
                "phrase_id": "group-a-phrase",
            },
            {
                "kind": "percussion",
                "source_id": "group-b",
                "split_group": "shared-group",
                "family_id": "group-family-b",
                "phrase_id": "group-b-phrase",
            },
        ]
    )

    selected = sample_rows(rows, 10, "constraint-seed")

    assert len(selected) == 10
    for field in ("source_id", "split_group", "family_id"):
        assert len({row.get(field, row["source_id"]) for row in selected}) == len(selected)
    assert {row["kind"] for row in selected} == {"melodic", "percussion"}


def test_packet_uses_actual_source_excerpts_and_escapes_script_data(tmp_path) -> None:
    source = tmp_path / "corpus"
    malicious_relative = "evil</script><img src=x onerror=alert(1)>.mid"
    midi_path = source / malicious_relative
    _write_midi(midi_path)
    source_hash = sha256(midi_path.read_bytes()).hexdigest()
    dataset = tmp_path / "dataset"
    _manifests(dataset, malicious_relative, source_hash)
    output = tmp_path / "review.html"

    returned = build_packet(source, dataset, output, count=1, seed="exact seed")
    rendered = output.read_text(encoding="utf-8")
    embedded = _embedded_packet(rendered)

    assert embedded == returned
    candidate = embedded["candidates"][0]
    assert [note["pitch"] for note in candidate["snippets"][0]["notes"]] == [60, 62, 64, 65]
    assert len(candidate["snippets"]) == 2
    assert [note["pitch"] for note in candidate["snippets"][1]["notes"]] == [65, 67, 69, 70]
    assert [1, 2, 3, 4] not in [
        [note["pitch"] for note in snippet["notes"]]
        for snippet in candidate["snippets"]
    ]
    assert malicious_relative not in rendered
    assert "\\u003c/script\\u003e" in rendered
    assert "new Blob" in rendered
    assert "source_sha256" in rendered
    assert candidate["split_group"] == "source-1"
    assert candidate["family_id"] == "source-1"
    assert "split_group" in rendered
    assert "family_id" in rendered
    assert "Perceptual salience" in rendered
    assert "Same musical phrase?" in rendered
    assert "It is not source audio" in rendered


def test_packet_selects_two_other_intervals_without_repeating_prototype(tmp_path) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "three.mid"
    _write_midi(midi_path, third_occurrence=True)
    dataset = tmp_path / "dataset"
    phrase = _manifests(dataset, "three.mid", sha256(midi_path.read_bytes()).hexdigest())
    phrase["occurrences"].insert(1, dict(phrase["occurrences"][0]))
    phrase["occurrences"].append({"start_tick": 1920, "end_tick": 2340, "note_index": 8})
    (dataset / "phrases.jsonl").write_text(json.dumps(phrase) + "\n")

    snippets = build_packet(source, dataset, tmp_path / "review.html", count=1)["candidates"][0]["snippets"]

    assert len(snippets) == 3
    assert [[note["pitch"] for note in snippet["notes"]] for snippet in snippets] == [
        [60, 62, 64, 65], [65, 67, 69, 70], [67, 69, 71, 72],
    ]
    assert [snippet["label"] for snippet in snippets] == [
        "Prototype", "Other occurrence 1", "Other occurrence 2",
    ]


def test_packet_rejects_support_containing_only_prototype_copies(tmp_path) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "one.mid"
    _write_midi(midi_path)
    dataset = tmp_path / "dataset"
    phrase = _manifests(dataset, "one.mid", sha256(midi_path.read_bytes()).hexdigest())
    phrase["occurrences"] = [phrase["occurrences"][0]] * 2
    (dataset / "phrases.jsonl").write_text(json.dumps(phrase) + "\n")
    with pytest.raises(ValueError, match="distinct other occurrence"):
        build_packet(source, dataset, tmp_path / "review.html", count=1)


def test_percussion_packet_keeps_simultaneous_source_hits(tmp_path) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "drums.mid"
    _write_midi(midi_path, drum=True)
    source_hash = sha256(midi_path.read_bytes()).hexdigest()
    dataset = tmp_path / "dataset"
    _manifests(dataset, "drums.mid", source_hash, kind="percussion")

    packet = build_packet(source, dataset, tmp_path / "review.html", count=1)
    notes = packet["candidates"][0]["snippets"][0]["notes"]

    assert packet["candidates"][0]["kind"] == "percussion"
    assert packet["candidates"][0]["split_group"] == "source-1"
    assert packet["candidates"][0]["family_id"] == "source-1"
    assert [note["pitch"] for note in notes] == [36, 42, 38, 42]
    assert all(note["onset_beats"] >= 0 for note in notes)


def test_source_hash_and_jsonl_are_validated(tmp_path) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "song.mid"
    _write_midi(midi_path)
    dataset = tmp_path / "dataset"
    _manifests(dataset, "song.mid", "0" * 64)

    with pytest.raises(ValueError, match="source hash mismatch"):
        build_packet(source, dataset, tmp_path / "review.html", count=1)

    (dataset / "phrases.jsonl").write_text("{bad json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        build_packet(source, dataset, tmp_path / "review.html", count=1)


def test_declared_metadata_receipt_opts_into_recovery_and_is_compared(tmp_path, monkeypatch) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "song.mid"
    _write_midi(midi_path)
    dataset = tmp_path / "dataset"
    source_hash = sha256(midi_path.read_bytes()).hexdigest()
    _manifests(dataset, "song.mid", source_hash)
    source_manifest = dataset / "sources.jsonl"
    source_row = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_row["metadata_repairs"] = []
    source_manifest.write_text(json.dumps(source_row) + "\n", encoding="utf-8")

    calls = []

    def tracked_load(path, *, recover_invalid_keys=False):
        calls.append(recover_invalid_keys)
        return strict_load_midi(path, recover_invalid_keys=recover_invalid_keys)

    monkeypatch.setattr(review_module, "load_midi", tracked_load)
    packet = build_packet(source, dataset, tmp_path / "review.html", count=1)

    assert calls == [True]
    assert packet["candidates"][0]["metadata_repairs"] == []

    source_row["metadata_repairs"] = [{"kind": "unexpected"}]
    source_manifest.write_text(json.dumps(source_row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata repair receipt mismatch"):
        build_packet(source, dataset, tmp_path / "mismatch.html", count=1)


def test_sample_configuration_validation() -> None:
    with pytest.raises(ValueError):
        sample_rows([], 0)
    with pytest.raises(ValueError):
        sample_rows([], 501)
    with pytest.raises(ValueError):
        sample_rows([], 1, "")


def test_snippet_preserves_tempo_and_exact_note_window() -> None:
    # A sustained prototype note overlaps the next window's onset. Selecting
    # all onsets inside its end tick would incorrectly include the third note.
    notes = [Note(480, 1920, 60, 90), Note(960, 1080, 64, 80), Note(1440, 1560, 67, 70)]
    song = MidiSong(480, [], [(0, 500_000), (960, 1_000_000)], [(0, 4, 4)], [])
    result = _snippet(notes, 480, 1920, song, "Prototype", "test", 0, 2)
    assert len(result["notes"]) == 2
    assert result["duration_seconds"] == 2.5
    assert result["notes"][0]["duration_seconds"] == 2.5
    assert result["notes"][1]["onset_seconds"] == .5
    assert result["notes"][1]["duration_seconds"] == .25
    with pytest.raises(ValueError, match="note coordinates"):
        _snippet(notes, 480, 1920, song, "Prototype", "test", 1, 3)
    with pytest.raises(ValueError, match="note coordinates"):
        _snippet(notes, 480, 1560, song, "Prototype", "test", 1, 2)


def test_packet_uses_per_occurrence_note_count_for_aligned_rows(tmp_path) -> None:
    source = tmp_path / "corpus"
    midi_path = source / "aligned.mid"
    _write_midi(midi_path, variable_occurrence=True)
    dataset = tmp_path / "dataset"
    phrase = _manifests(
        dataset, "aligned.mid", sha256(midi_path.read_bytes()).hexdigest()
    )
    phrase["occurrences"][1].update({"end_tick": 1500, "note_count": 5})
    (dataset / "phrases.jsonl").write_text(json.dumps(phrase) + "\n")

    snippets = build_packet(
        source, dataset, tmp_path / "review.html", count=1
    )["candidates"][0]["snippets"]

    assert [len(snippet["notes"]) for snippet in snippets] == [4, 5]
    assert [note["pitch"] for note in snippets[1]["notes"]] == [65, 67, 69, 70, 72]
