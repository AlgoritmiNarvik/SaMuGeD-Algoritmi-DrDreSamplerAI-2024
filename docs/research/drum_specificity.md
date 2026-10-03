# Development analysis of drum specificity

## Scope

The preferred independent pair admissibility reference is the completed executable-closure receipt in [`research_local/drum_oracle_v02`](../../research_local/drum_oracle_v02). The development stress interpretation below remains historical evidence from `drum_stress_v01`, whose `development_analysis.json` is not replaced by the oracle study.

This audit uses only the 20 development cases from the frozen `independent_patterns_negative` condition. It reconstructs the six development cases that returned tolerant matches and verifies their frozen arrangement hashes before replay. It does not inspect the test split, change detector code or alter the frozen benchmark results. The detailed machine readable evidence is in `research_local/drum_stress_v01/development_analysis.json`.

## Finding

The output is caused mainly by genuine shorter recurrence in the synthetic generator, not by a verifier error or unrelated context bars.

The tolerant detector returned output for 6 of 20 development cases. These were all six cases whose generated phrase length was four bars. None of the seven one bar or seven two bar cases returned output. Exact mode returned no output for this condition.

The six cases produced 55 valid candidates before the top three limit and 18 selected candidates after ranking. All selected candidates had support of two occurrences. Their lengths were sixteen two bar candidates, one one bar candidate and one four bar candidate. Seventeen candidate pairs were fully contained in the same independently generated four bar region. One four bar pair connected two different generated regions. No selected pair came from the surrounding context bars.

The generator explains the concentration. Each bar has the same sixteen step hat skeleton. Kick, snare and accent positions also follow deterministic rules based on bar index. In a four bar phrase, the first and second two bar halves therefore differ in only two kick placements per half pair. For each of the sixteen selected two bar comparisons, 46 of 48 hits matched, four hit slots were unmatched and all matched onsets had zero timing error. This is exactly the allowed four unmatched hits at the ten percent boundary. The selected one bar pair matched 23 of 24 hits with two unmatched hit slots, also exactly at its allowed boundary.

The one cross region four bar pair matched 92 of 96 hits. Eight hit slots were unmatched because one tom pitch differed between the regions. Its 60 hat matches had small swing differences within tolerance, while 32 non hat hits also matched. This is a chance recurrence under a highly shared generator skeleton and finite kit vocabulary, rather than a hats only coincidence.

Across all 18 selected comparisons, 851 hits matched and 74 hit slots were unmatched. MIDI pitches 42 and 44 supplied 555 matches, or 65.2 percent. Other pitches supplied 296 matches. Hats dominate the evidence, but the kick, snare and accent structure contributes enough exact agreement that removing hat evidence alone would not explain the accepted families.

Independent replay reproduced all 18 accepted comparisons and their stored similarities. Every pair satisfies the configured pitch identity, timing tolerance and edit budget. This found no verifier implementation error. The benchmark labels the whole arrangement negative because its macro regions were generated independently, but that label does not imply that shorter windows inside a region lack recurrence.

## Ranking diagnostics

Selected recurrence scores ranged from 0.5980 to 0.7469, with a mean of 0.6777. Match quality ranged from 0.9745 to 0.9823. Support was 0.3333 for every candidate because every selected family had two occurrences. Hit density was 1.0 and instrument diversity was 0.8316 throughout.

The primitive period diagnostic did not flag this mechanism. It is computed inside the selected candidate. Each two bar candidate contains two distinct bars, so its exact primitive period is two and its bar variation score is 1.0. The repeated unit appears when the two bar candidate recurs in the second half of its surrounding four bar region. A diagnostic limited to the candidate's internal bars cannot see that enclosing structure.

## Proposed mitigation

Do not tune the detector against these development outputs. The observed matches satisfy the declared recurrence relation, so suppressing them would reject valid nested patterns.

For a future synthetic specificity cohort, use recurrence certified negative generation. Before detector execution, enumerate all nonoverlapping one, two and four bar window pairs. Admit an arrangement as negative only when every pair has a certificate that it exceeds the frozen pitch specific timing or edit bounds. If an independently generated macro phrase contains a qualifying shorter pair, label that pair as nested legitimate structure instead of counting it as a negative error. Freeze this rule and its thresholds before generating a held out split.

This produces valid negative labels, but it also makes the negatives cleaner than real music. Rejection can reduce rhythmic diversity and increase generation cost. It cannot estimate how often useful or incidental recurrence occurs in a real corpus, so the synthetic result still needs a separate human reviewed real corpus protocol.

## Independent pair enumeration

A second check now exists in `samuged/drum_oracle.py`. It enumerates eligible one, two and four bar windows, then compares every nonoverlapping pair with matching meter and bar count. Equal kit pitches are matched by an independent maximum cardinality onset matcher at 1/12 beat tolerance. Total unmatched hits may not exceed the floor of ten percent of the larger hit count. It shares the source drum ensemble normalization with the detector, but does not use the detector's window generation, seeds, grouping or pair matcher.

The frozen study uses all 240 development cases from the stress cohort and sixteen real sources from the fixed pilot, clipped to their first 32 complete bars. This is a bounded diagnostic. The real sample is small and its introduction clips do not represent the full corpus. All 292,091 eligible comparisons completed without reaching the pair budget.

| Measure | Synthetic development | Real clips |
| --- | ---: | ---: |
| Cases | 240 | 16 |
| Independently admissible pairs | 5,313 | 3,245 |
| Admissible pairs represented in selected families | 994 | 797 |
| Selected pair coverage | 18.71% | 24.56% |
| Direct prototype edges checked | 589 | 157 |
| Invalid direct prototype edges | 0 | 0 |

The selected collection is limited to three diverse families per source. Pair coverage therefore combines discovery, grouping, ranking and selection effects. It is not a measurement of the detector's internal candidate recall. Four cases still omit admissible pairs without reporting a search limit or an observable candidate selection reason, so a general completeness claim would be incorrect.

A family is centred on a fixed prototype. Every retained occurrence must match that prototype, but two other occurrences may differ from each other beyond the tolerance. This nontransitivity explains 205 synthetic and ten real pairs that fail the oracle when every pair inside a returned family is checked. All direct prototype edges pass. Downstream users should retain the prototype relationship instead of interpreting an approximate family as a clique of mutually matching occurrences.

Compact counts and artifact hashes are saved in the preferred [`drum_oracle_v02` aggregate](../../research_local/drum_oracle_v02/aggregate.json), with raw evidence in [`drum_oracle_v02/raw_results.json`](../../research_local/drum_oracle_v02/raw_results.json). Its start receipt SHA256 is `896300214e5bf5602559d2456865eac1847894e9826f8a5b482c77c45eae0814`, completion receipt SHA256 is `42fb1e8c02eb33d3b106b8bcfb24c4129bc58aa08ece00a3a9ffc6193e2c3413` and executable source snapshot SHA256 is `879706f1749df154a69847691921e5c6174742a20cef2ad9776281556beac81e`. The historical v01 oracle remains available for comparison. Reproduce with `source .venv/bin/activate && python -m samuged.drum_oracle --output research_local/drum_oracle_new`. Neither this check nor the earlier stress analysis supplies human labels or validates musical salience.
