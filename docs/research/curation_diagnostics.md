# Curation diagnostics

## Scope

`scripts/audit_curation.py` measures the selected phrase rows in a completed SaMuGeD dataset. It extends `scripts/summarize_dataset.py` with source level curation measures and does not repeat its general source outcomes or search limit inventory.

The reference run used `research_local/lakh_phrases_v03`. The script required its audit to have passed with zero failures and full source coverage. It also verified the audit bindings to `sources.jsonl`, `phrases.jsonl`, `summary.json` and `build_config.json`. It read and validated all 17,232 source rows and all 94,950 phrase rows, then rehashed all five input artifacts before completing the result receipt.

These are descriptive measures of detector output. They do not measure human phrase quality, false positive rates, salience, memorability or exhaustive search.

## Definitions

For each source and kind, top three means the rows with the lowest `rank_in_file` values within that kind. The reference build already contains at most three rows per kind. Melodic output supplied three rows for 16,762 of 16,872 sources with melodic output. Percussion supplied three rows for 14,396 of 15,268 sources with percussion output.

Prototype temporal sum is the sum of the three exported `[start_tick, end_tick)` window lengths. Prototype temporal union merges those windows on the source timeline before measuring them. Occurrence temporal sum and union apply the same calculation to every saved occurrence of the three selected families. The overlap fraction is `(sum - union) / sum`. The manifest does not contain total song duration, so none of these measures is presented as a percentage of a song. Tick intervals remain integers per source. Totals across different PPQ values use exact rational beat arithmetic and the result file retains numerator and denominator values.

A single pitch phrase has one distinct MIDI pitch in its prototype. Rhythmic vocabulary is the number of distinct positive inter onset intervals. Stored beat onsets are mapped to the nearest source tick. Simultaneous strikes are collapsed before intervals are computed, so a drum chord contributes several hits but does not add a zero length rhythmic interval. Tiny rhythmic vocabulary means at most two distinct positive intervals. This is a deliberately narrow structural flag. A phrase can use only two interval values in a varied order and still receive the flag.

Distribution quantiles use the nearest stored order statistic with a half-up rank. The reported median is therefore the stored p50 observation, not the arithmetic mean of the two middle values for an even-sized sample.

Melodic part concentration uses `part_index` among the selected rows. Percussion rows use the ensemble part index `-1`, so the percussion measure instead reports the union of `source_part_indices` represented by the selected rows.

## Reference findings

| Measure | Melodic | Percussion |
| --- | ---: | ---: |
| Phrase rows | 50,439 | 44,511 |
| Sources with output | 16,872 | 15,268 |
| Prototype groups with any overlap | 13,565 (80.40%) | 10,201 (66.81%) |
| Prototype overlap, weighted by summed duration | 24.74% | 21.62% |
| Median source prototype overlap fraction | 21.65% | 17.86% |
| Occurrence groups with any overlap | 15,814 (93.73%) | 13,194 (86.42%) |
| Occurrence overlap, weighted by summed duration | 39.36% | 31.44% |
| Median source occurrence overlap fraction | 33.11% | 26.00% |
| Duplicate family slots within a source top three | 0 | 0 |
| Families appearing in more than one source | 7,479 of 39,205 | 6,639 of 34,546 |
| Rows belonging to a multi source family | 18,713 (37.10%) | 16,604 (37.30%) |
| Single pitch prototypes | 0 | 0 |
| Tiny rhythmic vocabulary prototypes | 16,932 (33.57%) | 22,445 (50.43%) |

The weighted prototype union retains 75.26% of summed melodic duration and 78.38% of summed percussion duration. This shows that the package contains substantial temporal overlap between distinct selected families. It does not show that their notes or musical roles are interchangeable. Melodic windows can overlap while coming from different parts. Percussion windows can overlap at different bar lengths or phases.

No source repeats the same canonical family within its top three for either kind. Across sources, 11,234 melodic rows and 9,965 percussion rows are repetitions beyond the first row for each family. A shared family ID describes the detector's canonical symbolic identity. It does not identify a composition or prove copying. Family aware sampling or weighting could reduce repeated symbolic content in a packaged view while retaining the source and split grouping rules.

Melodic phrases have median duration 379/48 beats (7.896), median 12 notes and median 8 occurrences. Their 90th percentiles are 11.9 beats, 24 notes and 22 occurrences. Percussion phrases have median duration 16 beats, median 55 hits and median 7 occurrences. Their 90th percentiles are 16 beats, 125 hits and 17 occurrences.

Among sources with melodic output, 4,128 of 16,872 (24.47%) select all of their saved rows from one part. The median dominant part share is two thirds and the median selected part count is two. For percussion, 2,776 of 15,268 source groups (18.18%) combine selected rows whose ensemble metadata references more than one original drum part. The median referenced drum part count is one.

The low rhythmic vocabulary flag is common, especially in percussion. It is useful as a review stratum rather than an automatic exclusion rule because drum ostinati are expected to reuse a small timing alphabet. The absence of single pitch output is also a property of this selected corpus and detector configuration, not evidence that the input corpus contains no single pitch repetitions.

## Packaging implications

The current top three offers family diversity within each source, but it does not offer temporal independence. A low overlap package can be derived as an optional view by preserving rank order and adding a clearly declared interval overlap criterion. Removing every overlap would conflate simultaneous musical roles and should not replace the full dataset.

Family balanced sampling can reduce the roughly 22% excess rows beyond one row per canonical family. Such a view should retain source groups and the existing family split exclusions. It should also report counts as source files or groups, not compositions.

The tiny rhythm flag and melodic part concentration are suitable strata for human review. Neither is a quality label. Any exclusion threshold would be a new curation policy and needs a separate frozen comparison before becoming a packaging default.

## Reproduction and receipts

Run from the repository root with the project environment active:

```bash
python scripts/audit_curation.py \
  --dataset research_local/lakh_phrases_v03 \
  --output research_local/curation_reference_v01
```

The completed artifacts are `aggregate.json`, `raw_results.json`, `experiment_receipt.json`, `source_snapshot.json` and `completion_receipt.json` under `research_local/curation_reference_v01`.

The reference aggregate SHA256 is `45e7ef74738d54812d02544d804d007a9a90b2aced19731377a867dc5ef163aa`. The raw result SHA256 is `945528bd194c18a8da89c0effc58b89821b978606e6a7d54978d57f4dcb5bae3`. The completion receipt SHA256 is `60146172c1eb2ee67e019f8bdbdfb61d6a8ecd799d1847bec809b0a255deb557`.
