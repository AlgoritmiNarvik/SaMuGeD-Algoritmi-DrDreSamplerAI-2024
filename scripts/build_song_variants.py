"""Render saved detector candidates for songs already present in the demo.

Defaults and corpus records stay unchanged. Additional cycles use explicit
whole bar formatting of the detected window, not distance between occurrences.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samuged.audio_loops import _sha256_file, _part_for_row, _optional_audio, infer_loop_period, active_meter, seconds_between, source_cycle_notes
from samuged.drums import drum_part
from samuged.midi import export_phrase, load_midi
from scripts.build_loop_space import _waveform
from scripts.compare_soundfonts import repeat_cycle, render_with_headroom
from scripts.render_source_layers import combine_aligned_tracks


def phrase_period(row, meter):
    # Deliberately omit recurrence spacing from this formatting decision.
    window = {**row, 'occurrences':[{'start_tick':row['start_tick'], 'end_tick':row['end_tick']}]}
    return infer_loop_period(window, meter=meter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('space', 'dataset', 'source-root', 'soundfont'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--include-source', action='append', default=[], help='Additional source path to prepare for demo curation')
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    root = args.space
    catalog = json.loads((root/'catalog.json').read_text())
    if _sha256_file(args.soundfont) != catalog['audio_renderer']['sha256']:
        raise ValueError('SoundFont must match the published renderer')
    current = {r['phrase_id']:r for g in catalog['groups'].values() for r in g['rows']}
    source_paths = {r['source_path'] for r in current.values()} | set(args.include_source)
    wanted = []
    for line in (args.dataset/'phrases.jsonl').open():
        row = json.loads(line)
        if row['source_path'] in source_paths and row['phrase_id'] not in current:
            wanted.append(row)
    @lru_cache(maxsize=200)
    def source(path, digest):
        full = args.source_root/path
        if _sha256_file(full) != digest:
            raise ValueError(f'Source hash changed: {path}')
        return load_midi(full, recover_invalid_keys=True)
    def render(row):
        pid = row['phrase_id']
        folder = root/'audio'/pid
        marker = folder/'demo_variant.json'
        # Resume completed renders after an interrupted build.
        if marker.exists():
            saved = json.loads(marker.read_text())
            for identifier in [pid, saved.get('with_drums',{}).get('phrase_id')]:
                if identifier and not (root/'audio'/identifier/'loop.flac').is_file():
                    raise ValueError('Incomplete cached variant')
            return saved
        song = source(row['source_path'], row['source_sha256'])
        published = args.dataset/row['midi_path']
        if _sha256_file(published) != row['midi_sha256']:
            raise ValueError('Detector MIDI hash changed')
        # Existing exports remain intact. Their metadata describes their cycle policy.
        if (folder/'loop.flac').exists():
            meta = json.loads((folder/'metadata.json').read_text())
            import subprocess
            with tempfile.TemporaryDirectory() as tmp:
                wav = Path(tmp)/'existing.wav'
                subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-i',str(folder/'loop.flac'),'-c:a','pcm_s24le','-ar','48000','-ac','2',str(wav)],check=True)
                wave = _waveform(wav)
            period_ticks, duration = meta['period']['period_ticks'], meta['cycle_seconds']
            program, policy = meta['part']['program'], meta['period']['policy']
            paired = None
        else:
            part = _part_for_row(song, row)
            start = row['start_tick']
            period = phrase_period(row, active_meter(song, start))
            period_ticks, policy = period.period_ticks, period.policy
            duration = seconds_between(song, start, start+period_ticks)
            program = part.program
            drums = drum_part(song)
            drum_notes = source_cycle_notes(drums, start, period_ticks)
            paired = None
            with tempfile.TemporaryDirectory(prefix='samuged-variant-') as tmp:
                tmp = Path(tmp)
                if not part.is_drum and drum_notes:
                    export_phrase(song, drums, drum_notes, start, start+period_ticks, tmp/'drums.mid')
                for suffix in ('', '-with-drums') if not part.is_drum and drum_notes else ('',):
                    identifier = pid+suffix
                    output = tmp/identifier
                    output.mkdir()
                    notes = source_cycle_notes(part, start, period_ticks)
                    export_phrase(song, part, notes, start, start+period_ticks, output/'loop.mid')
                    if suffix:
                        combine_aligned_tracks(output/'loop.mid', tmp/'drums.mid', output/'loop.mid')
                    shutil.copyfile(published, output/'source.mid')
                    repeat_cycle(output/'loop.mid', tmp/'repeated.mid', period_ticks)
                    details = render_with_headroom(tmp/'repeated.mid', args.soundfont, Path('/opt/homebrew/bin/fluidsynth'), output/'loop.wav', duration, effects_profile='original')
                    if details['clipped_sample_count'] or details['output_peak']>.9:
                        raise ValueError('Invalid rendered audio')
                    waveform = _waveform(output/'loop.wav')
                    _optional_audio(output/'loop.wav', make_mp3=False, make_flac=True, ffmpeg=Path('/opt/homebrew/bin/ffmpeg'))
                    (output/'loop.wav').unlink()
                    meta = dict(phrase_id=identifier, kind=row['kind'], source_path=row['source_path'], source_sha256=row['source_sha256'],
                        published_phrase_midi_sha256=row['midi_sha256'], cycle_start_tick=start, cycle_end_tick=start+period_ticks,
                        cycle_seconds=duration, period=asdict(period), part=dict(index=part.index, track=part.track, channel=part.channel,
                        program=part.program, name=part.name, is_drum=part.is_drum), audio=details, audio_renderer=catalog['audio_renderer'],
                        source_export_policy='Detector source.mid is unchanged. The demo cycle uses source notes with whole bar padding of the detected window.',
                        recognition_claim=False, demo_formatting=True)
                    (output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
                    artifacts=[dict(path=f'{identifier}/{p.name}',bytes=p.stat().st_size,sha256=_sha256_file(p)) for p in output.iterdir()]
                    (output/'hashes.json').write_text(json.dumps({'phrase_id':identifier,'artifacts':artifacts},indent=2)+'\n')
                    shutil.copytree(output,root/'audio'/identifier,dirs_exist_ok=True)
                    if suffix:
                        paired={'phrase_id':identifier,'waveform':waveform}
                    else:
                        wave=waveform
        item=dict(rank=row['rank_in_file'], phrase_id=pid, artist=row['artist_from_path'].replace('_',' '),
            title=row['title_from_path'].replace('_',' '), song_title=row['title_from_path'].replace('_',' '), kind=row['kind'],
            source_path=row['source_path'], occurrence_count=row['occurrence_count'], cycle_seconds=duration,
            period_beats=period_ticks/song.ticks_per_beat, bpm=60/(seconds_between(song,row['start_tick'],row['start_tick']+song.ticks_per_beat)),
            program=program, period_method=policy.replace('_',' '), waveform=wave, rationale='Additional saved detector candidate from the same source MIDI.',
            evidence_statement='Counts describe the saved detector phrase. Demo cycles use source notes and explicit loop formatting. No listener labels.',
            evidence_urls=[], search_limited=False, curation_truncated=True)
        if paired:
            item['with_drums']=paired
        marker.write_text(json.dumps(item,indent=2)+'\n')
        return item
    variants=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, item in enumerate(pool.map(render,wanted),1):
            variants.append(item)
            if i%20==0 or i==len(wanted):
                print(f'Prepared {i}/{len(wanted)} additional phrases',flush=True)
    catalog['song_variants']=variants
    (root/'catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    (root/'rendering/song_variants.json').write_text(json.dumps({'phrase_ids':[r['phrase_id'] for r in variants],
        'policy':'Saved detector candidates for existing demo sources. Defaults remain unchanged. Additional cycles use whole bar formatting.'},indent=2)+'\n')


if __name__=='__main__':
    main()
