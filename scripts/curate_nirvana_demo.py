"""Curate source derived Nirvana examples after Schism in the listening demo."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

SELECTIONS = (
    ('044359a0ce87afd9cfa2b171def3d12c', 'Rape Me'),
    ('be7da8e7e2decd51301810d204e62045', 'Heart-Shaped Box'),
    ('817bda73231323a5bac9e453707eeb52', 'In Bloom'),
    ('7265fb138040beb357543311779b8f1a', 'About a Girl'),
    ('4026827db9dc945f4837c939825665ff', 'Come As You Are'),
    ('37d33f1bc65d2e2d9ad9faa0e3b7e16a', 'Lithium'),
)


def curate(catalog):
    candidates = {r['phrase_id']: r for r in catalog.get('song_variants', [])}
    candidates.update({r['phrase_id']: r for r in catalog['groups']['popular']['rows']})
    ids = {pid for pid, _ in SELECTIONS}
    original = [r for r in catalog['groups']['popular']['rows'] if r['phrase_id'] not in ids and r['title'] != 'Smells Like Teen Spirit']
    if not original or original[0]['title'] != 'Schism':
        raise ValueError('Preserve Schism as the opening selection')
    selected = []
    for pid, title in SELECTIONS:
        row = deepcopy(candidates[pid])
        if row['kind'] != 'melodic' or not row.get('with_drums'):
            raise ValueError('Selected examples must include melody and source drum versions')
        row.update(title=title, song_title=title, artist='Nirvana',
                   rationale='Selected Nirvana example for the listening collection. Source notes and MIDI program are retained. Position is editorial, not a popularity score.')
        selected.append(row)
    rows = [original[0], *selected, *original[1:]]
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    catalog['groups']['popular']['rows'] = rows
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space', type=Path, required=True)
    args = parser.parse_args()
    path = args.space / 'catalog.json'
    catalog = curate(json.loads(path.read_text()))
    path.write_text(json.dumps(catalog, indent=2) + '\n')
    receipt = dict(selections=[dict(phrase_id=pid, title=title) for pid, title in SELECTIONS],
                   policy='Listening demo only. Existing entries remain. Corpus and analytics rankings are unchanged.')
    (args.space / 'rendering/nirvana_selection.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
