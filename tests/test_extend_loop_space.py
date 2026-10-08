import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.extend_loop_space import CORPORA, card, catalog_row, rank_rows, select, structural


def phrase(pid, *, occ=5, beats=8.0, notes=12, pitches=(60, 62, 64, 65), score=0.9, artist='A', title='T'):
    return {'phrase_id': pid, 'source_id': 's-' + pid, 'source_path': f'mid/{pid}.mid', 'source_sha256': '0' * 64,
            'artist': artist, 'title': title, 'kind': 'melodic', 'note_count': notes, 'occurrence_count': occ,
            'duration_beats': beats, 'recurrence_score': score, 'pitches': list(pitches) * (notes // len(pitches) + 1),
            'program': 0}


def test_structural_filter_matches_the_motif_rule():
    assert structural(phrase('a'))
    assert not structural(phrase('b', notes=7))
    assert not structural(phrase('c', pitches=(60, 62, 64)))
    assert not structural(phrase('d', beats=3.5))


def test_rank_rows_orders_by_occurrence_then_duration_and_keeps_one_per_title():
    rows = [phrase('low', occ=2, title='Low'), phrase('top', occ=9, beats=4.0), phrase('top-dup', occ=9, beats=8.0),
            phrase('other', occ=9, beats=8.0, title='Other'), phrase('tie', occ=9, beats=8.0, title='Tie', notes=8)]
    chosen = [r['phrase_id'] for r in rank_rows(rows, 10)]
    assert chosen == ['other', 'top-dup', 'tie', 'low']
    assert [r['phrase_id'] for r in rank_rows(rows, 2)] == ['other', 'top-dup']


def test_select_writes_a_bounded_selection_from_parquet(tmp_path):
    rows = [phrase('p1', occ=3, title='One'), phrase('p2', occ=7, title='Two'), phrase('p3', occ=1, notes=6, title='Three')]
    folder = tmp_path / 'data' / 'pdmx_melodic'
    folder.mkdir(parents=True)
    table = pa.Table.from_pylist([{**r, 'pitches': json.dumps(r['pitches'])} for r in rows])
    pq.write_table(table, folder / 'part-00000.parquet')
    selection = select('pdmx', tmp_path / 'data', tmp_path / 'sel.json', limit=5)
    assert [c['phrase_id'] for c in selection['candidates']] == ['p2', 'p1']
    assert selection['candidates'][0]['rank'] == 1
    assert selection['phrase_rows_considered'] == 3
    assert selection['rights_clearance'] == 'not_established'
    assert json.loads((tmp_path / 'sel.json').read_text())['config'] == 'pdmx_melodic'


def test_select_refuses_a_missing_configuration(tmp_path):
    with pytest.raises(ValueError):
        select('maestro', tmp_path, tmp_path / 'sel.json')


def test_catalog_row_carries_the_corpus_tempo_label():
    metadata = {'tempo_changes': [{'microseconds_per_beat': 500_000}], 'period': {'period_beats': 8.0, 'policy': 'fallback_pad_phrase_to_whole_bars_at_start_meter'},
                'cycle_seconds': 4.0, 'part': {'program': 0}}
    candidate = {'phrase_id': 'x', 'artist': '', 'title': 'Sonata', 'kind': 'melodic', 'source_path': '2004/a.midi', 'occurrence_count': 8}
    row = catalog_row(3, candidate, metadata, [0.1] * 96, CORPORA['maestro'])
    assert row['bpm'] == 120.0
    assert row['tempo_label'] == 'nominal BPM, no tempo map'
    assert row['period_method'] == 'fallback pad phrase to whole bars at start meter'
    assert row['rank'] == 3 and row['default_layer'] == 'solo'
    assert catalog_row(1, candidate, metadata, [], CORPORA['pdmx'])['tempo_label'] == 'BPM at cycle start'


def test_card_section_is_replaced_not_duplicated(tmp_path):
    path = tmp_path / 'README.md'
    path.write_text('---\ntitle: x\n---\n\n# Space\n\nBody.\n')
    groups = {'pdmx': {'title': 'PDMX scores', 'license': 'CC BY 4.0', 'rows': [1, 2]},
              'maestro': {'title': 'MAESTRO performances', 'license': 'CC BY NC SA 4.0, noncommercial use only', 'rows': [1]}}
    card(path, groups, 3)
    card(path, groups, 3)
    text = path.read_text()
    assert text.count('## Corpus expansion tabs') == 1
    assert 'Body.' in text
    assert '- MAESTRO performances: 1 loops, source license CC BY NC SA 4.0, noncommercial use only.' in text
    assert 'no tempo map' in text


def test_player_template_uses_the_row_tempo_label():
    template = (Path(__file__).resolve().parents[1] / 'scripts' / 'loop_player.html').read_text()
    assert "row.tempo_label||'BPM at cycle start'" in template


def test_player_template_honours_the_catalog_group_order():
    template = (Path(__file__).resolve().parents[1] / 'scripts' / 'loop_player.html').read_text()
    assert 'catalog.group_order' in template
