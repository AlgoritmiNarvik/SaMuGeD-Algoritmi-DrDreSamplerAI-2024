"""Build a level matched listening comparison from published loop MIDIs."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mido
from samuged.audio_loops import _render_audio, _optional_audio, _renderer_provenance
from scripts.render_bass_comparison import render_bass_audio


def repeat_cycle(source: Path, destination: Path, period_ticks: int, repetitions: int = 6):
    midi = mido.MidiFile(source)
    result = mido.MidiFile(type=1, ticks_per_beat=midi.ticks_per_beat)
    for track in midi.tracks:
        events = []
        tick = 0
        for message in track:
            tick += message.time
            if message.type != 'end_of_track':
                events.append((tick, message))
        if any(tick > period_ticks for tick, _ in events):
            raise ValueError('MIDI events extend beyond the declared cycle')
        out = mido.MidiTrack()
        previous = 0
        for repetition in range(repetitions):
            for tick, message in events:
                absolute = repetition * period_ticks + tick
                out.append(message.copy(time=absolute - previous))
                previous = absolute
        out.append(mido.MetaMessage('end_of_track', time=repetitions * period_ticks - previous))
        result.tracks.append(out)
    result.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--arachno', type=Path)
    parser.add_argument('--musescore', type=Path)
    parser.add_argument('--bass-runtime', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fluidsynth', type=Path, default=Path('/opt/homebrew/bin/fluidsynth'))
    parser.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    args = parser.parse_args()
    fluidsynth = args.fluidsynth
    ffmpeg = args.ffmpeg
    catalog = json.loads((args.space / 'catalog.json').read_text())
    selections = [('popular', 0), ('popular', 1), ('popular', 3), ('familiar', 1), ('motifs', 1), ('drums', 1)]
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {'renderer': _renderer_provenance(fluidsynth, ffmpeg), 'banks': {}, 'entries': []}
    for name, bank in [('FluidR3 GM', args.baseline), ('GeneralUser GS 2.0.3', args.candidate)]:
        receipt['banks'][name] = hashlib.sha256(bank.read_bytes()).hexdigest()
    banks = [('a', 'FluidR3 GM', args.baseline), ('b', 'GeneralUser GS 2.0.3', args.candidate)]
    if args.arachno:
        banks.append(('c', 'Arachno SoundFont 1.0', args.arachno))
        receipt['banks']['Arachno SoundFont 1.0'] = hashlib.sha256(args.arachno.read_bytes()).hexdigest()
    if args.musescore:
        banks.append(('d', 'MuseScore General 0.2.0', args.musescore))
        receipt['banks']['MuseScore General 0.2.0'] = hashlib.sha256(args.musescore.read_bytes()).hexdigest()
    if args.bass_runtime:
        if not args.arachno:
            parser.error('--bass-runtime requires --arachno')
        banks.append(('e', 'BASSMIDI + Arachno 1.0', args.arachno))
        receipt['banks']['BASSMIDI + Arachno 1.0'] = hashlib.sha256(args.arachno.read_bytes()).hexdigest()
    cards = []
    for group, index in selections:
        row = catalog['groups'][group]['rows'][index]
        identifier = row.get('with_drums', row)['phrase_id']
        folder = args.space / 'audio' / identifier
        metadata = json.loads((folder / 'metadata.json').read_text())
        entry = {'title': row['title'], 'phrase_id': identifier, 'midi_sha256': hashlib.sha256((folder / 'loop.mid').read_bytes()).hexdigest(), 'renders': {}}
        players = []
        with tempfile.TemporaryDirectory() as temp:
            repeated = Path(temp) / 'repeated.mid'
            repeat_cycle(folder / 'loop.mid', repeated, metadata['period']['period_ticks'])
            for tag, name, bank in banks:
                wav = args.output / f'{identifier}-{tag}.wav'
                start = time.monotonic()
                if tag == 'e':
                    details = render_bass_audio(repeated, bank, args.bass_runtime, wav, metadata['cycle_seconds'])
                else:
                    details = _render_audio(repeated, bank, fluidsynth, wav, metadata['cycle_seconds'])
                _optional_audio(wav, make_mp3=False, make_flac=True, ffmpeg=ffmpeg)
                flac = wav.with_suffix('.flac')
                entry['renders'][name] = {'audio': details, 'render_seconds': round(time.monotonic() - start, 3), 'bytes': flac.stat().st_size, 'sha256': hashlib.sha256(flac.read_bytes()).hexdigest()}
                wav.unlink()
                players.append(f'<label>{name}<audio controls loop preload="none" src="{flac.name}"></audio></label>')
        receipt['entries'].append(entry)
        cards.append(f'<section><h2>{html.escape(row["title"])}</h2><p>{html.escape(row["artist"])} · {"With drums" if "with_drums" in row else "Source part"}</p>{"".join(players)}</section>')
        print(row['title'], flush=True)
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (args.output / 'index.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Instrument comparison | SaMuGeD Earworms</title><style>body{font:16px system-ui;background:#101012;color:#eee;max-width:900px;margin:32px auto;padding:0 20px}a{color:#b8a9ed}section{border:1px solid #35353c;padding:20px;margin:20px 0}h2{margin:0}p{color:#aaa}label{display:block;margin:16px 0}audio{display:block;width:100%;margin-top:8px}</style><a href="https://almazermilov-samuged-earworms.static.hf.space/index.html">Back to loop player</a><h1>Instrument comparison</h1><p>Same MIDI notes, tempo and instrument programs. All versions use 48 kHz stereo rendering and the same peak level. Different timbres can still feel louder. Playback loops at 50% volume. Playing a version stops the other players.</p><p>Full instrument banks and two MIDI engines. Arachno is the current listening reference. Engine effects differ. HALion is unavailable here because its engine and GM library are not installed.</p>''' + ''.join(cards) + '''<p><a href="https://github.com/mrbumpy409/GeneralUser-GS">GeneralUser GS by S. Christian Collins</a> · <a href="generaluser-license.txt">License</a> · <a href="https://www.arachnosoft.com/main/soundfont.php">Arachno by Maxime Abbey</a> · <a href="musescore-license.md">MuseScore General license</a> · <a href="https://www.un4seen.com/bass.html">BASSMIDI</a> · <a href="receipt.json">Render measurements</a></p><script>document.querySelectorAll('audio').forEach(a=>{a.volume=.5;a.addEventListener('play',()=>document.querySelectorAll('audio').forEach(b=>{if(a!==b)b.pause()}))})</script></html>''')

if __name__ == '__main__':
    main()
