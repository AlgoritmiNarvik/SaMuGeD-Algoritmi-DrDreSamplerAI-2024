import hashlib
import json

import pytest

from scripts.select_tool_motifs import select


def write_dataset(path, rows):
    manifest = path / 'phrases.jsonl'
    manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    sources = {row['source_id']: {
        'source_id': row['source_id'], 'search_limited': True,
        'curation_truncated': True,
    } for row in rows}
    (path / 'sources.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in sources.values()))
    return manifest


def row(pid, *, artist='Tool', kind='melodic', count=5, program=33):
    return {
        'phrase_id': pid, 'source_id': pid, 'source_path': artist + '/song.mid',
        'artist_from_path': artist, 'title_from_path': 'song', 'song_key': 'song',
        'kind': kind, 'occurrence_count': count, 'duration_beats': 8,
        'note_count': 12, 'recurrence_score': 0.9, 'program': program,
        'part_name': 'Bass', 'pitches': [40, 42, 40],
    }


def test_selects_one_per_song_and_kind_with_bass_and_source_limits(tmp_path):
    manifest = write_dataset(tmp_path, [row('weak'), row('best', count=9),
        row('drum', kind='percussion', count=7), row('other', artist='A Perfect Circle', count=90)])
    result = select(tmp_path)
    assert [r['phrase_id'] for r in result['candidates']] == ['best', 'drum']
    assert result['source_paths'] == 1
    assert all(r['search_limited'] and r['curation_truncated'] for r in result['candidates'])
    assert result['phrase_manifest_sha256'] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert select(tmp_path) == result


def test_matches_exact_artist_name_ignoring_case_and_outer_space(tmp_path):
    write_dataset(tmp_path, [row('wanted', artist=' TOOL '), row('unwanted', artist='Tool tribute', count=99)])
    assert [r['phrase_id'] for r in select(tmp_path)['candidates']] == ['wanted']


def test_empty_tool_collection_is_explicit(tmp_path):
    write_dataset(tmp_path, [row('other', artist='Other')])
    with pytest.raises(ValueError, match='no Tool phrases'):
        select(tmp_path)


def test_preserves_contrasting_phrases_and_caps_each_kind(tmp_path):
    rows = []
    for i in range(5):
        r = row(str(i), count=20-i)
        r['pitches'] = [40, 42+i, 40]
        rows.append(r)
    rows.append({**rows[0], 'phrase_id': 'duplicate', 'source_id': 'duplicate', 'occurrence_count': 1})
    write_dataset(tmp_path, rows)
    assert [r['phrase_id'] for r in select(tmp_path)['candidates']] == ['0', '1', '2']
    assert [r['phrase_id'] for r in select(tmp_path, melodic_per_song=2)['candidates']] == ['0', '1']
