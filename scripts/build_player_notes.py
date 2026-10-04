"""Build source verified note views for the listening player, without changing audio."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.midi import load_midi
from samuged.audio_loops import _sha256_file, seconds_between


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, action='append', required=True)
    args = parser.parse_args()
    root = args.space
    catalog = json.loads((root / 'catalog.json').read_text())
    out = root / 'notes'
    out.mkdir(exist_ok=True)
    songs = {}
    rows = {r['phrase_id']: r for g in catalog['groups'].values() for r in g['rows']}
    def packed(song):
        ticks = {0, *(n.start for p in song.parts for n in p.notes), *(n.end for p in song.parts for n in p.notes)}
        times = {t: round(seconds_between(song, 0, t), 5) if t else 0 for t in ticks}
        return [[times[n.start], times[n.end], n.pitch, n.velocity, int(p.is_drum), p.index]
                for p in song.parts for n in p.notes]
    for pid, row in rows.items():
        folder = root / 'audio' / pid
        meta = json.loads((folder / 'metadata.json').read_text())
        digest = meta['source_sha256']
        if digest not in songs:
            candidates = [p / meta['source_path'] for p in args.source_root]
            path = next((p for p in candidates if p.is_file() and _sha256_file(p) == digest), None)
            if path is None:
                raise ValueError(f"Verified source not found: {meta['source_path']}")
            song = load_midi(path, recover_invalid_keys=True)
            notes = packed(song)
            songs[digest] = song
            payload = {'notes': notes, 'duration': max((n[1] for n in notes), default=0),
                       'parts': [{'index': p.index, 'name': p.name, 'drum': p.is_drum} for p in song.parts]}
            (out / f'{digest}.json').write_text(json.dumps(payload, separators=(',', ':')))
        song = songs[digest]
        variants = {key: packed(load_midi(root / 'audio' / rid / 'loop.mid'))
                    for key, rid in [('solo', pid), ('paired', row.get('with_drums', {}).get('phrase_id')),
                                     ('drums', row.get('drums_only', {}).get('phrase_id'))] if rid}
        start, end = meta['cycle_start_tick'], meta['cycle_end_tick']
        payload = {'song': digest, 'part': meta['part']['index'], 'drum': meta['part']['is_drum'],
                   'start': seconds_between(song, 0, start) if start else 0,
                   'end': seconds_between(song, 0, end), 'variants': variants}
        (out / f'{pid}.json').write_text(json.dumps(payload, separators=(',', ':')))
    (root / 'player_notes.js').write_bytes(Path(__file__).with_name('player_notes.js').read_bytes())
    print(f'Note views: {len(rows)} phrases, {len(songs)} verified source songs')


if __name__ == '__main__':
    main()
