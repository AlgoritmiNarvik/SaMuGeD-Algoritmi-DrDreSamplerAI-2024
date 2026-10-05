"""Read only coverage and duplicate candidate review for corpus catalogs."""
from __future__ import annotations

from pathlib import Path

from .catalog_search import connect
from .dataset import file_digest


def _duplicates(db, column, limit):
    # Column names are internal constants. Source values remain bound parameters.
    assert column in {'source_sha256', 'musical_sha256'}
    groups = f'''WITH groups AS (
        SELECT s.{column} AS fingerprint, count(*) AS source_records,
               count(DISTINCT b.dataset_id) AS corpus_count,
               count(DISTINCT CASE WHEN s.split IN ('train','validation','test')
                                   THEN s.split END) AS evaluation_split_count
        FROM sources s JOIN builds b USING(build_id)
        WHERE s.{column} IS NOT NULL AND trim(s.{column})<>''
        GROUP BY s.{column} HAVING count(*)>1)'''
    counts = dict(db.execute(groups + ''' SELECT count(*) AS candidate_groups,
        coalesce(sum(source_records),0) AS source_records_in_groups,
        coalesce(sum(corpus_count>1),0) AS cross_corpus_groups,
        coalesce(sum(evaluation_split_count>1),0) AS evaluation_split_conflict_groups
        FROM groups''').fetchone())
    examples = []
    for row in db.execute(groups + ''' SELECT * FROM groups
        ORDER BY evaluation_split_count DESC,corpus_count DESC,source_records DESC,fingerprint
        LIMIT ?''', (limit,)):
        group = dict(row)
        group['members'] = [dict(member) for member in db.execute(f'''
            SELECT s.source_key,b.dataset_id,s.source_id,s.split
            FROM sources s JOIN builds b USING(build_id)
            WHERE s.{column}=? ORDER BY b.dataset_id,s.source_key LIMIT 8''',
            (row['fingerprint'],))]
        group['members_truncated'] = row['source_records'] > len(group['members'])
        examples.append(group)
    return {**counts, 'examples': examples, 'examples_truncated': counts['candidate_groups'] > len(examples)}


def review(path: Path, *, sample_limit=20):
    """Describe recorded evidence without assigning splits, dropping sources or clearing rights."""
    if type(sample_limit) is not int or not 0 <= sample_limit <= 100:
        raise ValueError('sample limit must be between 0 and 100')
    before = file_digest(path)
    db = connect(path, timeout=60)
    try:
        db.execute('BEGIN')
        corpora = [dict(row) for row in db.execute('''SELECT b.dataset_id,
            count(*) AS source_records,
            sum(p.source_key IS NOT NULL) AS sources_with_phrases,
            sum(s.status='error') AS error_sources,
            sum(s.warning_count>0) AS sources_with_warnings,
            sum(s.repair_count>0) AS sources_with_repairs,
            sum(s.search_limited<>0) AS search_limited_sources,
            sum(s.curation_truncated<>0) AS curation_truncated_sources,
            sum(s.source_sha256 IS NULL OR trim(s.source_sha256)='') AS missing_byte_hash,
            sum(s.musical_sha256 IS NULL OR trim(s.musical_sha256)='') AS missing_arrangement_hash,
            sum(s.title IS NULL OR trim(s.title)='') AS missing_title,
            sum(s.artist IS NULL OR trim(s.artist)='') AS missing_artist,
            sum(s.split IS NULL OR s.split NOT IN ('train','validation','test')) AS sources_without_evaluation_split
            FROM sources s JOIN builds b USING(build_id)
            LEFT JOIN (SELECT DISTINCT source_key FROM phrases) p USING(source_key)
            GROUP BY b.dataset_id ORDER BY b.dataset_id''')]
        coverage = [dict(row) for row in db.execute('''SELECT b.dataset_id,a.category,
            count(DISTINCT a.source_key) AS labeled_sources,count(DISTINCT a.value) AS distinct_values
            FROM annotations a JOIN sources s USING(source_key) JOIN builds b USING(build_id)
            GROUP BY b.dataset_id,a.category ORDER BY b.dataset_id,a.category''')]
        phrases = [dict(row) for row in db.execute('''SELECT dataset_id,kind,count(*) AS phrase_records,
            min(duration_beats) AS min_duration_beats,max(duration_beats) AS max_duration_beats,
            min(occurrence_count) AS min_occurrences,max(occurrence_count) AS max_occurrences
            FROM phrase_catalog GROUP BY dataset_id,kind ORDER BY dataset_id,kind''')]
        statuses = [dict(row) for row in db.execute('''SELECT b.dataset_id,s.status,count(*) AS source_records
            FROM sources s JOIN builds b USING(build_id) GROUP BY b.dataset_id,s.status
            ORDER BY b.dataset_id,s.status''')]
        rights = [dict(row) for row in db.execute('''SELECT dataset_id,dataset_license,
            composition_rights,redistribution_status,conditions_json,evidence_json FROM datasets ORDER BY dataset_id''')]
        import json
        for row in rights:
            row['conditions'] = json.loads(row.pop('conditions_json'))
            row['evidence'] = json.loads(row.pop('evidence_json'))
        duplicates = {'matching_bytes': _duplicates(db, 'source_sha256', sample_limit),
                      'matching_normalized_arrangement': _duplicates(db, 'musical_sha256', sample_limit)}
    finally:
        db.close()
    if file_digest(path) != before:
        raise ValueError('catalog changed during review')
    return {'report_version': 1, 'catalog_sha256': before, 'corpora': corpora,
            'source_statuses': statuses, 'annotation_coverage': coverage, 'phrases': phrases,
            'rights_evidence': rights, 'duplicate_candidates': duplicates,
            'limitations': [
                'Counts describe build specific source records, not unique songs.',
                'Duplicate candidate counts overlap between methods and must not be added.',
                'Normalized arrangement equality is a candidate signal, not verified song identity.',
                'No approximate cross corpus similarity search is performed by this report.',
                'Zero recorded split conflicts does not establish an independent evaluation split.',
                'Rights evidence and source declarations do not grant reuse permission.',
                'Warning and search limit counts are not perceptual accuracy measurements.'],
            'splits_changed': False, 'sources_removed': False, 'published': False}
