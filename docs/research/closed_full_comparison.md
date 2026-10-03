# Closed full corpus comparison

## Scope and evidence boundary

This note compares the audited `aligned_closed` full corpus with the audited
`aligned_indexed` full corpus. Both runs cover 17,232 input paths. The closed
audit passed with zero failures and full source coverage. It reports 16,995
successful parses and 237 parse errors. The comparison is a differential
description of saved detector output. It is not an accuracy, musical quality,
human preference or perceptual result.

The comparison completed at
`research_local/closed_full_comparison_v01`. Its completion verifier passed
for all four comparison artifacts. The curation run is descriptive only. The
duplicate report and screened view are heuristic supplementary views and do
not establish duplicate ground truth.

| Artifact | SHA256 |
| --- | --- |
| Closed `sources.jsonl` | `f69d200caab0749f78354de08272352237ad1bfcc540278b42d5929672dd3d3b` |
| Closed `phrases.jsonl` | `7a827173407fa0d522e37b4d4f970e5f344e3870663854a6bc5d2e0899de602b` |
| Closed `summary.json` | `4af75e44fe08de6494fb82452cc167099aea852806a3e057bb990cb951677ec3` |
| Closed `build_config.json` | `d7e1b223b6dca7e2c61d6160b8f19a22e0d879cca98b68c3024883f61a5a909b` |
| Closed `audit.json` | `34a4391532674b4981924cc2a4065df06e7b3ba6b012189164dac6f05746dd29` |
| Comparison `aggregate.json` | `f5adffb5e0075e3bad8ab9bd0b55bec730250637de1ced36e76079de6c8133dd` |
| Comparison `raw_results.json` | `d95390631e2b67a06795fcbbb9595010f28d82a1ba07a4afeb853a02882062a9` |
| Comparison `input_inventory.json` | `0fd671a8ee138f5325cde9c8fca705de7bada595971a9b7c7ecae8a1d12d2290` |
| Comparison `experiment_receipt.json` | `721123f7743fcf15018d23f52037dfecc62bbd71bc651d574383533850569522` |
| Comparison `completion_receipt.json` | `9aa28b042f0df52441763b3f35c0074aeb7f10c50915fde18d3444a100decb36` |
| Comparison `source_snapshot.json` | `a4888af1a4bbe09db54dfa33589af87d5b092260be9f919e7c63c280e0c5dca7` |

## Detector output differences

All source outcome categories were unchanged:

| Outcome | Indexed | Closed | Change |
| --- | ---: | ---: | ---: |
| `error:parse_error` | 237 | 237 | 0 |
| `ok:matched` | 16,923 | 16,923 | 0 |
| `ok:no_match` | 72 | 72 | 0 |

The full semantic payload changed for 2,605 melodic sources. It changed for
zero percussion sources. Selected melodic phrase rows changed from 50,568 to
50,566 (difference -2); percussion rows remained 44,511. The semantic payload
retains scores, matcher flags, alignment data, occurrence coordinates and
musical fields while excluding only build identifiers and rank fields.

The v3 common content projection separates note and interval content from
algorithm-specific metadata. It includes prototype note fields and sorted
occurrence interval coordinates. It excludes scores, matcher flags, edit paths
and other alignment metadata.

| Common projection | Melodic changed sources | Percussion changed sources |
| --- | ---: | ---: |
| Ordered prototype sequence | 2,605 | 0 |
| Duplicate-preserving prototype multiset | 2,605 | 0 |
| Top one prototype | 1,918 | 0 |
| Ordered recurrence interval projection | 2,605 | 0 |

The selected melodic prototype count is 50,568 for indexed and 50,566 for
closed. The percussion prototype count is 44,511 for each. There were 207
melodic and 6 percussion global rank shifts. These rank shifts are reported as
metadata diagnostics and do not imply percussion content changes. The melodic
family count changed from 39,746 to 39,780, with 36,746 common families and 61
families whose membership changed. The percussion family count stayed 34,546.

The phrase split counts were:

| Phrase split | Indexed | Closed |
| --- | ---: | ---: |
| train | 77,540 | 77,538 |
| validation | 8,818 | 8,818 |
| test | 8,262 | 8,262 |
| `overlap_excluded` | 459 | 459 |

The source split counts in the closed build are 13,966 train, 1,694
validation and 1,572 test. No detector rerun was performed as part of this
comparison. The closed build itself was created and audited before this
differential analysis.

## Duplicate report and screened view

The closed duplicate report is
`research_local/duplicates_closed_v01.json`. It used explicit invalid-key
recovery, the existing recovered fingerprint cache and the same uncapped
settings as the indexed and recovered reports: 20,000,000 generated pair
events, 2,000,000 verified pairs and 400,000 reported candidates. It used two
workers and had 16,995 cache hits.

The following values equal both prior full reports:

| Measure | Value |
| --- | ---: |
| Successful fingerprints | 16,995 |
| Parse errors | 237 |
| Metadata-recovered files | 28 |
| Metadata-recovery events | 124 |
| Generated pair events | 7,649,316 |
| Verified pairs | 1,026,277 |
| Reported candidates | 105,123 |
| Exact-arrangement candidates | 2,238 |
| Symbolic near-duplicate candidates | 6,164 |
| Shared-pattern candidates | 98,959 |
| Strong cross-split edges | 77 |
| Pair generation, verification and report caps reached | no |

The closed report SHA256 is
`92cad57eeceaac57b51c769290cfa7a0d1207b0458b8f137af7a7b442a721614`.
Its design SHA256 is
`3085c00ec84503609ab7daeda86fdb046c3090d33064907368e059cd0d89f704` and
its method key is
`818e13be7a44762592a2473d3f2253880f52a71d81f704d3c162dceb842be011`.

