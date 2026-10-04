"""Apply two explicit listening demo edits without changing corpus records."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import _sha256_file, _optional_audio, seconds_between, source_cycle_notes
from samuged.drums import drum_part
from samuged.midi import export_phrase, load_midi
from scripts.build_loop_space import _waveform
from scripts.compare_soundfonts import repeat_cycle, render_with_headroom
from scripts.render_source_layers import combine_aligned_tracks

YMCA = '6291316a16eee3dcbd3bbbf08a1fafe0'
YMCA_EDIT = 'ae09ebedccf5653b9ed2c1f0cb3879c4'
WANNABE = 'e50a558be2e523f0178f109a71e014af'
WANNABE_LEAD = '765b60067cd93cca0c3214d6a6267c25'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def replace_popular(rows, old_id, replacement):
    """Keep the listening slot, but retain the replacement's own recurrence count."""
    matches = [i for i, row in enumerate(rows) if row['phrase_id'] in (old_id, replacement['phrase_id'])]
    if len(matches) != 1:
        raise ValueError('Expected exactly one curated listening slot')
    index = matches[0]
    rows[index] = {**deepcopy(replacement), 'rank': rows[index]['rank']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('space', 'source-root', 'soundfont', 'familiar-manifest'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    root = args.space
    catalog, atlas = read(root / 'catalog.json'), read(root / 'atlas/analysis.json')
    original = read(root / 'audio' / YMCA / 'metadata.json')
    source = args.source_root / original['source_path']
    if _sha256_file(source) != original['source_sha256']:
        raise ValueError('Y.M.C.A. source hash changed')
    if _sha256_file(args.soundfont) != catalog['audio_renderer']['sha256']:
        raise ValueError('SoundFont differs from the published renderer')
    song = load_midi(source, recover_invalid_keys=True)
    part = next(p for p in song.parts if p.index == original['part']['index'])
    start, period = original['cycle_start_tick'], 8 * song.ticks_per_beat
    if start != 9184 or song.ticks_per_beat != 384:
        raise ValueError('Unexpected source timing')
    seconds = seconds_between(song, start, start + period)
    notes = source_cycle_notes(part, start, period)
    waves, entries = {}, []
    with tempfile.TemporaryDirectory(prefix='samuged-demo-') as temp:
        temp = Path(temp)
        drums = drum_part(song)
        export_phrase(song, drums, source_cycle_notes(drums, start, period), start, start + period, temp / 'drums.mid')
        for suffix in ('', '-with-drums'):
            pid = YMCA_EDIT + suffix
            folder = temp / pid
            folder.mkdir()
            export_phrase(song, part, notes, start, start + period, folder / 'loop.mid')
            if suffix:
                combine_aligned_tracks(folder / 'loop.mid', temp / 'drums.mid', folder / 'loop.mid')
            shutil.copyfile(root / 'audio' / YMCA / 'source.mid', folder / 'source.mid')
            repeat_cycle(folder / 'loop.mid', temp / 'repeated.mid', period)
            audio = render_with_headroom(temp / 'repeated.mid', args.soundfont, Path('/opt/homebrew/bin/fluidsynth'), folder / 'loop.wav', seconds, effects_profile='original')
            if audio['clipped_sample_count'] or audio['output_peak'] > .9:
                raise ValueError('Invalid rendered peak')
            waves[pid] = _waveform(folder / 'loop.wav')
            _optional_audio(folder / 'loop.wav', make_mp3=False, make_flac=True, ffmpeg=Path('/opt/homebrew/bin/ffmpeg'))
            (folder / 'loop.wav').unlink()
            metadata = deepcopy(original)
            metadata.update(phrase_id=pid, base_phrase_id=YMCA, cycle_end_tick=start + period,
                            cycle_seconds=seconds, audio=audio, audio_renderer=catalog['audio_renderer'])
            metadata['period'] = {'period_ticks': period, 'period_beats': 8,
                                  'policy': 'explicit_demo_eight_beat_boundary', 'supporting_difference_count': 0}
            metadata['demo_edit'] = {'original_phrase_id': YMCA, 'original_cycle_seconds': 16,
                'reason': 'The occurrence spacing included almost twelve seconds without melody.',
                'boundary_note': 'The final detector note release is clipped by two ticks (2.6 ms). The next attack lies outside this eight beat phrase.',
                'recurrence_count_policy': 'Counts refer to the original detected phrase, not an independent audit of this edited cycle.'}
            used = [*notes, *(source_cycle_notes(drums, start, period) if suffix else [])]
            metadata['source_note_count_used'] = len(used)
            metadata['source_notes_used'] = [dict(start_tick=n.start, end_tick=min(n.end, start + period),
                relative_start_tick=n.start-start, relative_end_tick=min(n.end-start, period),
                pitch=n.pitch, velocity=n.velocity) for n in used]
            metadata['source_export_policy'] = 'source.mid retains the detector excerpt. loop.mid uses an explicitly curated eight beat source window.'
            write(folder / 'metadata.json', metadata)
            artifacts = [dict(path=f'{pid}/{p.name}', sha256=_sha256_file(p), bytes=p.stat().st_size) for p in folder.iterdir()]
            write(folder / 'hashes.json', {'phrase_id': pid, 'artifacts': artifacts})
            shutil.copytree(folder, root / 'audio' / pid, dirs_exist_ok=True)
            entries.append({'phrase_id': pid, 'artifacts': artifacts})

    popular = catalog['groups']['popular']['rows']
    lead = next(r for r in catalog['groups']['familiar']['rows'] if r['phrase_id'] == WANNABE_LEAD)
    replace_popular(popular, WANNABE, lead)
    ymca = deepcopy(next(r for r in popular if r['phrase_id'] in (YMCA, YMCA_EDIT)))
    ymca.update(phrase_id=YMCA_EDIT, period_beats=8, cycle_seconds=seconds,
                period_method='explicit demo eight beat boundary', waveform=waves[YMCA_EDIT],
                rationale='Short source phrase selected for the listening demo. The former cycle followed recurrence spacing and included a long melodic gap.',
                evidence_statement='Demo boundary edit. Counts refer to the original detected phrase. No listener recognition labels.',
                with_drums={'phrase_id': YMCA_EDIT+'-with-drums', 'waveform': waves[YMCA_EDIT+'-with-drums']})
    replace_popular(popular, YMCA, ymca)
    # Analytics recurrence views stay unchanged. Only its curated Popular songs view follows the demo.
    originals = {r['phrase_id']: r for rows in atlas['views'].values() for r in rows}
    familiar = next(json.loads(line) for line in args.familiar_manifest.read_text().splitlines() if json.loads(line)['phrase_id'] == WANNABE_LEAD)
    for old, new in ((YMCA, ymca), (WANNABE, lead)):
        previous = originals.get(old) or originals[new['phrase_id']]
        row = deepcopy(previous)
        if old == WANNABE:
            for key in row:
                if key in familiar:
                    row[key] = familiar[key]
            row['duration_beats'] = (familiar['end_tick']-familiar['start_tick'])/familiar['ticks_per_beat']
        row.update(phrase_id=new['phrase_id'], occurrence_count=new['occurrence_count'], program=new['program'],
                   midi_file=f"../audio/{new['phrase_id']}/source.mid")
        replace_popular(atlas['views']['popular'], old, row)
        pid = new['phrase_id']
        loop = load_midi(root / 'audio' / pid / 'source.mid')
        ns = [n for p in loop.parts for n in p.notes]
        end = max(n.end for n in ns)
        atlas['snippets'][pid] = [dict(label='Detector excerpt', start_tick=0, end_tick=end,
            duration_beats=end/loop.ticks_per_beat, duration_seconds=seconds_between(loop, 0, end),
            notes=[dict(pitch=n.pitch, velocity=n.velocity, onset_beats=n.start/loop.ticks_per_beat,
                        duration_beats=(n.end-n.start)/loop.ticks_per_beat) for n in ns])]
        def binding(identifier):
            return dict(wav=f'../audio/{identifier}/loop.flac', flac=f'../audio/{identifier}/loop.flac', midi=f'../audio/{identifier}/loop.mid')
        atlas['audio'][pid] = {**binding(pid), 'cycle_seconds':new['cycle_seconds'], 'period_beats':new['period_beats'],
                               'program':new['program'], 'with_drums':binding(new['with_drums']['phrase_id']), 'default_mode':'paired'}
    from scripts.analyze_top_phrases import write_csv
    write_csv(root / 'atlas/top50_popular.csv', atlas['views']['popular'])
    write(root / 'catalog.json', catalog)
    write(root / 'atlas/analysis.json', atlas)
    write(root / 'rendering/demo_curation.json', {'version':'demo-curation-v1', 'entries':entries,
        'wannabe':{'previous':WANNABE, 'selected':WANNABE_LEAD},
        'claim':'Only listening defaults and demo cycle formatting changed. Corpus and recurrence rankings are unchanged.'})


if __name__ == '__main__':
    main()
