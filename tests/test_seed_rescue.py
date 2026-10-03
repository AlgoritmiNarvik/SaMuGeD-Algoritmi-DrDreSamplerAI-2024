import json

import pytest

from samuged import aligned
from samuged.aligned import AlignedConfig
from samuged.midi import Note
from samuged.phrases import window
from scripts.compare_seed_rescue import (
    _ORIGINAL_SEED_KEYS,
    _read_jsonl_lf,
    _seed_method,
    _worker,
    seed_keys_for_method,
)


def _window(pitches, onsets, durations=None, ppq=96):
    durations = durations or [0.5] * len(pitches)
    notes = [
        Note(round(onset * ppq), round((onset + duration) * ppq), pitch, 80)
        for pitch, onset, duration in zip(pitches, onsets, durations)
    ]
    return window(notes, 0, len(notes), ppq)


def test_terminal_seed_ignores_duration_only_span_change():
    cfg = AlignedConfig()
    pitches = [60, 62, 64, 65, 67, 69]
    onsets = [0, 0.5, 1.0, 1.5, 2.0, 4.0]
    short = _window(pitches, onsets, [0.5] * 6)
    long = _window(pitches, onsets, [0.5] * 5 + [1.5])
    assert set(seed_keys_for_method(short, cfg, "terminal_onset")) == set(
        seed_keys_for_method(long, cfg, "terminal_onset")
    )
    assert set(seed_keys_for_method(short, cfg, "baseline")) != set(
        seed_keys_for_method(long, cfg, "baseline")
    )


def test_union_adds_one_short_key_per_distinct_offset():
    cfg = AlignedConfig()
    candidate = _window(
        [60, 62, 64, 65, 67, 69, 71, 72],
        [0, 0.5, 1, 1.5, 2, 2.5, 3, 4],
    )
    keys = seed_keys_for_method(candidate, cfg, "terminal_onset_union_short")
    offsets = aligned._offsets(8, cfg.seed_notes, cfg.max_seed_offsets)
    short_keys = [key for key in keys if key[0] == "short_distinct"]
    assert len(short_keys) == len(offsets)
    assert {key[1] for key in short_keys} == set(offsets)
    assert any(key[0] == "pair_terminal" for key in keys)


def test_long_union_uses_only_terminal_composite_keys():
    cfg = AlignedConfig()
    candidate = _window(list(range(60, 69)), list(range(9)))
    keys = seed_keys_for_method(candidate, cfg, "terminal_onset_union_short")
    assert keys
    assert all(key[0] in {"single_terminal", "pair_terminal"} for key in keys)


def test_union_retains_composite_namespace_across_eight_and_nine_notes():
    cfg = AlignedConfig()
    short = _window(list(range(60, 68)), list(range(8)))
    long = _window(list(range(60, 69)), list(range(9)))
    short_keys = set(
        seed_keys_for_method(short, cfg, "terminal_onset_union_short")
    )
    long_keys = set(
        seed_keys_for_method(long, cfg, "terminal_onset_union_short")
    )
    assert "pair_terminal" in {key[0] for key in short_keys}
    assert "pair_terminal" in {key[0] for key in long_keys}
    assert "short_distinct" in {key[0] for key in short_keys}
    assert "short_distinct" not in {key[0] for key in long_keys}


def test_process_local_patch_is_restored_on_error():
    assert aligned._seed_keys is _ORIGINAL_SEED_KEYS
    with pytest.raises(RuntimeError):
        with _seed_method("terminal_onset"):
            assert aligned._seed_keys is not _ORIGINAL_SEED_KEYS
            raise RuntimeError("stop")
    assert aligned._seed_keys is _ORIGINAL_SEED_KEYS


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_jsonl_reader_preserves_unicode_separator_in_filename(tmp_path, separator):
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text(
        '{"source_path":"artist/a' + separator + 'b.mid","status":"ok"}\n'
        '{"source_path":"artist/c.mid","status":"ok"}\n',
        encoding="utf-8",
    )
    rows = _read_jsonl_lf(manifest)
    assert len(rows) == 2
    assert rows[0]["source_path"] == "artist/a" + separator + "b.mid"


def test_lf_reader_matches_historical_reader_for_safe_rows(tmp_path):
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
    historical = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert _read_jsonl_lf(manifest) == historical


def test_worker_checks_source_bytes_before_midi_parse(tmp_path):
    source = tmp_path / "case.mid"
    source.write_bytes(b"not midi")
    with pytest.raises(ValueError, match="source changed before worker parse"):
        _worker({
            "task_kind": "midi",
            "source_path": str(source),
            "source_sha256": "0" * 64,
            "source_bytes": len(source.read_bytes()),
        })
