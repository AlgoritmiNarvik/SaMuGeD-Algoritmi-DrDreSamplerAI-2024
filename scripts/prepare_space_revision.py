"""Bind revised audio and a verified Schism note explainer to a built Space."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import _sha256_file, seconds_between
from samuged.midi import load_midi
from scripts.make_review import script_safe_json


def time_at(song, tick):
    return 0.0 if tick == 0 else seconds_between(song, 0, tick)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--demo-source', type=Path, required=True)
    parser.add_argument('--audio-base-url', required=True)
    args = parser.parse_args()
    root = args.space
    catalog = json.loads((root / 'catalog.json').read_text())
    row = catalog['groups']['popular']['rows'][0]
    if row['title'] != 'Schism' or row['artist'] != 'Tool':
        raise ValueError('The default example must be the curated Schism phrase')
    folder = root / 'audio' / row['phrase_id']
    metadata = json.loads((folder / 'metadata.json').read_text())
    if _sha256_file(args.demo_source) != metadata['source_sha256']:
        raise ValueError('Schism source MIDI differs from the extraction source')
    source = load_midi(args.demo_source)
    part = next(p for p in source.parts if p.index == metadata['part']['index']
                and p.channel == metadata['part']['channel'] and not p.is_drum)
    period = metadata['period']['period_ticks']
    start = metadata['cycle_start_tick']
    left, right = max(0, start - period), start + 3 * period
    selection = json.loads((root / 'rendering/schism_selection.json').read_text())
    selected = next(r for r in selection['candidates'] if r['phrase_id'] == row['phrase_id'])
    context_notes = [{'start': max(left, n.start) - left, 'end': min(right, n.end) - left,
                      'pitch': n.pitch, 'velocity': n.velocity,
                      'start_seconds': time_at(source, n.start) - time_at(source, start),
                      'end_seconds': time_at(source, n.end) - time_at(source, start)}
                     for n in part.notes if left <= n.start < right]
    loop = load_midi(folder / 'loop.mid')
    notes = [{'start': time_at(loop, n.start), 'end': time_at(loop, n.end),
              'pitch': n.pitch, 'velocity': n.velocity}
             for p in loop.parts if not p.is_drum for n in p.notes]
    paired_id = row['with_drums']['phrase_id']
    paired = load_midi(root / 'audio' / paired_id / 'loop.mid')
    drums = [{'start': time_at(paired, n.start), 'end': time_at(paired, n.end),
              'pitch': n.pitch, 'velocity': n.velocity}
             for p in paired.parts if p.is_drum for n in p.notes]
    demo = {'phrase_id': row['phrase_id'], 'paired_id': paired_id, 'title': 'Schism', 'artist': 'Tool',
            'source_sha256': metadata['source_sha256'], 'loop_midi_sha256': _sha256_file(folder / 'loop.mid'),
            'cycle_seconds': metadata['audio']['duration_seconds'], 'period_ticks': period,
            'context_ticks': right - left, 'selected_start_tick': start - left,
            'context_notes': context_notes, 'notes': notes, 'drums': drums,
            'repeats': [{'start': r['start'] - left, 'end': r['end'] - left}
                        for r in selected['occurrence_ticks'] if left <= r['start'] < right]}
    (root / 'explainer.json').write_text(json.dumps(demo, indent=2) + '\n')
    catalog['explainer'] = {'phrase_id': row['phrase_id'], 'paired_id': paired_id}
    catalog['audio_base_url'] = args.audio_base_url.rstrip('/')
    (root / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    template = Path(__file__).with_name('loop_player.html').read_text()
    count = len(list((root / 'audio').glob('*/loop.flac')))
    (root / 'index.html').write_text(template.replace('__CATALOG__', script_safe_json(catalog))
                                   .replace('<strong>40</strong>', f'<strong>{count}</strong>'))
    (root / 'loop_explainer.js').write_bytes(Path(__file__).with_name('loop_explainer.js').read_bytes())
    (root / 'player_notes.js').write_bytes(Path(__file__).with_name('player_notes.js').read_bytes())
    atlas = root / 'atlas'
    packet = json.loads((atlas / 'analysis.json').read_text())
    packet['audio_renderer'] = catalog['audio_renderer']
    for pid, binding in packet['audio'].items():
        for version in [binding, *(v for v in binding.values() if isinstance(v, dict))]:
            for field in ('wav', 'flac'):
                if field in version:
                    audio_id = Path(urlparse(version[field]).path).parent.name
                    if not (root / 'audio' / audio_id / 'loop.flac').is_file():
                        raise ValueError(f'Missing revised atlas audio: {audio_id}')
                    version[field] = f'{args.audio_base_url.rstrip("/")}/{audio_id}/loop.flac'
    (atlas / 'analysis.json').write_text(json.dumps(packet, indent=2, ensure_ascii=False) + '\n')
    (atlas / 'index.html').write_text(Path(__file__).with_name('top_phrases.html').read_text()
                                   .replace('__DATA__', script_safe_json(packet)))
    audio_receipt = json.loads((atlas / 'audio_receipt.json').read_text())
    audio_receipt['audio_revision'] = '../rendering/audio_revision.json'
    if 'bindings' in audio_receipt:
        audio_receipt['historical_bindings'] = audio_receipt.pop('bindings')
    audio_receipt['audio_base_url'] = args.audio_base_url
    (atlas / 'audio_receipt.json').write_text(json.dumps(audio_receipt, indent=2) + '\n')
    receipt = json.loads((atlas / 'receipt.json').read_text())
    receipt['outputs'] = {p.relative_to(atlas).as_posix(): {'bytes': p.stat().st_size, 'sha256': _sha256_file(p)}
                          for p in sorted(atlas.rglob('*')) if p.is_file() and p.name != 'receipt.json'}
    (atlas / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
