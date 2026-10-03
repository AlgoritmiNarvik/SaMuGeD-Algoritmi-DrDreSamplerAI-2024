import json
from dataclasses import asdict
from pathlib import Path
from copy import deepcopy

import mido
from jsonschema import Draft202012Validator

from samuged.aligned import AlignedConfig
from samuged.dataset import _work, finalize
from samuged.phrases import Config
from scripts.validate_schema import validate_dataset, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def occurrence(start, end, *, note_index=None, transpose=0):
    row = {
        "start_tick": start,
        "end_tick": end,
        "similarity": 1.0,
        "transpose_semitones": transpose,
    }
    if note_index is not None:
        row["note_index"] = note_index
    return row


def melodic_phrase(*, manifest=True, artifact=True):
    row = {
        "channel": 0,
        "duration_beats": 4.0,
        "durations_beats": [0.5, 0.5, 0.5, 0.5],
        "end_tick": 1920,
        "family_id": "b" * 64,
        "kind": "melodic",
        "note_count": 4,
        "occurrence_count": 2,
        "occurrences": [
            occurrence(0, 1920, note_index=0),
            occurrence(3840, 5760, note_index=8),
        ],
        "onsets_beats": [0.0, 1.0, 2.0, 3.0],
        "part_index": 0,
        "part_name": "lead",
        "phrase_id": "c" * 32,
        "pitches": [60, 62, 64, 65],
        "program": 0,
        "prototype_note_index": 0,
        "rank_in_file": 1,
        "raw_occurrence_count": 2,
        "recurrence_score": 0.9,
        "score_components": {"support": 1.0},
        "source_track": 0,
        "start_tick": 0,
        "velocities": [90, 90, 90, 90],
    }
    if artifact:
        row["midi_path"] = "midi/melodic/" + "d" * 32 + ".mid"
        row["midi_sha256"] = "e" * 64
    if manifest:
        row.update(
            {
                "artist_from_path": "Artist",
                "song_key": "a" * 24,
                "source_id": "1" * 24,
                "source_path": "Artist/Track.MID",
                "source_sha256": "f" * 64,
                "split": "train",
                "split_group": "2" * 24,
                "ticks_per_beat": 480,
                "title_from_path": "Track",
            }
        )
    return row


def percussion_phrase(*, manifest=True, artifact=False):
    row = {
        "bar_count": 1,
        "channel": 9,
        "duration_beats": 4.0,
        "duration_policy": "clip_at_next_same_pitch_hit",
        "durations_beats": [0.5, 0.5, 0.5, 0.5],
        "end_tick": 1920,
        "family_id": "3" * 64,
        "kind": "percussion",
        "kit_programs": [0],
        "meter_denominator": 4,
        "meter_numerator": 4,
        "note_count": 4,
        "occurrence_count": 2,
        "occurrences": [
            occurrence(0, 1920),
            occurrence(3840, 5760),
        ],
        "onsets_beats": [0.0, 1.0, 2.0, 3.0],
        "part_index": -1,
        "phrase_id": "4" * 32,
        "pitches": [36, 38, 42, 46],
        "rank_in_file": 1,
        "recurrence_score": 0.8,
        "score_components": {"support": 1.0},
        "source_part_indices": [0],
        "source_tracks": [0],
        "start_tick": 0,
        "velocities": [90, 90, 90, 90],
    }
    if artifact:
        row["midi_path"] = "midi/percussion/" + "5" * 32 + ".mid"
        row["midi_sha256"] = "6" * 64
    if manifest:
        row.update(
            {
                "artist_from_path": "Artist",
                "song_key": "a" * 24,
                "source_id": "1" * 24,
                "source_path": "Artist/Track.MID",
                "source_sha256": "f" * 64,
                "split": "train",
                "split_group": "2" * 24,
                "ticks_per_beat": 480,
                "title_from_path": "Track",
            }
        )
    return row


