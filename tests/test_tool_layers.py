import mido
import pytest

from scripts.render_tool_layers import combine_tracks


def layer(path, channel, *, ticks=480, length=960):
    midi = mido.MidiFile(type=1, ticks_per_beat=ticks)
    midi.tracks.append(mido.MidiTrack([
        mido.MetaMessage('set_tempo', tempo=500000, time=0),
        mido.MetaMessage('time_signature', numerator=7, denominator=8, time=0),
        mido.MetaMessage('end_of_track', time=length),
    ]))
    midi.tracks.append(mido.MidiTrack([
        mido.Message('program_change', channel=channel, program=33, time=0),
        mido.Message('note_on', channel=channel, note=36, velocity=101, time=120),
        mido.Message('note_off', channel=channel, note=36, velocity=0, time=240),
        mido.MetaMessage('end_of_track', time=length-360),
    ]))
    midi.save(path)
    return midi


def test_combined_loop_preserves_tempo_channels_note_timing_and_velocity(tmp_path):
    riff = layer(tmp_path/'riff.mid', 0)
    drums = layer(tmp_path/'drums.mid', 9)
    combine_tracks(tmp_path/'riff.mid', tmp_path/'drums.mid', tmp_path/'loop.mid')
    combined = mido.MidiFile(tmp_path/'loop.mid')
    assert combined.tracks[0] == riff.tracks[0]
    assert combined.tracks[1] == riff.tracks[1]
    assert combined.tracks[2] == drums.tracks[1]
    assert all(sum(m.time for m in track) == 960 for track in combined.tracks)
    assert [m.channel for track in combined.tracks for m in track if m.type == 'note_on'] == [0, 9]


@pytest.mark.parametrize('ticks,length,channel', [(960,960,9),(480,1920,9),(480,960,0)])
def test_misaligned_or_nonpercussion_layer_is_rejected(tmp_path, ticks, length, channel):
    layer(tmp_path/'riff.mid', 0)
    layer(tmp_path/'drums.mid', channel, ticks=ticks, length=length)
    with pytest.raises(ValueError):
        combine_tracks(tmp_path/'riff.mid', tmp_path/'drums.mid', tmp_path/'loop.mid')
