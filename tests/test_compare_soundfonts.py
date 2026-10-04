from pathlib import Path
import mido
import pytest
from scripts.compare_soundfonts import repeat_cycle, render_with_headroom
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


def test_synthesis_retries_before_normalization_can_hide_clipping(monkeypatch):
    gains = []
    def render(*args, synthesis_gain):
        gains.append(synthesis_gain)
        return {'input_peak': min(1.0, 4 * synthesis_gain), 'synthesis_gain': synthesis_gain}
    monkeypatch.setattr('scripts.compare_soundfonts._render_audio', render)
    result = render_with_headroom(None, None, None, None, 1)
    assert gains == [0.45, 0.225]
    assert result['input_peak'] == pytest.approx(0.9)
    assert result['synthesis_gain'] == 0.225


def test_synthesis_retry_is_bounded(monkeypatch):
    monkeypatch.setattr('scripts.compare_soundfonts._render_audio', lambda *a, **k: {'input_peak': 1.0})
    with pytest.raises(ValueError, match='headroom'):
        render_with_headroom(None, None, None, None, 1)


def test_synthesis_checks_peak_outside_the_selected_cycle(monkeypatch):
    gains = []
    def render(*args, synthesis_gain):
        gains.append(synthesis_gain)
        return {'input_peak': 0.1, 'synthesis_peak': min(1.0, 4 * synthesis_gain)}
    monkeypatch.setattr('scripts.compare_soundfonts._render_audio', render)
    render_with_headroom(None, None, None, None, 1)
    assert gains == [0.45, 0.225]


def test_effect_profile_survives_headroom_retry(monkeypatch):
    calls = []
    def render(*args, synthesis_gain, effects_profile):
        calls.append((synthesis_gain, effects_profile))
        return {'input_peak': 0.1, 'synthesis_peak': min(1.0, 4 * synthesis_gain)}
    monkeypatch.setattr('scripts.compare_soundfonts._render_audio', render)
    render_with_headroom(None, None, None, None, 1, effects_profile='warm_room')
    assert calls == [(0.45, 'warm_room'), (0.225, 'warm_room')]


def test_unknown_effect_profile_fails_before_launch():
    from samuged.audio_loops import _render_audio
    with pytest.raises(ValueError, match='unknown effects profile'):
        _render_audio(None, None, None, None, 1, effects_profile='unknown')


def test_renderer_applies_and_records_explicit_room_settings(monkeypatch, tmp_path):
    from samuged.audio_loops import EFFECT_PROFILES, _render_audio
    commands = []
    monkeypatch.setattr('samuged.audio_loops._run', lambda command, label: commands.append(command))
    monkeypatch.setattr('samuged.audio_loops._read_wave', lambda path: (np.zeros((10, 2)), 48000))
    monkeypatch.setattr('samuged.audio_loops.process_steady_cycle', lambda *a: (np.zeros((10, 2)), {}))
    result = _render_audio(Path('input.mid'), Path('bank.sf2'), Path('fluidsynth'),
                           tmp_path / 'loop.wav', 1, effects_profile='close_room')
    command = commands[0]
    for setting, value in EFFECT_PROFILES['close_room'].items():
        position = command.index(f'{setting}={value}')
        assert command[position - 1] == '-o'
    assert command[-2:] == ['bank.sf2', 'input.mid']
    assert result['effects_settings'] == EFFECT_PROFILES['close_room']
    assert result['effects_profile'] == 'close_room'


def test_room_page_rerun_replaces_block_and_preserves_bank_players():
    from scripts.compare_effects import add_auditions
    page = '<h1>Comparison</h1><section>Earlier bank players</section>'
    once = add_auditions(page, '<section>First rooms</section>')
    twice = add_auditions(once, '<section>New rooms</section>')
    assert 'First rooms' not in twice
    assert twice.count('New rooms') == 1
    assert twice.count('Earlier bank players') == 1