The screened closed view is
`research_local/screened_splits_closed_v01`. Independent
`verify_screening(dataset, screening)` reconstruction passed. It copied the
complete duplicate report and verified its bytes, strong edge projection,
source and phrase mappings and counts.

| Screened measure | Value |
| --- | ---: |
| Candidate edges | 6,168 |
| Excluded source groups | 44 |
| Excluded source files | 766 |
| Retained cross-split strong edges | 0 |
| Already family-excluded phrases in quarantined groups | 341 |
| Newly excluded validation phrases | 1,747 |
| Newly excluded test phrases | 2,136 |

The closed screened phrase counts are 77,538 train, 7,071 validation, 6,126
test, 3,883 `duplicate_excluded` and 459 `overlap_excluded`. The source counts
are 13,966 train, 1,352 validation, 1,148 test and 766
`duplicate_excluded`. The screening artifact hashes are:

| Artifact | SHA256 |
| --- | --- |
| `summary.json` | `4b3bf34c00378bd2d08c21468eff17b10e236600d24f1606cde1afc435d4edb5` |
| `candidate_edges.jsonl` | `a792ec7c968946f1e7807a87e503e1bc1a787a70da173dc875265fdc3e7b86d6` |
| `phrase_splits.jsonl` | `9a45938fc178d858c2ff87cf10883bc08d55c27d3b64a0ea9759abbecb054f0a` |
| `source_splits.jsonl` | `ab5e2395667e46f646351d95e58c3264c928d117a466a939d9334eb1607fb38a` |
| Copied `duplicate_report.json` | `92cad57eeceaac57b51c769290cfa7a0d1207b0458b8f137af7a7b442a721614` |

The duplicate report is a similarity based review aid. It can miss duplicates
outside its fingerprint definition and can flag related material that is not a
duplicate recording. Screening is an additive sensitivity view. It preserves
the original split labels and manifests.

## Descriptive curation

`research_local/curation_closed_v01` validates 17,232 source rows and 95,077
phrase rows. It reports 50,566 melodic phrases across 16,908 melodic source
groups and 44,511 percussion phrases across 15,268 percussion source groups.
Among the selected melodic groups, 5,019 of 16,908 have all selected rows
from one part. The median selected melodic prototype has 19 notes, 12.89583333
beats and 7 saved occurrences. The corresponding percussion medians are 55
notes, 16 beats and 7 occurrences.

The curation output is descriptive and does not establish human quality,
false-positive rates, memorability or exhaustive search. Its verified output
hashes are:

| Artifact | SHA256 |
| --- | --- |
| `aggregate.json` | `1c52a875bf736a6a96045e3b54e72f1b68c59286e7dd9169fdc2b2764f121480` |
| `raw_results.json` | `9742506e2820264e9a8a3ed96cacd5597c137dce637dd5b1337a2d9078700b76` |
| `experiment_receipt.json` | `ad1019553fe92bd75fa06ff57a965fc97df80288758d4144925dc148a9aad3f5` |
| `completion_receipt.json` | `2aba1e1d1ec405824b9580ef7b4c3001e48b723b32c698b4b31c9b206a4b11a4` |
| `source_snapshot.json` | `ec4ba31fbd6f811d9997a1e3059465eaeac1419ed6aa69e7833977a16b5e23e4` |

## Independent content reconstruction

A separate streaming implementation reads the phrase manifests directly and
reproduces all eight changed source ID sets. It also compares duplicate report
candidate rows, errors and generation counters with the indexed and reference
reports and reconstructs the screened splits. All checks pass. The report is
`research_local/closed_content_diagnostics_independent_v01.json`, SHA256
`25e44accf44a3a46f90803fdc6e0acd8d3989d4a2960ec0073cede9cf3f29055`.
The saved driver SHA256 is
`cf7820c1305b447a31a3255c37aae321070b46be6c40078bf29c934b93288084`.
A root rerun at `research_local/closed_content_diagnostics_root_v01.json`
reproduces the independent report exactly.

The direct manifests contain actual PPQ, whereas the comparison's record
phrase projection stores that field as null and checks it at source level.
This representation difference affects raw hashes, not the changed source
sets. Changing only that field to the record representation reproduces every
saved changed row. See [comparison identity](comparison_identity.md).

## Reproduction commands

Run from the repository root after `source .venv/bin/activate`. Use new
output paths so the completed evidence above remains unchanged:

```bash
python scripts/compare_variants.py \
  --left research_local/lakh_aligned_indexed_v01 \
  --right research_local/lakh_aligned_closed_v01 \
  --output research_local/my_closed_comparison

python scripts/verify_experiment.py \
  --experiment research_local/my_closed_comparison

python scripts/audit_duplicates.py \
  --source 'datasets/Lakh MIDI Clean' \
  --manifest research_local/lakh_aligned_closed_v01/sources.jsonl \
  --output research_local/my_closed_duplicates.json \
  --cache research_local/duplicates_recovered_cache_v01 \
  --workers 2 --recover-invalid-keys \
  --max-generated-pairs 20000000 \
  --max-verified-pairs 2000000 \
  --max-reported-candidates 400000

python scripts/screen_splits.py \
  --dataset research_local/lakh_aligned_closed_v01 \
  --duplicate-report research_local/my_closed_duplicates.json \
  --output research_local/my_closed_screening

python scripts/audit_curation.py \
  --dataset research_local/lakh_aligned_closed_v01 \
  --output research_local/my_closed_curation

python scripts/verify_experiment.py \
  --experiment research_local/my_closed_curation
```

The full closed build and its source audit are frozen inputs to these steps.
The closed comparison, duplicate report, screening and curation outputs are
new local evidence. No claim is made that the heuristic duplicate view is a
complete corpus screen or that the detector selections are musically correct.
