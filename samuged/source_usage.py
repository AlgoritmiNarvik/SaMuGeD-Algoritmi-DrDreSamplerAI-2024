"""Per source declared usage terms and exact PDMX score evidence, not rights clearance."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile

from .catalog_search import connect
from .dataset import file_digest

POLICY_VERSION = 'declared-source-terms-v1'
LICENSE_URLS = {
    'CC-BY-4.0': 'https://creativecommons.org/licenses/by/4.0/',
    'CC-BY-NC-SA-4.0': 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
}
SCORE_URLS = {
    'publicdomain': 'https://creativecommons.org/publicdomain/mark/1.0/',
    'cc0': 'https://creativecommons.org/publicdomain/zero/1.0/',
}


def source_path(value):
    """Use the full archive path, never a title, basename or best arrangement."""
    value = value.removeprefix('./')
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts:
        raise ValueError('invalid score path')
    return str(path)


def load_scores(path):
    scores = {}
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        required = {'mid', 'metadata', 'license', 'license_url', 'license_conflict',
                    'subset:no_license_conflict', 'subset:all_valid'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('missing PDMX rights fields')
        for row in reader:
            if row['mid'] in {'', 'NA'}:
                continue
            key = source_path(row['mid'])
            if key in scores:
                raise ValueError('ambiguous MIDI path in score metadata')
            # Keep relevant evidence only, without lyrics or personal contact data.
            fields = required | {'path', 'is_original', 'is_official', 'publisher'}
            scores[key] = {k: row.get(k) for k in sorted(fields)}
    return scores


def assess(record, score=None, *, csv_sha256=None):
    license_id = record['dataset_license']
    recognized = license_id in LICENSE_URLS and bool(record['evidence_url'])
    research = redistribution = 'conditional_declared' if recognized else 'unresolved'
    commercial = ('restricted_declared' if license_id == 'CC-BY-NC-SA-4.0'
                  else 'conditional_declared' if recognized else 'unresolved')
    conditions = list(json.loads(record['conditions_json']))
    if recognized:
        conditions += ['Retain attribution, copyright and license notices',
                       'Link the license and describe changes',
                       'Do not add restrictions prohibited by the license']
    conditions += ['These statuses describe declared source terms only',
                   'Composition, arrangement and performance clearance is not established',
                   'Research means noncommercial research here. No legal exception is inferred']
    evidence = {'dataset_url': record['evidence_url'], 'dataset_license': license_id,
                'dataset_license_url': LICENSE_URLS.get(license_id),
                'scope': 'declared corpus terms, not a grant from all song rights holders',
                'policy_version': POLICY_VERSION}
    score_status = 'not_applicable'
    score_id = score_path = None
    if record['dataset_id'] == 'pdmx':
        score_status = 'incomplete'
        if score:
            score_path = score.get('metadata')
            match = re.fullmatch(r'\./metadata/\d+/(\d+)\.json', score_path or '')
            score_id = match.group(1) if match else None
            evidence['score'] = dict(score, csv_sha256=csv_sha256,
                                     match_method='exact_full_MIDI_archive_path',
                                     score_page_verified=False)
            conflict = (score.get('license_conflict') == 'True'
                        or score.get('subset:no_license_conflict') == 'False'
                        or score.get('license') != record['score_license_declaration']
                        or score.get('license_url') != record['score_license_url'])
            if conflict:
                score_status = 'conflict'
            elif (score.get('license_conflict') == 'False'
                  and score.get('subset:no_license_conflict') == 'True'
                  and score.get('subset:all_valid') == 'True'
                  and SCORE_URLS.get(score.get('license')) == score.get('license_url')
                  and score.get('license') in SCORE_URLS and score_id):
                score_status = 'declaration_consistent'
            if score.get('license') == 'publicdomain':
                conditions += ['Public Domain Mark identifies a claim. It is not a copyright license']
            conditions += ['Check the underlying work, arrangement and applicable jurisdiction']
        if score_status != 'declaration_consistent':
            research = redistribution = commercial = 'unresolved'
    return dict(research_terms_status=research, redistribution_terms_status=redistribution,
                commercial_terms_status=commercial, overall_clearance_status='not_established',
                score_review_status=score_status, source_score_id=score_id,
                score_metadata_path=score_path, usage_conditions=conditions, usage_evidence=evidence)


def prepare(metadata: Path, catalog: Path, output: Path, *, pdmx_csv: Path | None = None):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 12 * 1024**3:
        raise ValueError('insufficient storage reserve')
    hashes = {'metadata_sha256': file_digest(metadata), 'catalog_sha256': file_digest(catalog),
              'pdmx_csv_sha256': file_digest(pdmx_csv) if pdmx_csv else None}
    scores = load_scores(pdmx_csv) if pdmx_csv else {}
    source = connect(catalog, timeout=60)
    try:
        with tempfile.TemporaryDirectory(prefix='samuged-usage-', dir=output.parent) as tmp:
            target = Path(tmp) / 'usage.sqlite'
            shutil.copyfile(metadata, target)
            db = sqlite3.connect(target)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('PRAGMA max_page_count=524288')
                if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('unsupported metadata index')
                if db.execute('SELECT catalog_sha256 FROM provenance').fetchone()[0] != hashes['catalog_sha256']:
                    raise ValueError('metadata belongs to another catalog')
                db.executescript('''
                CREATE TABLE source_usage(source_key TEXT PRIMARY KEY REFERENCES records,
                 research_terms_status TEXT NOT NULL,redistribution_terms_status TEXT NOT NULL,
                 commercial_terms_status TEXT NOT NULL,overall_clearance_status TEXT NOT NULL,
                 score_review_status TEXT NOT NULL,source_score_id TEXT,score_metadata_path TEXT,
                 usage_conditions_json TEXT NOT NULL,usage_evidence_json TEXT NOT NULL,
                 usage_reviewed_on TEXT NOT NULL);
                CREATE INDEX usage_commercial ON source_usage(commercial_terms_status);
                CREATE INDEX usage_score ON source_usage(score_review_status);
                ''')
                count = 0
                counts = Counter()
                date = datetime.now(timezone.utc).date().isoformat()
                for src in source.execute('SELECT source_key,source_path,source_sha256 FROM sources ORDER BY source_key'):
                    record = db.execute('SELECT * FROM records WHERE source_key=?', (src['source_key'],)).fetchone()
                    if record is None:
                        raise ValueError('source coverage differs')
                    if record['source_sha256'] != src['source_sha256']:
                        raise ValueError('source hash differs from catalog')
                    score = scores.get(source_path(src['source_path'])) if record['dataset_id'] == 'pdmx' else None
                    result = assess(record, score, csv_sha256=hashes['pdmx_csv_sha256'])
                    values = (src['source_key'], *(result[k] for k in ('research_terms_status',
                        'redistribution_terms_status', 'commercial_terms_status', 'overall_clearance_status',
                        'score_review_status', 'source_score_id', 'score_metadata_path')),
                        json.dumps(result['usage_conditions'], ensure_ascii=False),
                        json.dumps(result['usage_evidence'], ensure_ascii=False), date)
                    db.execute('INSERT INTO source_usage VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
                    counts[(record['dataset_id'], result['commercial_terms_status'], result['score_review_status'])] += 1
                    count += 1
                if db.execute('SELECT count(*) FROM records').fetchone()[0] != count:
                    raise ValueError('incomplete usage coverage')
                db.commit()
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('usage index integrity failed')
                if (file_digest(metadata) != hashes['metadata_sha256']
                    or file_digest(catalog) != hashes['catalog_sha256']
                    or (pdmx_csv and file_digest(pdmx_csv) != hashes['pdmx_csv_sha256'])):
                    raise ValueError('input changed during annotation')
                db.close()
                os.link(target, output)
                return dict(source_records=count, policy_version=POLICY_VERSION, inputs=hashes,
                            sha256=file_digest(output), bytes=output.stat().st_size, published=False,
                            all_rights_clearance='not_established', counts=[dict(dataset=d,
                                commercial_terms_status=c, score_review_status=s, records=n)
                                for (d, c, s), n in sorted(counts.items())])
            finally:
                db.close()
    finally:
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('metadata', 'catalog', 'output', 'pdmx-csv'):
        parser.add_argument('--'+name, type=Path, required=name != 'pdmx-csv')
    args = parser.parse_args()
    print(json.dumps(prepare(args.metadata, args.catalog, args.output, pdmx_csv=args.pdmx_csv), indent=2))


if __name__ == '__main__':
    main()
