# Seed bucket cap sensitivity

## Question

This bounded experiment measures whether increasing the aligned indexed seed posting bucket cap changes verified recurring phrase output. It compares `AlignedConfig.max_bucket=192` with `max_bucket=768`. The candidate shortlist remains 80, the comparison cap remains 2,000 and the verifier and ranking are unchanged.

The synthetic cases measure planted symbolic recurrence. The real MIDI files have no phrase accuracy labels. Real output changes show sensitivity to this resource bound, not improvement in musical quality or human response.

## Frozen design

The synthetic cohort contains the 500 development cases returned by `generate_cases(1000)`. Test split cases are excluded. The real cohort contains all 23 search limited files from the fixed 128 file Lakh pilot and 23 controls chosen before measurement from unlimited files by `SHA256(source_path)` order.

The pilot records establish the observed cause of the search limit. All 23 limited files have one or more saturated seed posting buckets, none has a note, window, comparison or group limit flag and no part has `comparison_limit_reached=true`.

A start receipt freezes the design, both complete configurations, all synthetic seeds and truth intervals, all real paths and hashes and the executable source closure before detector execution. A fixed pilot of six limited files, six controls and 20 development cases estimates total paired runtime. The predeclared fallback would use the first 12 path ordered limited files and first 12 hash ordered controls if projected detector time exceeded one hour.

## Reproduction

Run from the repository root:

```bash
source .venv/bin/activate
nice -n 10 python scripts/compare_seed_buckets.py \
  --source "datasets/Lakh MIDI Clean" \
  --manifest research_local/pilot_melody_v01/sources.jsonl \
  --output research_local/seed_bucket_sensitivity_v01
python scripts/verify_experiment.py \
  --experiment research_local/seed_bucket_sensitivity_v01
pytest -q tests/test_seed_buckets.py
```

## Results

The runtime pilot projected 233.23 seconds of paired detector work, below the one hour limit. The full predeclared cohort was therefore evaluated. The completed receipt verifies both result artifacts.

### Development cases

The 500 development cases never approached either seed bucket cap. Their largest bucket contained 30 postings. Both variants returned byte equivalent phrase structures on every case and produced identical scores:

| Development metric | Cap 192 | Cap 768 |
| --- | ---: | ---: |
| Candidate F1 | 0.8711 | 0.8711 |
| Occurrence F1 | 0.8622 | 0.8622 |
| Positive cases recovered | 409/423 | 409/423 |
| Top one recovery | 0.9362 | 0.9362 |
| Negative cases with output | 0/77 | 0/77 |
| Detector time | 13.19 s | 13.07 s |

These cases provide no evidence about the saturated regime because neither configuration saturated.

### Fixed real MIDI

| Cohort and metric | Cap 192 | Cap 768 |
| --- | ---: | ---: |
| Limited files with seed saturation | 23/23 | 1/23 |
| Limited saturated buckets | 485 | 7 |
| Limited postings dropped | 49,194 | 1,178 |
| Limited posting entries visited | 148,280,865 | 158,359,471 |
| Limited proposed pairs | 17,990,728 | 19,491,091 |
| Limited DP comparisons | 254 | 259 |
| Limited detector time | 114.99 s | 118.27 s |
| Limited files with changed selected output | 0 | 1 |
| Control files with saturation | 0/23 | 0/23 |
| Control files with changed selected output | 0 | 0 |
| Control detector time | 55.28 s | 55.65 s |

The wider cap reduced dropped postings by 97.6% and saturated buckets by 98.6% in the limited cohort. It increased posting visits by 6.8%, proposed pairs by 8.3% and measured limited cohort runtime by 2.9%. Neither variant reached the 2,000 comparison cap. The controls had identical nonruntime telemetry and identical outputs.

One limited file changed, `Pooh/Pensiero.4.mid`. The wider cap still saturated seven pair seed buckets in this file. All three selected semantic outputs changed. The first retained the same family and source start but its verified support changed from six occurrences to five and its recurrence score changed from 0.9221 to 0.9172. The second changed from a 20 note, five occurrence family to a 23 note, four occurrence family. The third moved from part 4 with 16 notes and two occurrences to part 7 with nine notes and eight occurrences. There is no annotation with which to judge either selection.

The effect is not monotonic. Extra postings can connect a candidate to a different existing group during greedy candidate processing. That changes group representatives, verified membership, occurrence support and later ranking. In the changed file, the wider cap reduced total groups from 35,240 to 34,952 while increasing repeat groups from 1,667 to 1,856. The selected candidate count remained 272 under both settings because every real file in both cohorts also reached the unchanged per part shortlist limit of 80. This experiment did not vary that limit, but it can mediate which seed induced candidate changes reach the final three selections.

## Decision and limitations

Increasing `max_bucket` to 768 materially reduces the search limit flag with a small measured runtime increase on this cohort. It has no measured development benefit and changes one of 23 saturated real outputs in a way that cannot be labelled better or worse. The result supports recording seed saturation separately from comparison limits. It does not support changing the production default based on accuracy.

Aligned builds expose this parameter as `--seed-bucket-limit 768`. The default remains 192. An explicit value is saved as `config.max_bucket` and changes the run fingerprint, so use a new output directory. The option accepts 1 through 2048 and is rejected for the reference detector. The current full indexed, closed and melody builds all use the unchanged default 192.

The real cohort was selected from the earlier 128 file pilot and overrepresents known saturation. The control selection is deterministic but small. Runtime comes from one alternating order run on one machine. The fixed shortlist cap means this is a sensitivity study of the seed bucket bound within the current bounded pipeline, not an exhaustive recurrence search.

Integrity identifiers:

- start receipt SHA256: `548fb8ae5905aa6b29229c2dd4c15550b81ebceca716fe60cb8cb60652ac1231`
- frozen source snapshot SHA256: `04cc32548c3a80fb6f0815145ca79f15645209c504807f53aa70d6fdb0e88059`
- case cohort SHA256: `3024829258ae09e59f3097364ef52d93c66edd6c9347a2b793c47884e8a75897`
- raw results SHA256: `87b41d0c8b969fd02060a1cdf819be61ce652741472246ab982695ad8b0fadbf`
- aggregate SHA256: `8d5ebb5db796f128c70d634068c05038c3cbdb4c0361c311fb336dea88fef4ff`