def source_row(*, include_optional=True):
    row = {
        "artist_from_path": "Artist",
        "artist_key": "artist",
        "candidate_count": 1,
        "config": {
            "duration_error_fraction": 0.25,
            "duration_tolerance": 0.25,
            "lengths": [4],
            "max_beats": 32.0,
            "max_bucket": 192,
            "max_candidates": 80,
            "max_comparisons": 250000,
            "max_gap_beats": 2.0,
            "max_stream_notes": 12000,
            "max_windows": 80000,
            "min_beats": 4.0,
            "mode": "approximate",
            "onset_merge_beats": 1 / 24,
            "pitch_error_fraction": 0.125,
            "timing_tolerance": 0.125,
            "top_k": 3,
        },
        "curation_truncated": False,
        "elapsed_seconds": 0.1,
        "musical_sha256": "7" * 64,
        "note_count": 8,
        "outcome": "matched",
        "part_count": 1,
        "part_stats": [
            {
                "candidate_limit_reached": False,
                "candidates_truncated": 0,
                "comparison_limit_reached": False,
                "comparisons": 1,
                "input_notes": 8,
                "note_limit_reached": False,
                "overlapping_occurrences_removed": 0,
                "part_index": 0,
                "raw_groups": 1,
                "repeat_groups": 1,
                "saturated_seed_buckets": 0,
                "skyline_notes": 8,
                "window_limit_reached": False,
                "windows": 1,
                "windows_considered": 1,
            }
        ],
        "raw_repeat_group_count": 1,
        "run_key": "8" * 64,
        "search_limited": False,
        "shortlisted_candidate_count": 1,
        "song_key": "a" * 24,
        "source_bytes": 100,
        "source_id": "1" * 24,
        "source_path": "Artist/Track.MID",
        "source_sha256": "f" * 64,
        "split": "train",
        "split_group": "2" * 24,
        "status": "ok",
        "ticks_per_beat": 480,
        "title_from_path": "Track",
        "warnings": [],
    }
    if include_optional:
        row["phrases"] = [melodic_phrase(manifest=False, artifact=False)]
        row["drum_stats"] = {
            "bar_origin_assumption": "bar zero starts at tick zero",
            "candidate_count": 0,
            "candidate_limit_reached": False,
            "candidates_truncated": 0,
            "comparison_limit_reached": False,
            "comparisons": 0,
            "config": {
                "bar_counts": [1],
                "hit_error_fraction": 0.1,
                "max_bucket": 64,
                "max_candidates": 80,
                "max_comparisons": 60000,
                "max_hits": 100000,
                "max_window_hits": 4096,
                "max_windows": 12000,
                "min_hits": 8,
                "min_pitches": 2,
                "mode": "tolerant",
                "timing_tolerance_beats": 1 / 12,
                "top_k": 3,
            },
            "diversity_comparisons": 0,
            "diversity_pruned": 0,
            "duplicate_hits_removed": 0,
            "eligible_windows": 0,
            "hit_limit_reached": False,
            "input_drum_parts": 0,
            "input_hits": 0,
            "kit_programs": [],
            "merged_hits": 0,
            "meter_segments": 1,
            "mode": "tolerant",
            "oversized_windows": 0,
            "raw_candidate_count": 0,
            "raw_group_count": 0,
            "saturated_seed_buckets": 0,
            "search_limited": False,
            "selected_count": 0,
            "source_part_indices": [],
            "source_tracks": [],
            "window_attempts": 0,
            "window_limit_reached": False,
            "windows_considered": 0,
        }
    row["phrases"] = row.get("phrases", [])
    return row


def write_dataset(directory, sources, phrases):
    directory.mkdir()
    (directory / "sources.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in sources), encoding="utf-8"
    )
    (directory / "phrases.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in phrases), encoding="utf-8"
    )


