# Duplicate screening analysis

The current view applies to the recovered reference corpus `research_local/lakh_phrases_v03`. It preserves the original manifests and provides additional split exclusions based on heuristic melodic duplicate candidates. It is a sensitivity view, not a claim of complete musical separation.

## Full recovered diagnostic

The report `research_local/duplicates_recovered_v01.json` accounts for all 17,232 inputs, with 16,995 successful fingerprints and 237 parse errors. It uses one recorded method, zero cache reuse and explicit recovery of the same 28 invalid-key files as the dataset. The method verifies 1,026,277 pairs from 7,649,316 generated pair events. No source shingle or global pair/report bound is reached.

There are 6,164 symbolic near-duplicate candidates and four further exact-arrangement edges, giving 6,168 strong screening edges. The 98,959 weaker shared-pattern candidates are recorded for investigation but do not trigger this screening policy. The 77 strong cross-split pairs have the same source-hash endpoints as the previous strict diagnostic. Two edge similarity records change when recovered sources alter shingle document frequencies; they are not copied from the older report.

## Group screening

The view at `research_local/screened_splits_reference_v03` connects all strong edges, including edges within one split. Whole original groups in later splits are quarantined according to train before validation before test. It excludes 44 groups and 766 source files. Original labels remain available in each mapping row.

| Screened split | Source files | Phrase rows |
| --- | ---: | ---: |
| train | 13,966 | 77,445 |
| validation | 1,352 | 7,044 |
| test | 1,148 | 6,113 |
| overlap_excluded | not applicable | 480 |
| duplicate_excluded | 766 | 3,868 |

The new exclusions comprise 1,742 validation and 2,126 test phrase rows. Another 350 phrases in quarantined groups were already family excluded and keep `overlap_excluded`. No retained strong candidate edge crosses splits. This changes the validation and test distributions, so consumers should report which split view they use.

## Evidence and verification

The portable screening bundle contains the complete original `duplicate_report.json`, `candidate_edges.jsonl`, source and phrase mapping files and a summary with hashes. The verifier checks the copied report bytes, rebuilds its strong edge projection and reconstructs connected groups, mappings and counts against the base manifests. It rejects shifted source identities, changed mappings, missing evidence and escaped artifact paths. The script's creation hash is labelled unverified creation metadata, rather than a claim about whichever source file is currently installed.

```sh
source .venv/bin/activate
python scripts/screen_splits.py \
  --dataset research_local/lakh_phrases_v03 \
  --duplicate-report research_local/duplicates_recovered_v01.json \
  --output research_local/my_screened_view
```

Join `phrase_splits.jsonl` one-to-one to the base phrase manifest by `phrase_id`, then use `screened_split`. Exclude both `overlap_excluded` and `duplicate_excluded` when forming train, validation or test examples. Do not silently overwrite the original fields.

The report SHA256 is `2077800af8e1df96609aece44a9f217f3ac29e24ba40ded124dbe1c55e7cc299`. Small receipts are saved in `results/duplicates_recovered_v01.json` and `results/screened_splits_reference_v03.json`. They link the view to the exact recovered source and phrase manifests.

## Interpretation limits

Fingerprints use transposition-invariant pitch intervals and median-normalized rhythm shingles. They ignore shingle order and frequency, instrumentation, harmony and much duration information. High containment may mean a shared part, embedded excerpt, medley or a false positive. The 237 parse errors have no symbolic fingerprint. No human song-identity labels or claim of all possible covers and aliases being detected is made.

The earlier title and source inspections are preserved in [the strict-run analysis](duplicate_screening_strict.md). That document's counts, checksums and artifact layout describe the historical strict corpus. Its old screening files lack the current copied-report binding and are not accepted by the current package validator.
