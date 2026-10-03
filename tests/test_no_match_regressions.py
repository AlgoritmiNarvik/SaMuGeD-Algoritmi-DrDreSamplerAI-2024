from samuged.aligned import AlignedConfig
from samuged.midi import Note
from samuged.phrases import window
from scripts.audit_no_match_regressions import pair_diagnostics


def _window(pitches, onsets, *, ppq=96, index=0):
    notes = [
        Note(round(onset * ppq), round((onset + 0.5) * ppq), pitch, 80)
        for pitch, onset in zip(pitches, onsets)
    ]
    candidate = window(notes, 0, len(notes), ppq)
    candidate.index = index
    return candidate


def test_pair_diagnostics_separates_verifier_from_seed_support():
    cfg = AlignedConfig()
    left = _window(
        [75, 70, 51, 64, 63, 58, 46, 55],
        [0, 0.44791667, 0.84375, 1.35416667, 1.9375, 2.48958333, 2.91666667, 3.36458333],
    )
    right = _window(
        [80, 75, 56, 69, 68, 63, 54, 60],
        [0, 0.5, 0.85416667, 1.375, 1.95833333, 2.52083333, 2.96875, 3.38541667],
        index=20,
    )
    result = pair_diagnostics(left, right, cfg)
    assert result["direct_alignment"] is not None
    assert result["direct_alignment"]["shift"] == 5
    assert result["shared_seed_key_count"] == 2
    assert result["seed_support_pass"] is False


def test_pair_diagnostics_reports_terminal_timing_rule():
    cfg = AlignedConfig()
    left = _window([60, 62, 64, 65, 67, 69], [0, 1, 2, 3, 4, 5])
    right = _window([65, 67, 69, 70, 72, 74], [0, 1, 2, 3, 4, 5.25], index=20)
    result = pair_diagnostics(left, right, cfg)
    assert result["terminal_timing_pass"] is False
    assert result["direct_alignment"] is None
