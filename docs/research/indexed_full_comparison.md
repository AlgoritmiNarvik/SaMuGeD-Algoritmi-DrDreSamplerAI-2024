# Indexed full corpus comparison

## Scope and evidence boundary

This note compares the audited `aligned_indexed` full corpus build with the audited reference build. Both builds cover the same 17,232 input paths. Each audit requires full source coverage, reports zero failures and binds `sources.jsonl`, `phrases.jsonl`, `summary.json` and `build_config.json` by SHA256.

The comparison measures detector output differences. It does not measure musical quality, human preference, memorability or real corpus recall. Duplicate screening is heuristic and does not establish known duplicate truth.

| Artifact | SHA256 |
| --- | --- |
| Reference audit | `e89f8275936e2813f577ba42eaf092c930a8a7170bc7777fecd04dbac4e37ecf` |
| Indexed audit | `8936468ac01b79855edbb8c8d450fb888980c1ac8f1731d5215ea6d6117c765f` |
| Comparison aggregate | `c9008f7f5c5b39eed1ca90933c0daa82f5c27758f53e5609287d30562bee3dbe` |
| Comparison raw results | `c8c872fcd108a8eb051dc531cce5221833bf500e9e0771fa58c02470a9c24e39` |
| Comparison completion receipt | `d1982ef64cba8f844f0604a9eef9224d74f81b2c326bdc146bb27165e340f2dd` |
| Independent manifest check | `d882e98cd82a941240521233ca84186c84ae1495b78dfdbcb5d2d55067745f94` |

The completed comparison is in `research_local/indexed_full_comparison_v02`. Its source snapshot digest is `4ee1b11f1e7807df096ea5ae8757c08302b46142f25cef9f4fb34376834430c0`. The comparison script is the committed `f115a656f1a7f62304986d9eb4f99e9dc5cbcbdc` version, script SHA256 `f5c37a1a9eda1eea5e788b58277e775c4e7eb7cd5433ba7ee4073a9c41e5205b`.

## Full corpus output

| Measure | Reference | Indexed | Difference |
| --- | ---: | ---: | ---: |
| Parsed sources | 16,995 | 16,995 | 0 |
| Parse errors | 237 | 237 | 0 |
| Sources with a matched output | 16,892 | 16,923 | +31 |
| Sources with melodic phrases | 16,872 | 16,908 | +36 |
| Melodic phrases | 50,439 | 50,568 | +129 |
| Percussion phrases | 44,511 | 44,511 | 0 |
| Melodic search limited files | 700 | 3,843 | +3,143 |
| Percussion search or curation limited files | 2,339 | 2,339 | 0 |

Outcome transitions were 34 `no_match` to `matched`, 3 `matched` to `no_match`, 16,889 `matched` to `matched`, 69 `no_match` to `no_match` and 237 unchanged parse errors. The independent manifest check reproduced these counts.

The comparison reports full selected payload changes for melodic output in 16,911 sources. This comparison excludes only `phrase_id`, `midi_path` and `rank_in_file`. It retains scores, matcher flags, occurrence alignment and all musical fields. Therefore 16,911 is not a count of sources with changed notes or source coordinates. A content projection is needed to separate musical selection changes from method metadata changes.

Percussion has zero semantic payload changes and zero phrase count change. The independent check compared all 44,511 percussion rows after excluding the same three build identifier and rank fields and found zero changed sources. The comparison reports 73 percussion rank shifts because `rank_in_file` is shared across kinds and the melodic selection count changed. These are not percussion musical changes.

Observed build worker time was 7,544.239 seconds for reference and 49,793.215 seconds for indexed, a 6.60 ratio. Observed wall time was 3,782.876 and 12,465.966 seconds, a 3.30 ratio. These builds used different effective parallelism and ran amid other work, so wall time is not an isolated speed benchmark. The indexed build also reached its melodic search limits in 3,843 files, so it is not exhaustive.

## Descriptive curation diagnostics

`research_local/curation_indexed_v01` validates all 17,232 source rows and 95,079 phrase rows. Its completed aggregate SHA256 is `9ccceceeaa8e7dee1273a567a9e48d8d430591d7e0becf1c6568a112671d26a5`, raw result SHA256 is `1d535131d149642d2626b9bfd2a5bddfbd76d24fced07e7f6baa4ce2ce2e2c21` and completion receipt SHA256 is `58bd99c00dae406e9992d1a6fd946a445c6ef5aa6a2d0aacae334c676c31f523`.

