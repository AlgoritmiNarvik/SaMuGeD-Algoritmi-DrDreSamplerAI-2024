"""Optional whole MIDI rendering with a locally supplied BASSMIDI runtime.

The proprietary runtime is not bundled. This adapter is for local listening
comparisons; review the vendor license before using it in another setting.
"""
from __future__ import annotations

import ctypes as ct
from pathlib import Path

import numpy as np

from samuged.audio_loops import SAMPLE_RATE, process_steady_cycle, write_pcm24_wave


class Font(ct.Structure):
    _fields_ = [('font', ct.c_uint32), ('preset', ct.c_int), ('bank', ct.c_int)]


def render_bass_audio(midi: Path, bank: Path, runtime: Path, destination: Path,
                      cycle_seconds: float) -> dict:
    """Decode the complete arrangement without opening an audio device."""
    core = ct.CDLL(str((runtime / 'core/libbass.dylib').resolve()), mode=ct.RTLD_GLOBAL)
    synth = ct.CDLL(str((runtime / 'midi/libbassmidi.dylib').resolve()))
    u32, u64, ptr, integer = ct.c_uint32, ct.c_uint64, ct.c_void_p, ct.c_int

    def bind(lib, name, args, result=u32):
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
        return function

    error = bind(core, 'BASS_ErrorGetCode', [], integer)
    init = bind(core, 'BASS_Init', [integer, u32, u32, ptr, ptr], integer)
    free = bind(core, 'BASS_Free', [], integer)
    stream_free = bind(core, 'BASS_StreamFree', [u32], integer)
    data = bind(core, 'BASS_ChannelGetData', [u32, ptr, u32])
    core_version = bind(core, 'BASS_GetVersion', [])
    midi_version = bind(synth, 'BASS_MIDI_GetVersion', [])
    font_init = bind(synth, 'BASS_MIDI_FontInit', [ct.c_char_p, u32])
    font_free = bind(synth, 'BASS_MIDI_FontFree', [u32], integer)
    create = bind(synth, 'BASS_MIDI_StreamCreateFile', [u32, ct.c_char_p, u64, u64, u32, u32])
    set_fonts = bind(synth, 'BASS_MIDI_StreamSetFonts', [u32, ct.POINTER(Font), u32], integer)
    get_preset = bind(synth, 'BASS_MIDI_StreamGetPreset', [u32, u32, ct.POINTER(Font)], integer)

    def require(value, label):
        if not value:
            raise RuntimeError(f'{label} failed, BASS error {error()}')
        return value

    require(init(0, SAMPLE_RATE, 0, None, None), 'BASS initialization')
    stream = font = 0
    try:
        font = require(font_init(str(bank.resolve()).encode(), 0), 'SoundFont load')
        # Decode, floating point output and sinc interpolation. Effects remain
        # the engine defaults and are explicitly labelled in the receipt.
        flags = 0x200000 | 0x100 | 0x800000
        stream = require(create(0, str(midi.resolve()).encode(), 0, 0, flags, SAMPLE_RATE), 'MIDI stream')
        setting = Font(font, -1, 0)
        require(set_fonts(stream, ct.byref(setting), 1), 'SoundFont routing')
        chunk = (ct.c_float * 65536)()
        parts = []
        maximum = round((cycle_seconds * 6 + 30) * SAMPLE_RATE) * 2
        samples = 0
        while True:
            count = data(stream, chunk, ct.sizeof(chunk))
            if count == 0xFFFFFFFF:
                if error() != 45:  # BASS_ERROR_ENDED
                    raise RuntimeError(f'BASS decoding failed, error {error()}')
                break
            if count == 0:
                break
            if count % 8:
                raise ValueError('BASS output is not stereo float PCM')
            values = np.ctypeslib.as_array(chunk)[:count // 4].copy()
            parts.append(values)
            samples += len(values)
            if samples > maximum:
                raise ValueError('BASS output exceeds the bounded render duration')
        if not parts:
            raise ValueError('BASS produced no audio')
        presets = []
        for channel in range(16):
            selection = Font()
            if get_preset(stream, channel, ct.byref(selection)):
                if selection.font != font:
                    raise ValueError('A preset used a SoundFont outside the requested bank')
                presets.append({'channel': channel, 'preset': selection.preset, 'bank': selection.bank})
        rendered = np.concatenate(parts).reshape(-1, 2).astype(np.float64)
        if not np.isfinite(rendered).all():
            raise ValueError('BASS produced nonfinite samples')
        loop, details = process_steady_cycle(rendered, SAMPLE_RATE, cycle_seconds)
        write_pcm24_wave(destination, loop)
        details['engine'] = {
            'name': 'BASSMIDI', 'bass_version_hex': hex(core_version()),
            'bassmidi_version_hex': hex(midi_version()), 'interpolation': 'sinc',
            'effects': 'engine defaults', 'intermediate_format': 'float32',
            'presets': presets,
        }
        return details
    finally:
        if stream:
            stream_free(stream)
        if font:
            font_free(font)
        free()
