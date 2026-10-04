"""Revise a built Space's instrument audio without changing its loop MIDIs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import (
    EFFECT_PROFILES, _optional_audio, _renderer_provenance, _sha256_file,
)
from scripts.build_loop_space import _waveform
from scripts.compare_soundfonts import repeat_cycle, render_with_headroom


def update_waveforms(value, waveforms):
    if isinstance(value, dict):
        if 'waveform' in value and value.get('phrase_id') in waveforms:
            value['waveform'] = waveforms[value['phrase_id']]
        for child in value.values():
            update_waveforms(child, waveforms)
    elif isinstance(value, list):
        for child in value:
            update_waveforms(child, waveforms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--soundfont', type=Path, required=True)
    parser.add_argument('--bank-name', required=True)
    parser.add_argument('--license', type=Path, required=True)
    parser.add_argument('--profile', choices=EFFECT_PROFILES, default='original')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--fluidsynth', type=Path, default=Path('/opt/homebrew/bin/fluidsynth'))
    parser.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 4:
        parser.error('--workers must be between 1 and 4')
    if args.output.resolve().is_relative_to(args.space.resolve()):
        parser.error('output must be outside the input Space')
    bank = {'name': args.bank_name, 'sha256': _sha256_file(args.soundfont),
            'effects_profile': args.profile, 'effects_settings': EFFECT_PROFILES[args.profile]}
    shutil.copytree(args.space, args.output)
    shutil.copyfile(args.license, args.output / 'soundfont-license.txt')
    card = args.output / 'README.md'
    text = card.read_text()
    text = text.replace('The authentic FluidR3 GM SoundFont was used with FluidSynth.',
                        f'Audio uses {args.bank_name} with FluidSynth and the {args.profile} effect profile.')
    card.write_text(text)
    (args.output / 'rendering/previous-soundfont-license.txt').write_bytes((args.space / 'soundfont-license.txt').read_bytes())
    folders = sorted((args.output / 'audio').iterdir())

    def render(folder):
        metadata_path = folder / 'metadata.json'
        metadata = json.loads(metadata_path.read_text())
        original_midi_hash = _sha256_file(folder / 'loop.mid')
        previous = {name: _sha256_file(folder / name)
                    for name in ('loop.mid', 'source.mid', 'loop.flac', 'metadata.json') if (folder / name).exists()}
        with tempfile.TemporaryDirectory() as temp:
            repeated = Path(temp) / 'repeated.mid'
            repeat_cycle(folder / 'loop.mid', repeated, metadata['period']['period_ticks'])
            wav = folder / 'loop.wav'
            details = render_with_headroom(repeated, args.soundfont, args.fluidsynth, wav,
                                           metadata['cycle_seconds'], effects_profile=args.profile)
            if details['frame_count'] != metadata['audio']['frame_count']:
                raise ValueError(f'cycle frame count changed: {folder.name}')
            if details['clipped_sample_count'] or details['output_peak'] > 0.9:
                raise ValueError(f'invalid audio peak: {folder.name}')
            waveform = _waveform(wav)
            _optional_audio(wav, make_mp3=False, make_flac=True, ffmpeg=args.ffmpeg)
            wav_hash = _sha256_file(wav)
            wav.unlink()
        if original_midi_hash != _sha256_file(folder / 'loop.mid'):
            raise ValueError(f'loop MIDI changed: {folder.name}')
        metadata['audio'] = details
        metadata['audio_renderer'] = bank
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
        artifacts = [{'path': f'{folder.name}/{p.name}', 'bytes': p.stat().st_size, 'sha256': _sha256_file(p)}
                     for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'hashes.json']
        (folder / 'hashes.json').write_text(json.dumps({'phrase_id': folder.name, 'artifacts': artifacts}, indent=2) + '\n')
        return {'phrase_id': folder.name, 'previous': previous, 'artifacts': artifacts,
                'canonical_wav_sha256': wav_hash, 'audio': details}, waveform

    entries, waveforms = [], {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, (entry, waveform) in enumerate(pool.map(render, folders), 1):
            entries.append(entry)
            waveforms[entry['phrase_id']] = waveform
            if index % 25 == 0 or index == len(folders):
                print(f'Rendered {index}/{len(folders)}', flush=True)
    catalog = json.loads((args.output / 'catalog.json').read_text())
    update_waveforms(catalog, waveforms)
    catalog['audio_renderer'] = bank
    (args.output / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    receipt = {'version': 'samuged-audio-revision-v1', 'bank': bank,
               'renderer': _renderer_provenance(args.fluidsynth, args.ffmpeg),
               'previous_receipts': 'Earlier rendering manifests describe the previous audio revision.',
               'entries': entries}
    (args.output / 'rendering/audio_revision.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Finished {len(entries)} loops', flush=True)


if __name__ == '__main__':
    main()
