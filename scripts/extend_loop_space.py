"""Add corpus expansion tabs to a built listening Space without touching its existing loops.

`select` ranks the published expansion phrases of one corpus by within source occurrence count under the
same structural filter as the Lakh motif view and writes a selection file with the phrase IDs to render.
`build` copies a built Space, binds the renders of `scripts/render_audio_loops.py` for those selections,
re-renders their audio with the Space's current SoundFont and effect profile, appends one catalog group
per selection and regenerates the page, the card and the rendering receipts. Audio stays outside the
Space: the FLAC files are collected in a separate folder for the audio repository and the catalog keeps
pointing at a pinned audio base URL.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import glob
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import EFFECT_PROFILES, _optional_audio, _renderer_provenance, _sha256_file, seconds_between
from samuged.midi import load_midi
from scripts.build_loop_space import _waveform
from scripts.build_player_notes import occurrence_windows, recurrence_records
from scripts.compare_soundfonts import render_with_headroom, repeat_cycle
from scripts.make_review import script_safe_json

SELECTION_VERSION = 'samuged-expansion-selection-v1'
MIN_NOTES, MIN_PITCHES, MIN_BEATS = 8, 4, 4.0
CORPORA = {
    'pdmx': {
        'config': 'pdmx_melodic',
        'title': 'PDMX scores',
        'description': ('Fifty recurring melodic phrases from the PDMX public domain score collection, one per title, '
                        'ranked by repetition inside the score. Counts measure within score repetition, not popularity.'),
        'license': 'CC BY 4.0 with Public Domain Mark or CC0 declarations on every score',
        'tempo_label': 'BPM at cycle start',
    },
    'maestro': {
        'config': 'maestro_melodic',
        'title': 'MAESTRO performances',
        'description': ('Fifty recurring melodic phrases from MAESTRO piano performances, one per title, ranked by '
                        'repetition inside the performance. Performances are recorded in real time without a tempo map, '
                        'so cycles follow the player and not a grid.'),
        'license': 'CC BY NC SA 4.0, noncommercial use only',
        'tempo_label': 'nominal BPM, no tempo map',
    },
}


def _json(path: Path):
    return json.loads(path.read_text())


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def structural(row: dict) -> bool:
    """The Lakh motif view rule: at least eight notes, four distinct pitches and four quarter note beats."""
    pitches = row['pitches'] if isinstance(row['pitches'], list) else json.loads(row['pitches'])
    return (row['note_count'] >= MIN_NOTES and len(set(pitches)) >= MIN_PITCHES
            and float(row['duration_beats']) >= MIN_BEATS)


def rank_rows(rows, limit: int) -> list[dict]:
    """Order by occurrence count, duration, note count and recurrence score, one phrase per artist and title."""
    ordered = sorted((r for r in rows if structural(r)),
                     key=lambda r: (-int(r['occurrence_count']), -float(r['duration_beats']), -int(r['note_count']),
                                    -float(r['recurrence_score']), r['phrase_id']))
    seen, chosen = set(), []
    for row in ordered:
        key = ((row.get('artist') or '').strip().lower(), (row.get('title') or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        chosen.append(row)
        if len(chosen) == limit:
            break
    return chosen


def select(corpus: str, parquet_dir: Path, output: Path, limit: int = 50) -> dict:
    import pyarrow.parquet as pq
    spec = CORPORA[corpus]
    columns = ['phrase_id', 'source_id', 'source_path', 'source_sha256', 'artist', 'title', 'kind', 'note_count',
               'occurrence_count', 'duration_beats', 'recurrence_score', 'pitches', 'program']
    files = sorted(glob.glob(str(parquet_dir / spec['config'] / '*.parquet')))
    if not files:
        raise ValueError(f'no parquet files for {spec["config"]} under {parquet_dir}')
    rows = []
    for file in files:
        rows.extend(pq.read_table(file, columns=columns).to_pylist())
    chosen = rank_rows(rows, limit)
    selection = {
        'version': SELECTION_VERSION, 'corpus': corpus, 'config': spec['config'], 'limit': limit,
        'rule': {'min_notes': MIN_NOTES, 'min_distinct_pitches': MIN_PITCHES, 'min_beats': MIN_BEATS,
                 'order': 'occurrence_count, duration_beats, note_count, recurrence_score, phrase_id',
                 'one_per': 'normalized artist and title'},
        'inputs': {Path(f).name: _sha256_file(Path(f)) for f in files},
        'phrase_rows_considered': len(rows),
        'candidates': [{'rank': i, 'phrase_id': r['phrase_id'], 'source_id': r['source_id'],
                        'source_path': r['source_path'], 'source_sha256': r['source_sha256'],
                        'artist': r['artist'] or '', 'title': r['title'] or '', 'kind': r['kind'],
                        'occurrence_count': int(r['occurrence_count']), 'note_count': int(r['note_count']),
                        'duration_beats': float(r['duration_beats']), 'program': r['program']}
                       for i, r in enumerate(chosen, 1)],
        'identity_verified': False, 'rights_clearance': 'not_established',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(output, selection)
    return selection


def _copy_render(render_root: Path, entry: dict, folder: Path) -> None:
    """Copy the verified loop MIDI, source MIDI and metadata of one rendered phrase."""
    for artifact in entry['artifacts']:
        path = render_root / artifact['path']
        if not path.resolve().is_relative_to(render_root.resolve()) or _sha256_file(path) != artifact['sha256']:
            raise ValueError(f'render artifact hash mismatch or path escape: {artifact["path"]}')
    folder.mkdir(parents=True)
    for name in ('loop.mid', 'source.mid', 'metadata.json'):
        shutil.copyfile(render_root / entry['phrase_id'] / name, folder / name)


def _rerender(folder: Path, bank: dict, soundfont: Path, fluidsynth: Path, ffmpeg: Path, flac_out: Path) -> tuple[dict, list]:
    """Render the loop MIDI with the Space bank, like scripts/rerender_loop_space.py, and move the FLAC aside."""
    metadata = _json(folder / 'metadata.json')
    with tempfile.TemporaryDirectory() as temp:
        repeated = Path(temp) / 'repeated.mid'
        repeat_cycle(folder / 'loop.mid', repeated, metadata['period']['period_ticks'])
        wav = folder / 'loop.wav'
        details = render_with_headroom(repeated, soundfont, fluidsynth, wav, metadata['cycle_seconds'],
                                       effects_profile=bank['effects_profile'])
        if details['frame_count'] != metadata['audio']['frame_count']:
            raise ValueError(f'cycle frame count changed: {folder.name}')
        if details['clipped_sample_count'] or details['output_peak'] > 0.9:
            raise ValueError(f'invalid audio peak: {folder.name}')
        waveform = _waveform(wav)
        _optional_audio(wav, make_mp3=False, make_flac=True, ffmpeg=ffmpeg)
        wav.unlink()
    metadata['audio'] = details
    metadata['audio_renderer'] = bank
    _write(folder / 'metadata.json', metadata)
    flac = folder / 'loop.flac'
    flac_out.mkdir(parents=True)
    shutil.move(str(flac), flac_out / 'loop.flac')
    artifacts = [{'path': f'{folder.name}/{p.name}', 'bytes': p.stat().st_size, 'sha256': _sha256_file(p)}
                 for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'hashes.json']
    artifacts.append({'path': f'{folder.name}/loop.flac', 'bytes': (flac_out / 'loop.flac').stat().st_size,
                      'sha256': _sha256_file(flac_out / 'loop.flac'), 'location': 'audio repository'})
    _write(folder / 'hashes.json', {'phrase_id': folder.name, 'artifacts': artifacts})
    return metadata, waveform


def catalog_row(rank: int, candidate: dict, metadata: dict, waveform: list, spec: dict) -> dict:
    tempo = metadata['tempo_changes'][0]['microseconds_per_beat']
    period = metadata['period']
    return {
        'rank': rank, 'phrase_id': candidate['phrase_id'], 'artist': candidate['artist'] or '',
        'title': candidate['title'], 'song_title': candidate['title'], 'kind': candidate['kind'],
        'source_path': candidate['source_path'], 'occurrence_count': candidate['occurrence_count'],
        'period_beats': period['period_beats'], 'cycle_seconds': metadata['cycle_seconds'], 'bpm': 60_000_000 / tempo,
        'tempo_label': spec['tempo_label'], 'program': metadata['part']['program'],
        'period_method': period['policy'].replace('_', ' '),
        'rationale': 'Selected by within source occurrence count under the motif filter, then rebuilt from source part notes over a complete cycle.',
        'evidence_statement': 'Structural recurrence in the saved score or performance. No listener labels, no identity or rights claim.',
        'evidence_urls': [], 'search_limited': False, 'curation_truncated': False,
        'waveform': waveform, 'featured': False, 'default_layer': 'solo',
    }


def _note_views(root: Path, rows: list[dict], source_roots: list[Path], manifests: list[Path]) -> int:
    """Write note views for the new phrases only and merge them into the existing notes index."""
    out = root / 'notes'
    out.mkdir(exist_ok=True)
    index_path = out / 'index.json'
    index = _json(index_path) if index_path.exists() else {}
    records = recurrence_records(manifests)
    songs, durations = {}, {}

    def packed(song):
        ticks = {0, *(n.start for p in song.parts for n in p.notes), *(n.end for p in song.parts for n in p.notes)}
        times = {t: round(seconds_between(song, 0, t), 5) if t else 0 for t in ticks}
        return [[times[n.start], times[n.end], n.pitch, n.velocity, int(p.is_drum), p.index]
                for p in song.parts for n in p.notes]
    for row in rows:
        pid = row['phrase_id']
        meta = _json(root / 'audio' / pid / 'metadata.json')
        digest = meta['source_sha256']
        if digest not in songs:
            candidates = [r / meta['source_path'] for r in source_roots]
            path = next((p for p in candidates if p.is_file() and _sha256_file(p) == digest), None)
            if path is None:
                raise ValueError(f"Verified source not found: {meta['source_path']}")
            song = load_midi(path, recover_invalid_keys=True)
            notes = packed(song)
            songs[digest] = song
            durations[digest] = max((n[1] for n in notes), default=0)
            (out / f'{digest}.json').write_text(json.dumps(
                {'notes': notes, 'duration': durations[digest],
                 'parts': [{'index': p.index, 'name': p.name, 'drum': p.is_drum} for p in song.parts]},
                separators=(',', ':')))
        song = songs[digest]
        variants = {'solo': packed(load_midi(root / 'audio' / pid / 'loop.mid'))}
        start, end = meta['cycle_start_tick'], meta['cycle_end_tick']
        payload = {'song': digest, 'part': meta['part']['index'], 'drum': meta['part']['is_drum'],
                   'start': seconds_between(song, 0, start) if start else 0,
                   'end': seconds_between(song, 0, end), 'variants': variants,
                   'source_duration': durations[digest],
                   'repeats': occurrence_windows(records.get(pid), song, meta),
                   'repeat_method': 'saved_detector_occurrences',
                   'beat_grid': [[round(seconds_between(song, start, t), 5) if t > start else 0,
                                  round((t - start) / song.ticks_per_beat, 3)]
                                 for t in range(start, end + 1, max(1, song.ticks_per_beat // 2))]}
        (out / f'{pid}.json').write_text(json.dumps(payload, separators=(',', ':')))
        items = [i for i in index.get(digest, []) if i['phrase_id'] != pid]
        items.append({'phrase_id': pid, 'start': payload['start'], 'end': payload['end'],
                      'label': meta['part']['name'] or 'Melody', 'kind': row['kind'],
                      'note_count': len(variants['solo']), 'scopes': ['main']})
        items.sort(key=lambda item: (item['start'], item['kind'], item['phrase_id']))
        index[digest] = items
    index_path.write_text(json.dumps(index, separators=(',', ':')))
    return len(rows)


def build(space: Path, output: Path, audio_output: Path, selections: list[Path], renders: list[Path], *,
          soundfont: Path, bank_name: str, audio_base_url: str, fluidsynth: Path, ffmpeg: Path,
          source_roots: list[Path], manifests: list[Path], workers: int = 2) -> dict:
    if output.exists() or audio_output.exists():
        raise FileExistsError('output folders must not exist')
    if output.resolve().is_relative_to(space.resolve()):
        raise ValueError('output must be outside the input Space')
    if not selections or not renders:
        raise ValueError('at least one selection and one render folder are required')
    catalog = _json(space / 'catalog.json')
    bank = dict(catalog['audio_renderer'])
    if bank['name'] != bank_name or bank['sha256'] != _sha256_file(soundfont):
        raise ValueError('the SoundFont differs from the bank recorded in the Space catalog')
    if bank['effects_profile'] not in EFFECT_PROFILES:
        raise ValueError('unknown effect profile in the Space catalog')
    shutil.copytree(space, output, ignore=shutil.ignore_patterns('.git'))
    audio_output.mkdir(parents=True)
    existing = {r['phrase_id'] for g in catalog['groups'].values() for r in g['rows']}
    entries = {}  # phrase id -> (render root, manifest entry), pooled over every render folder
    for index, render_root in enumerate(renders):
        manifest = _json(render_root / 'manifest.json')
        for entry in manifest['entries']:
            if entry['phrase_id'] in entries:
                raise ValueError(f'phrase rendered twice: {entry["phrase_id"]}')
            entries[entry['phrase_id']] = (render_root, entry)
        for name in ('manifest.json', 'receipt.json'):
            shutil.copyfile(render_root / name, output / 'rendering' / f'expansion_render_{index:02d}_{name}')
    receipt_entries, new_rows, groups_added, seen = [], [], {}, set()
    for selection_path in selections:
        selection = _json(selection_path)
        spec = CORPORA[selection['corpus']]
        jobs = []
        for candidate in selection['candidates']:
            pid = candidate['phrase_id']
            if pid in existing or pid in seen:
                raise ValueError(f'phrase already present in the Space: {pid}')
            seen.add(pid)
            if pid not in entries:
                raise ValueError(f'phrase not rendered: {pid}')
            folder = output / 'audio' / pid
            if folder.exists():
                raise ValueError(f'audio folder already exists: {pid}')
            render_root, entry = entries[pid]
            _copy_render(render_root, entry, folder)
            metadata = _json(folder / 'metadata.json')
            if metadata['source_sha256'] != candidate['source_sha256']:
                raise ValueError(f'render source differs from the selection: {pid}')
            jobs.append((candidate, folder))

        def work(job):
            candidate, folder = job
            metadata, waveform = _rerender(folder, bank, soundfont, fluidsynth, ffmpeg, audio_output / 'audio' / folder.name)
            return candidate, metadata, waveform
        rows = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for candidate, metadata, waveform in pool.map(work, jobs):
                rows.append(catalog_row(candidate['rank'], candidate, metadata, waveform, spec))
                receipt_entries.append({'phrase_id': candidate['phrase_id'], 'corpus': selection['corpus'],
                                        'artifacts': _json(output / 'audio' / candidate['phrase_id'] / 'hashes.json')['artifacts'],
                                        'audio': metadata['audio']})
        rows.sort(key=lambda r: r['rank'])
        key = selection['corpus']
        groups_added[key] = {'title': spec['title'], 'description': spec['description'], 'license': spec['license'], 'rows': rows}
        new_rows.extend(rows)
        shutil.copyfile(selection_path, output / 'rendering' / f'{key}_selection.json')
    # The page shows Popular first and then the remaining tabs alphabetically unless an order is given.
    shown = ['popular', *sorted(k for k in catalog['groups'] if k != 'popular')] if 'group_order' not in catalog else list(catalog['group_order'])
    catalog['group_order'] = [*(k for k in shown if k in catalog['groups']), *groups_added]
    catalog['groups'].update(groups_added)
    catalog['audio_base_url'] = audio_base_url.rstrip('/')
    _write(output / 'catalog.json', catalog)
    _page(output, catalog)
    for name in ('loop_explainer.js', 'player_notes.js', 'note_explorer.css', 'atlas_notes.js', 'loop_downloads.js'):
        (output / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    if source_roots:
        _note_views(output, new_rows, source_roots, manifests)
    receipt = {'version': 'samuged-expansion-tabs-v1', 'bank': bank,
               'renderer': _renderer_provenance(fluidsynth, ffmpeg), 'audio_base_url': catalog['audio_base_url'],
               'groups': {k: len(v['rows']) for k, v in groups_added.items()}, 'entries': receipt_entries,
               'identity_verified': False, 'rights_clearance': 'not_established'}
    _write(output / 'rendering' / 'expansion_tabs.json', receipt)
    _write(audio_output / 'rendering' / 'expansion_tabs.json', receipt)
    card(output / 'README.md', groups_added, len(new_rows))
    return catalog


def card(path: Path, groups: dict, loops: int) -> None:
    text = path.read_text()
    marker = '\n## Corpus expansion tabs\n'
    text = text.split(marker)[0].rstrip('\n') + '\n\n'
    text = text.replace('Three top 50 collections and ten familiar song selections',
                        'Five top 50 collections and ten familiar song selections')
    text = text.replace('The 630 lossless renders are served', f'The {630 + loops} lossless renders are served')
    lines = [marker.strip('\n'), '',
             f'{loops} loops come from the corpus expansion of the dataset, in the tabs '
             + ' and '.join(g['title'] for g in groups.values()) + '. '
             'They are ranked by repetition inside one score or performance under the same motif filter as the Lakh '
             'motifs, one phrase per title, and rebuilt from source notes over a complete cycle with the same bank. '
             'Counts are not popularity and the fragments have no listener labels. '
             'See rendering/expansion_tabs.json and the per corpus selection, manifest and receipt files.', '']
    for key, group in groups.items():
        lines.append(f'- {group["title"]}: {len(group["rows"])} loops, source license {group["license"]}.')
    lines.append('')
    lines.append('MAESTRO performances carry no tempo map, so the BPM shown for them is the nominal file tempo and '
                 'cycles follow the recorded timing. Identity of the underlying works is not verified and no rights '
                 'clearance is claimed for any corpus.')
    path.write_text(text + '\n'.join(lines) + '\n')


def playable_loops(space: Path) -> int:
    """Count audio folders whose hash receipt lists a rendered loop, wherever the FLAC is served from."""
    count = 0
    for hashes in (space / 'audio').glob('*/hashes.json'):
        if any(a['path'].endswith('/loop.flac') for a in _json(hashes)['artifacts']):
            count += 1
    return count


def _page(space: Path, catalog: dict) -> None:
    template = Path(__file__).with_name('loop_player.html').read_text()
    (space / 'index.html').write_text(template.replace('__CATALOG__', script_safe_json(catalog))
                                      .replace('<strong>40</strong>', f'<strong>{playable_loops(space)}</strong>'))


def pin(space: Path, audio_base_url: str) -> dict:
    """Point a built Space at the audio repository commit that holds its FLAC files, after that upload."""
    catalog = _json(space / 'catalog.json')
    catalog['audio_base_url'] = audio_base_url.rstrip('/')
    _write(space / 'catalog.json', catalog)
    _page(space, catalog)
    receipt_path = space / 'rendering' / 'expansion_tabs.json'
    if receipt_path.exists():
        receipt = _json(receipt_path)
        receipt['audio_base_url'] = catalog['audio_base_url']
        _write(receipt_path, receipt)
    return catalog


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pin_parser = commands.add_parser('pin', help='rewrite the audio base URL of a built Space')
    pin_parser.add_argument('--space', type=Path, required=True)
    pin_parser.add_argument('--audio-base-url', required=True)
    sel = commands.add_parser('select', help='rank the expansion phrases of one corpus')
    sel.add_argument('--corpus', choices=sorted(CORPORA), required=True)
    sel.add_argument('--parquet-dir', type=Path, required=True, help='folder with <config>/*.parquet')
    sel.add_argument('--output', type=Path, required=True)
    sel.add_argument('--limit', type=int, default=50)
    bld = commands.add_parser('build', help='append expansion tabs to a built Space')
    bld.add_argument('--space', type=Path, required=True)
    bld.add_argument('--output', type=Path, required=True)
    bld.add_argument('--audio-output', type=Path, required=True, help='folder of FLAC files for the audio repository')
    bld.add_argument('--selection', type=Path, action='append', required=True)
    bld.add_argument('--render', type=Path, action='append', required=True)
    bld.add_argument('--soundfont', type=Path, required=True)
    bld.add_argument('--bank-name', required=True)
    bld.add_argument('--audio-base-url', required=True)
    bld.add_argument('--source-root', type=Path, action='append', default=[])
    bld.add_argument('--phrase-manifest', type=Path, action='append', default=[])
    bld.add_argument('--workers', type=int, default=2)
    bld.add_argument('--fluidsynth', type=Path, default=Path('/opt/homebrew/bin/fluidsynth'))
    bld.add_argument('--ffmpeg', type=Path, default=Path('/opt/homebrew/bin/ffmpeg'))
    args = parser.parse_args(argv)
    if args.command == 'pin':
        catalog = pin(args.space, args.audio_base_url)
        print(json.dumps({'audio_base_url': catalog['audio_base_url']}))
        return
    if args.command == 'select':
        selection = select(args.corpus, args.parquet_dir, args.output, limit=args.limit)
        print(json.dumps({'corpus': args.corpus, 'candidates': len(selection['candidates']),
                          'considered': selection['phrase_rows_considered']}))
        return
    if args.workers < 1 or args.workers > 4:
        parser.error('--workers must be between 1 and 4')
    catalog = build(args.space, args.output, args.audio_output, args.selection, args.render, soundfont=args.soundfont,
                    bank_name=args.bank_name, audio_base_url=args.audio_base_url, fluidsynth=args.fluidsynth,
                    ffmpeg=args.ffmpeg, source_roots=args.source_root, manifests=args.phrase_manifest,
                    workers=args.workers)
    print({key: len(value['rows']) for key, value in catalog['groups'].items()})


if __name__ == '__main__':
    main()
