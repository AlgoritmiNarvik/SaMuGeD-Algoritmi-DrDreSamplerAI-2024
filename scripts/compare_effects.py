"""Compare Arachno and Colombo with identical global effect profiles."""
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


PROFILES = [
    ('original', 'Original', 'Default reverb and chorus from the earlier bank auditions.'),
    ('close_room', 'Close room', 'A small room with softer reflections. No chorus.'),
    ('warm_room', 'Warm room', 'More space with darker reflections. No chorus.'),
    ('dry', 'Dry', 'No global reverb or chorus. Hear the samples themselves.'),
]
BANK_NAMES = {'arachno': 'Arachno SoundFont 1.0', 'colombo': 'ColomboGMGS2 17.02 Vanilla'}


def build_page(entries: list[dict]) -> str:
    options = []
    cards = []
    for index, entry in enumerate(entries):
        title = html.escape(entry['title'])
        options.append(f'<option value="{index}">{title}</option>')
        rows = []
        for profile, label, description in PROFILES:
            players = []
            for bank, name in BANK_NAMES.items():
                filename = html.escape(entry['renders'][bank][profile]['file'], quote=True)
                players.append(f'<div><h3>{name}</h3><audio aria-label="{title}, {name}, {label}" '
                               f'controls loop preload="none" src="{filename}"></audio></div>')
            rows.append(f'<div class="profile" data-profile="{profile}" hidden>'
                        f'<p>{description}</p><div class="banks">{"".join(players)}</div></div>')
        cards.append(f'<section data-phrase="{index}" hidden><h2>{title}</h2>{"".join(rows)}</section>')
    profiles = ''.join(f'<option value="{key}">{label}</option>' for key, label, _ in PROFILES)
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arachno and Colombo | SaMuGeD Earworms</title><style>
body{font:16px system-ui;background:#101012;color:#eee;max-width:960px;margin:32px auto;padding:0 20px}
a{color:#b8a9ed}h1{font-size:28px}h2{margin-top:0}h3{font-size:16px;font-weight:500}
p{color:#aaa;line-height:1.5}section{border:1px solid #35353c;padding:20px;margin:24px 0}
.choices{display:flex;gap:20px;flex-wrap:wrap}label{display:grid;gap:8px}
select{font:inherit;color:#eee;background:#1a1a1e;border:1px solid #45454e;padding:10px;max-width:100%}
.banks{display:grid;grid-template-columns:1fr 1fr;gap:24px}audio{display:block;width:100%}
@media(max-width:640px){.banks{grid-template-columns:1fr}body{padding:0 12px}.choices label{width:100%}}
[hidden]{display:none!important}</style></head><body>
<a href="https://almazermilov-samuged-earworms.static.hf.space/index.html">Back to loop player</a>
<h1>Arachno and Colombo</h1>
<p>Choose one universal bank. Compare the same phrase and effect profile on both sides.
Iris is the piano example. Schism covers bass with drums.</p>
<p>Same MIDI, 48 kHz stereo and 24 bit audio. All versions have the same peak level,
but perceived volume can differ. Playback loops at 50% volume. Playing a version stops the other.</p>
<div class="choices"><label>Phrase<select id="phrase">''' + ''.join(options) + '''</select></label>
<label>Effects<select id="profile">''' + profiles + '''</select></label></div>
''' + ''.join(cards) + '''
<p>Room effects keep the original notes, timing, velocities and programs. They add space,
but cannot replace the character of a piano sample. Effect sends vary by patch,
so some drums barely respond to these settings.</p>
<p><a href="https://www.arachnosoft.com/main/soundfont.php">Arachno by Maxime Abbey</a> ·
<a href="https://sourceforge.net/projects/colombogmgs2-sf2/">ColomboGMGS2 by Tharii314</a> ·
<a href="effects-receipt.json">Settings and render measurements</a></p>
<script>
const phrase=document.getElementById('phrase'), profile=document.getElementById('profile');
const players=Array.from(document.querySelectorAll('audio'));
players.forEach(a=>{a.volume=.5;a.addEventListener('play',()=>players.forEach(b=>{if(a!==b)b.pause()}))});
function select(){
  players.forEach(a=>a.pause());
  document.querySelectorAll('[data-phrase]').forEach(s=>s.hidden=s.dataset.phrase!==phrase.value);
  document.querySelectorAll('[data-profile]').forEach(s=>s.hidden=s.dataset.profile!==profile.value);
}
phrase.addEventListener('change',select);profile.addEventListener('change',select);select();
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--soundfont', type=Path, required=True, help='Colombo Vanilla SF2')
    parser.add_argument('--arachno', type=Path, required=True)
    parser.add_argument('--fluidsynth', type=Path, default=Path('/opt/homebrew/bin/fluidsynth'))
    parser.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    args = parser.parse_args()
    existing = json.loads((args.comparison / 'receipt.json').read_text())
    banks = [('arachno', args.arachno, 'c'), ('colombo', args.soundfont, 'j')]
    receipt = {'banks': {}, 'renderer': _renderer_provenance(args.fluidsynth, args.ffmpeg),
               'profiles': EFFECT_PROFILES, 'entries': []}
    for bank, path, _ in banks:
        bank_hash = _sha256_file(path)
        if existing['banks'].get(BANK_NAMES[bank]) != bank_hash:
            raise ValueError(f'Sound bank differs from the existing reference: {bank}')
        receipt['banks'][BANK_NAMES[bank]] = bank_hash
    # Put the disputed piano phrase first, keeping the other instrument examples.
    entries = sorted(existing['entries'], key=lambda row: row['title'] != 'Iris')
    for row in entries:
        identifier = row['phrase_id']
        folder = args.space / 'audio' / identifier
        source = folder / 'loop.mid'
        if _sha256_file(source) != row['midi_sha256']:
            raise ValueError(f'MIDI differs from the existing reference: {identifier}')
        metadata = json.loads((folder / 'metadata.json').read_text())
        entry = {'title': row['title'], 'phrase_id': identifier,
                 'midi_sha256': row['midi_sha256'], 'renders': {}}
        with tempfile.TemporaryDirectory() as temporary:
            repeated = Path(temporary) / 'repeated.mid'
            repeat_cycle(source, repeated, metadata['period']['period_ticks'])
            for bank, soundfont, tag in banks:
                reference = args.comparison / f'{identifier}-{tag}.flac'
                original = row['renders'][BANK_NAMES[bank]]
                if _sha256_file(reference) != original['sha256']:
                    raise ValueError(f'Reference audio differs: {identifier}, {bank}')
                entry['renders'][bank] = {'original': {**original, 'file': reference.name}}
                for profile, _, _ in PROFILES[1:]:
                    wav = args.comparison / f'{identifier}-{bank}-{profile}.wav'
                    start = time.monotonic()
                    details = render_with_headroom(
                        repeated, soundfont, args.fluidsynth, wav,
                        metadata['cycle_seconds'], effects_profile=profile,
                    )
                    _optional_audio(wav, make_mp3=False, make_flac=True, ffmpeg=args.ffmpeg)
                    flac = wav.with_suffix('.flac')
                    entry['renders'][bank][profile] = {
                        'file': flac.name, 'audio': details,
                        'render_seconds': round(time.monotonic() - start, 3),
                        'bytes': flac.stat().st_size, 'sha256': _sha256_file(flac),
                    }
                    wav.unlink()
        receipt['entries'].append(entry)
        print(row['title'], flush=True)
    (args.comparison / 'effects-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (args.comparison / 'index.html').write_text(build_page(receipt['entries']))


if __name__ == '__main__':
    main()
