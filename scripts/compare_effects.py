"""Add Colombo room auditions to an existing local sound bank comparison."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import (
    EFFECT_PROFILES, _optional_audio, _renderer_provenance, _sha256_file,
)
from scripts.compare_soundfonts import repeat_cycle, render_with_headroom


START = '<!-- Colombo effects start -->'
END = '<!-- Colombo effects end -->'
PROFILES = [
    ('dry', 'Dry', 'No reverb or chorus. A reference for the samples themselves.'),
    ('close_room', 'Close room', 'A small room with softer reflections. No chorus.'),
    ('warm_room', 'Warm room', 'More space with darker reflections. No chorus.'),
]


def add_auditions(page: str, content: str) -> str:
    """Replace the audition block on reruns, keeping the earlier bank players."""
    if START in page:
        before, rest = page.split(START, 1)
        _, after = rest.split(END, 1)
        page = before + after
    insertion = page.index('<section>')
    page = page[:insertion] + START + content + END + page[insertion:]
    return page.replace('Arachno is the current listening reference.',
                        'ColomboGMGS2 17.02 Vanilla is the selected bank.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--soundfont', type=Path, required=True)
    parser.add_argument('--fluidsynth', type=Path, default=Path('/opt/homebrew/bin/fluidsynth'))
    parser.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    args = parser.parse_args()
    existing = json.loads((args.comparison / 'receipt.json').read_text())
    bank_hash = _sha256_file(args.soundfont)
    bank_name = 'ColomboGMGS2 17.02 Vanilla'
    if existing['banks'].get(bank_name) != bank_hash:
        raise ValueError('Sound bank differs from the existing Colombo reference')
    receipt = {
        'bank': bank_name, 'bank_sha256': bank_hash,
        'renderer': _renderer_provenance(args.fluidsynth, args.ffmpeg),
        'profiles': EFFECT_PROFILES, 'entries': [],
    }
    cards = []
    for row in existing['entries']:
        identifier = row['phrase_id']
        folder = args.space / 'audio' / identifier
        source = folder / 'loop.mid'
        if _sha256_file(source) != row['midi_sha256']:
            raise ValueError(f'MIDI differs from the existing reference: {identifier}')
        reference = args.comparison / f'{identifier}-j.flac'
        if _sha256_file(reference) != row['renders'][bank_name]['sha256']:
            raise ValueError(f'Colombo reference audio differs: {identifier}')
        metadata = json.loads((folder / 'metadata.json').read_text())
        entry = {'title': row['title'], 'phrase_id': identifier,
                 'midi_sha256': row['midi_sha256'], 'renders': {}}
        players = [f'<label>Original Colombo<audio controls loop preload="none" src="{reference.name}"></audio></label>']
        with tempfile.TemporaryDirectory() as temporary:
            repeated = Path(temporary) / 'repeated.mid'
            repeat_cycle(source, repeated, metadata['period']['period_ticks'])
            for profile, label, description in PROFILES:
                wav = args.comparison / f'{identifier}-colombo-{profile}.wav'
                start = time.monotonic()
                details = render_with_headroom(
                    repeated, args.soundfont, args.fluidsynth, wav,
                    metadata['cycle_seconds'], effects_profile=profile,
                )
                _optional_audio(wav, make_mp3=False, make_flac=True, ffmpeg=args.ffmpeg)
                flac = wav.with_suffix('.flac')
                entry['renders'][profile] = {
                    'audio': details, 'render_seconds': round(time.monotonic() - start, 3),
                    'bytes': flac.stat().st_size, 'sha256': _sha256_file(flac),
                }
                wav.unlink()
                players.append(f'<label>{label}<small style="display:block;color:#aaa">{description}</small>'
                               f'<audio controls loop preload="none" src="{flac.name}"></audio></label>')
        receipt['entries'].append(entry)
        cards.append(f'<section><h3>{html.escape(row["title"])}</h3>{"".join(players)}</section>')
        print(row['title'], flush=True)
    (args.comparison / 'effects-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    content = ('<section id="colombo-rooms"><h2>Colombo room comparison</h2>'
               '<p>The selected bank with three effect settings. Original Colombo already uses reverb and chorus. '
               'The room versions remove chorus and soften the reflections. Same notes and timing, '
               '48 kHz stereo, 24 bit audio and the same peak level. Timbres can still feel louder.</p>'
               '<p>Try Schism first, then Iris and Thunderstruck. Reverb continues across the loop boundary. '
               'Playback loops at 50% volume. Playing a version stops the others. '
               'The Low Rider drum patch has almost no effect send, so its versions sound alike.</p>'
               + ''.join(cards) + '<a href="effects-receipt.json">Effect settings and measurements</a></section>')
    page = args.comparison / 'index.html'
    page.write_text(add_auditions(page.read_text(), content))


if __name__ == '__main__':
    main()