The selected indexed melodic phrases are longer than the reference selections by the recorded summaries. Median note count changes from 12 to 19 and median duration from 7.896 to 12.625 beats. Median occurrence count changes from 8 to 7. Phrases with at most two distinct positive inter onset intervals change from 16,932 of 50,439 (33.57%) to 14,336 of 50,568 (28.35%). Sources whose selected melodic phrases all come from one part change from 4,128 of 16,872 (24.47%) to 5,153 of 16,908 (30.48%). These are descriptive selection properties. They do not show that either selection is musically better.

Percussion curation diagnostics are identical between builds. This agrees with the direct semantic comparison.

## Duplicate screening

The duplicate audit used the recovered fingerprint cache and the same settings as `duplicates_recovered_v01.json`: invalid key recovery enabled, maximum 20,000,000 generated pair events, 2,000,000 verified pairs and 400,000 reported candidates. The frozen script and fingerprint method hashes match the recovered run.

The indexed report at `research_local/duplicates_indexed_v01.json` has SHA256 `8716d41bc017cfe8b890e9dc7ac29d85c94b4452be43e195ccf4c43124c0ca09`. It records 16,995 cache hits, 7,649,316 generated pair events, 1,026,277 verified pairs and 105,123 reported candidates. No pair generation, pair verification or report limit was reached. Candidate rows, error rows, configuration and generation counts equal the recovered reference report. The reports differ in the bound source manifest and run provenance.

The screened view at `research_local/screened_splits_indexed_v01` uses 6,168 strong edges. Of these, 3,930 are symbolic near duplicates only, 2,234 are both exact arrangements and symbolic near duplicates and 4 are exact arrangements only. Screening quarantines 44 source groups containing 766 source files. It retains zero strong cross split edges. It newly marks 2,136 test phrases and 1,747 validation phrases as `duplicate_excluded`. A further 341 phrases in quarantined groups were already `overlap_excluded`.

The screened indexed phrase counts are 77,540 train, 7,071 validation, 6,126 test, 3,883 `duplicate_excluded` and 459 `overlap_excluded`. The reference screened view has the same source groups and edges, while its phrase counts differ because its melodic selections differ.

The duplicate report is a similarity based review aid. It can miss duplicates outside its fingerprint definition and it can flag musically related files that are not duplicate recordings.

## Reproduction

Python was run after `source .venv/bin/activate`. The comparison and curation commands were run from the repository root:

```bash
nice -n 10 python scripts/compare_variants.py \
  --left research_local/lakh_phrases_v03 \
  --right research_local/lakh_aligned_indexed_v01 \
  --output research_local/indexed_full_comparison_v02

nice -n 10 python scripts/audit_curation.py \
  --dataset research_local/lakh_aligned_indexed_v01 \
  --output research_local/curation_indexed_v01

python scripts/verify_experiment.py \
  --experiment research_local/indexed_full_comparison_v02

python scripts/verify_experiment.py \
  --experiment research_local/curation_indexed_v01
```

The duplicate and screening commands were run from `research_local/validation_runner_v02`, whose 35 files matched `RUNNER_SNAPSHOT.json` before execution:

```bash
nice -n 10 python scripts/audit_duplicates.py \
  --source '../../datasets/Lakh MIDI Clean' \
  --manifest ../lakh_aligned_indexed_v01/sources.jsonl \
  --output ../duplicates_indexed_v01.json \
  --cache ../duplicates_recovered_cache_v01 \
  --workers 2 --recover-invalid-keys \
  --max-generated-pairs 20000000 \
  --max-verified-pairs 2000000 \
  --max-reported-candidates 400000

nice -n 10 python scripts/screen_splits.py \
  --dataset ../lakh_aligned_indexed_v01 \
  --duplicate-report ../duplicates_indexed_v01.json \
  --output ../screened_splits_indexed_v01
```

An earlier frozen comparison attempt is preserved at `research_local/indexed_full_comparison_v01`. It stopped before producing results because version 1 treated detector outcome as immutable source identity. The separate diagnosis at `research_local/indexed_full_comparison_outcome_diagnosis_v01.json` identified 37 outcome differences and no other source identity field differences. Version 2 records outcomes as measured transitions. The failed v1 receipt is not scientific evidence.
