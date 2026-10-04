from pathlib import Path
import mido
import pytest
from scripts.compare_soundfonts import repeat_cycle
from samuged.audio_loops import _read_wave, write_pcm24_wave
import numpy as np


def test_repeat_preserves_tempo_program_and_cycle_boundary(tmp_path: Path):
    source = tmp_path / 'loop.mid'
    output = tmp_path / 'repeated.mid'
    midi = mido.MidiFile(ticks_per_beat=480)
    midi.tracks.append(mido.MidiTrack([
        mido.MetaMessage('set_tempo', tempo=600000),
        mido.Message('program_change', channel=2, program=34),
        mido.Message('note_on', channel=2, note=40, velocity=79),
        mido.Message('note_off', channel=2, note=40, time=480),
        mido.MetaMessage('end_of_track'),
    ]))
    midi.save(source)
    repeat_cycle(source, output, 480, 6)
    result = mido.MidiFile(output)
    assert result.length == pytest.approx(3.6)
    assert [m.velocity for m in result.tracks[0] if m.type == 'note_on'] == [79] * 6
    assert [m.program for m in result.tracks[0] if m.type == 'program_change'] == [34] * 6
    with pytest.raises(ValueError, match='beyond'):
        repeat_cycle(source, output, 400, 6)


def test_pcm24_retains_sign_and_detail_below_pcm16_step(tmp_path: Path):
    path = tmp_path / 'detail.wav'
    source = np.array([[1e-5, -1e-5], [.25, -.25]])
    write_pcm24_wave(path, source)
    restored, rate = _read_wave(path)
    assert rate == 48000
    np.testing.assert_allclose(restored, source, atol=2 / 8388608)
    assert restored[0, 0] > 0
    assert restored[0, 1] < 0