def write_repeated_midi(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for repetition in range(3):
        for index, pitch in enumerate([60, 62, 65, 64, 67, 65, 62, 60, 64, 65, 69, 67]):
            track.append(
                mido.Message(
                    "note_on",
                    note=pitch,
                    velocity=90,
                    time=24 + (2880 if repetition and index == 0 else 0),
                )
            )
            track.append(mido.Message("note_off", note=pitch, time=216))
    midi.save(path)


def aligned_worker_manifests(tmp_path, algorithm="aligned", *, percussion=False, recover=False):
    source = tmp_path / "source.mid"
    output = tmp_path / "aligned"
    write_repeated_midi(source)
    if percussion or recover:
        midi = mido.MidiFile(source)
        if percussion:
            track = mido.MidiTrack()
            midi.tracks.append(track)
            for _ in range(24):
                track.append(mido.Message('note_on', channel=9, note=36, velocity=80, time=0))
                track.append(mido.Message('note_on', channel=9, note=42, velocity=80, time=0))
                track.append(mido.Message('note_off', channel=9, note=36, time=60))
                track.append(mido.Message('note_off', channel=9, note=42, time=180))
        if recover:
            midi.tracks[0].insert(0, mido.MetaMessage('key_signature', key='C'))
        midi.save(source)
        if recover:
            source.write_bytes(source.read_bytes().replace(b'\xff\x59\x02\x00\x00', b'\xff\x59\x02\x08\x00', 1))
    row = _work(
        (
            str(source),
            "Artist/source.mid",
            str(output),
            asdict(AlignedConfig()),
            "a" * 64,
            True,
            percussion,
            algorithm,
            recover,
        )
    )
    assert row["status"] == "ok" and row["phrases"]
    finalize([row], output, {})
    sources = [json.loads(line) for line in (output / "sources.jsonl").read_text().splitlines()]
    phrases = [json.loads(line) for line in (output / "phrases.jsonl").read_text().splitlines()]
    return sources, phrases


def reference_worker_manifests(tmp_path):
    source = tmp_path / "source.mid"
    output = tmp_path / "reference"
    write_repeated_midi(source)
    row = _work(
        (
            str(source),
            "Artist/source.mid",
            str(output),
            asdict(Config()),
            "a" * 64,
            True,
            False,
            "reference",
            False,
        )
    )
    assert row["status"] == "ok" and row["phrases"]
    finalize([row], output, {})
    sources = [json.loads(line) for line in (output / "sources.jsonl").read_text().splitlines()]
    phrases = [json.loads(line) for line in (output / "phrases.jsonl").read_text().splitlines()]
    return sources, phrases


def metadata_repair():
    return {
        "kind": "invalid_key_signature_retyped_as_sequencer_specific",
        "track_index": 0,
        "event_index": 1,
        "tick": 0,
        "offset_basis": "unwrapped_smf_bytes",
        "event_offset": 14,
        "status_offset": 15,
        "meta_type_offset": 16,
        "payload_offset": 19,
        "original_meta_type": 89,
        "replacement_meta_type": 127,
        "original_payload_hex": "0800",
        "reason": "signed_key_out_of_range",
        "original_smf_sha256": "a" * 64,
        "recovered_smf_sha256": "b" * 64,
    }


def validator(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_synthetic_manifests_validate_and_report_counts(tmp_path):
    dataset = tmp_path / "dataset"
    write_dataset(dataset, [source_row()], [melodic_phrase(), percussion_phrase()])

    result = validate_dataset(dataset)

    assert result["source_rows"] == 1
    assert result["phrase_rows"] == 2
    assert result["valid_rows"] == 3
    assert result["invalid_rows"] == 0
    assert result["errors"] == []


def test_schemas_accept_actual_melodic_and_percussion_shapes():
    assert not list(validator("source").iter_errors(source_row()))
    assert not list(validator("phrase").iter_errors(melodic_phrase()))
    assert not list(validator("phrase").iter_errors(percussion_phrase()))


def test_reference_worker_cache_stats_validate(tmp_path):
    sources, phrases = reference_worker_manifests(tmp_path)

    assert sources[0]["part_stats"][0]["exact_cache_hits"] > 0
    assert not list(validator("source").iter_errors(sources[0]))
    assert phrases
    assert all(not list(validator("phrase").iter_errors(row)) for row in phrases)


def test_source_without_optional_phrase_or_drum_stats_is_valid():
    row = source_row(include_optional=False)

    assert not list(validator("source").iter_errors(row))


def test_no_midi_artifacts_are_optional_but_must_be_a_pair():
    row = melodic_phrase(artifact=False)
    assert not list(validator("phrase").iter_errors(row))

    row["midi_path"] = "midi/melodic/" + "d" * 32 + ".mid"
    assert list(validator("phrase").iter_errors(row))


def test_future_aligned_occurrence_fields_are_allowed():
    row = melodic_phrase()
    row["occurrences"][0]["note_count"] = row["note_count"]
    row["occurrences"][0]["matched_pairs"] = [[0, 0], [1, 1]]

    assert not list(validator("phrase").iter_errors(row))


def test_overlap_excluded_phrase_requires_source_split():
    row = melodic_phrase()
    row["split"] = "overlap_excluded"
    assert list(validator("phrase").iter_errors(row))

    row["source_split"] = "train"
    assert not list(validator("phrase").iter_errors(row))


def test_schema_rejects_tampered_types_and_conditional_fields():
    phrase = melodic_phrase()
    phrase["note_count"] = "4"
    assert list(validator("phrase").iter_errors(phrase))

    melodic = melodic_phrase()
    melodic.pop("part_name")
    assert list(validator("phrase").iter_errors(melodic))

    percussion = percussion_phrase()
    percussion["part_index"] = 0
    assert list(validator("phrase").iter_errors(percussion))

    percussion["part_index"] = -1
    percussion["channel"] = 10
    assert list(validator("phrase").iter_errors(percussion))


def test_manifest_diagnostics_are_bounded(tmp_path):
    row = melodic_phrase()
    manifest = tmp_path / "phrases.jsonl"
    manifest.write_text(
        "".join(json.dumps({**row, "note_count": "bad"}) + "\n" for _ in range(6)),
        encoding="utf-8",
    )

    result = validate_manifest(manifest, SCHEMAS / "phrase.schema.json", max_errors=2)

    assert result["rows"] == 6
    assert result["valid"] == 0
    assert result["invalid"] == 6
    assert len(result["errors"]) == 2


def test_aligned_worker_export_validates_nested_and_standalone_rows(tmp_path):
    sources, phrases = aligned_worker_manifests(tmp_path)

    assert not list(validator("source").iter_errors(sources[0]))
    assert phrases
    assert all(not list(validator("phrase").iter_errors(row)) for row in phrases)
    assert sources[0]["config"]["min_notes"] == asdict(AlignedConfig())["min_notes"]
    assert sources[0]["phrases"][0]["matcher_flags"]["monotone_alignment"] is True
    assert sources[0]["phrases"][0]["occurrences"][1]["matched_note_pairs"]


def test_aligned_indexed_worker_export_validates_extended_part_stats(tmp_path):
    sources, phrases = aligned_worker_manifests(tmp_path, "aligned_indexed")

    source = sources[0]
    assert source["index_variant"] == "exact_first_cached_v1"
    assert not list(validator("source").iter_errors(source))
    assert phrases
    assert all(not list(validator("phrase").iter_errors(row)) for row in phrases)

    indexed_fields = {
        "exact_fast_path_hits",
        "seed_key_calls",
        "seed_keys_bypassed",
        "exact_key_cache_hits",
        "posting_entries_visited",
        "seed_index_keys",
        "seed_index_postings",
        "max_seed_bucket_size",
        "saturated_seed_postings_dropped",
        "saturated_seed_key_types",
    }
    assert indexed_fields <= set(source["part_stats"][0])
    assert set(source["part_stats"][0]["saturated_seed_key_types"]) <= {
        "single",
        "pair",
    }


def test_aligned_indexed_nested_counter_types_and_completeness_are_strict(tmp_path):
    sources, _phrases = aligned_worker_manifests(tmp_path, "aligned_indexed")

    source = deepcopy(sources[0])
    source["part_stats"][0]["posting_entries_visited"] = "many"
    assert list(validator("source").iter_errors(source))

    source = deepcopy(sources[0])
    source["part_stats"][0].pop("seed_index_keys")
    assert list(validator("source").iter_errors(source))

    source = deepcopy(sources[0])
    source["part_stats"][0]["saturated_seed_key_types"] = {"triple": 1}
    assert list(validator("source").iter_errors(source))


def test_aligned_config_shape_is_disambiguated_from_reference_config(tmp_path):
    sources, _phrases = aligned_worker_manifests(tmp_path)
    aligned = sources[0]
    aligned["config"]["mode"] = "approximate"
    assert list(validator("source").iter_errors(aligned))

    reference = source_row()
    reference["config"].pop("mode")
    assert list(validator("source").iter_errors(reference))


def test_aligned_occurrence_fields_and_counts_are_required_when_flagged(tmp_path):
    _sources, phrases = aligned_worker_manifests(tmp_path)
    phrase = deepcopy(phrases[0])
    phrase["occurrences"][1]["edit_count"] = "zero"
    assert list(validator("phrase").iter_errors(phrase))

    phrase = deepcopy(phrases[0])
    phrase["occurrences"][1].pop("note_count")
    assert list(validator("phrase").iter_errors(phrase))

    phrase = deepcopy(phrases[0])
    phrase["matcher_flags"]["tempo_warp"] = "false"
    assert list(validator("phrase").iter_errors(phrase))


def test_metadata_repair_receipt_is_bounded_and_strict():
    row = source_row()
    row["metadata_repairs"] = [metadata_repair()]
    assert not list(validator("source").iter_errors(row))

    row["metadata_repairs"][0]["offset_basis"] = "raw_file_bytes"
    assert list(validator("source").iter_errors(row))

    row = source_row()
    row["metadata_repairs"] = [{**metadata_repair(), "unexpected": True}]
    assert list(validator("source").iter_errors(row))

    row = source_row()
    row["metadata_repairs"] = [{**metadata_repair(), "original_payload_hex": "abc"}]
    assert list(validator("source").iter_errors(row))
    schema = json.loads((SCHEMAS/'source.schema.json').read_text())
    from samuged.midi import MAX_MIDI_BYTES
    assert schema['$defs']['metadataRepair']['properties']['original_payload_hex']['maxLength'] == 2*MAX_MIDI_BYTES


def test_actual_recovery_receipts_and_drum_phrases_validate_in_aligned_source(tmp_path):
    sources, phrases = aligned_worker_manifests(tmp_path, 'aligned_indexed', percussion=True, recover=True)
    assert {row['kind'] for row in phrases} == {'melodic', 'percussion'}
    assert sources[0]['metadata_repairs'][0]['original_smf_sha256']
    assert not list(validator('source').iter_errors(sources[0]))
    assert all(not list(validator('phrase').iter_errors(row)) for row in phrases)
    damaged = deepcopy(sources[0])
    del damaged['metadata_repairs'][0]['recovered_smf_sha256']
    assert list(validator('source').iter_errors(damaged))
