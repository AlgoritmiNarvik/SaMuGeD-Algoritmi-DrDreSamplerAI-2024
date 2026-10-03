# Shortlist cap sensitivity

## Question

The melodic detectors retain at most 80 candidates per part before global ranking and diversity pruning. This frozen development study asks whether retaining 400 candidates changes the selected top three or merely reduces candidate truncation telemetry.

This is a sensitivity diagnostic. It does not select a new default. It uses no test split or external human labels and it does not measure musical quality or memorability.

## Frozen design

The study compared two configurations for each detector. The only changed field was `max_candidates`, set to 80 or 400. `top_k` remained 3 and all other detector settings remained at their defaults.

- Reference approximate detector: 500 development cases from `generate_cases(1000)` and 128 fixed real MIDI sources.
- Aligned indexed detector: the same 500 development cases and 128 real sources.
- Development scoring: planted candidate and occurrence precision, recall and F1 plus recovery rank.
- Real source analysis: exact selected output equality, selected family counts, structural diversity, runtime and limit telemetry. The real sources have no labels in this study.
- Execution: one process at nice level 10. Cap order alternated by item and detector to reduce a fixed first-run timing bias.
- Input binding: every real MIDI file was checked against the SHA256 recorded in `research_local/pilot_indexed_v01/sources.jsonl` before the start receipt was written.

Structural diversity is described without assigning quality. For selected families on the same part, an occurrence is covered when at least 70 percent of the shorter interval overlaps an occurrence from the other family. The report records the number of such family pairs and their overlap coverage. Cross-part families are counted separately rather than treated as overlapping.

The start receipt binds 500 development cases, 128 real source paths and hashes, both configurations and the executable source snapshot. The completion receipt binds the raw and aggregate result bytes.

## Results

| Detector and cohort | Equal selected outputs | Changed outputs | Changed top 1 | Cap 80 truncated cases | Cap 400 truncated cases |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference, development | 500 / 500 | 0 | 0 | 0 | 0 |
| Reference, real | 128 / 128 | 0 | 0 | 121 | 58 |
| Aligned indexed, development | 499 / 500 | 1 | 0 | 22 | 0 |
| Aligned indexed, real | 126 / 128 | 2 | 0 | 125 | 118 |

For the reference detector, the selected output was byte-equivalent across caps for every item even though the cap of 80 truncated candidates in 121 of 128 real files. In this cohort its cap signal is telemetry, not a selected-output difference.

For aligned indexed, 3 of 628 paired items changed, 0.48 percent overall. The top ranked family never changed. One development case gained a second, incorrect candidate at cap 400. Two real files substituted the third ranked family. These real substitutions cannot be scored as better or worse because the cohort is unlabelled.

### Development metrics

| Detector | Cap | Candidate F1 | Occurrence F1 | Top 1 recovery | Mean reciprocal rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference approximate | 80 | 0.715996 | 0.717629 | 0.777778 | 0.777778 |
| Reference approximate | 400 | 0.715996 | 0.717629 | 0.777778 | 0.777778 |
| Aligned indexed | 80 | 0.871140 | 0.862245 | 0.936170 | 0.950355 |
| Aligned indexed | 400 | 0.870213 | 0.861366 | 0.936170 | 0.950355 |

The aligned indexed difference came from `development-0271-meter_ppq_change`. Cap 80 returned the correct top ranked family alone. Cap 400 retained three additional per-part candidates and selected one extra family, adding one candidate false positive and two occurrence false positives. Recall and rank were unchanged. This single development example lowered candidate F1 by 0.000927 and occurrence F1 by 0.000879. It is development evidence and should not be read as a held-out effect estimate.

### Selected family structure on real sources

| Detector | Cap | Selected families | Mean per source | Overlapping same-part pairs |
| --- | ---: | ---: | ---: | ---: |
| Reference approximate | 80 | 376 | 2.9375 | 17 |
| Reference approximate | 400 | 376 | 2.9375 | 17 |
| Aligned indexed | 80 | 379 | 2.9609 | 29 |
| Aligned indexed | 400 | 379 | 2.9609 | 30 |

The two changed aligned indexed files were `Celine_Dion/The_Power_of_the_Dream.mid` and `George_Baker_Selection/Little_Green_Bag.mid`. Both kept the same first two families and replaced only the third. At cap 80 each selection spanned two parts. At cap 400 all three selected families came from one part. The maximum pair overlap coverage rose from 0 to 0.667 and 0.875 respectively. This shows that a larger per-part shortlist can reduce cross-part variety in the final top three even though it exposes more candidates to global ranking.

### Runtime and other bounds

| Detector and cohort | Cap 80 seconds | Cap 400 seconds | Median paired ratio, 400 / 80 |
| --- | ---: | ---: | ---: |
| Reference, development | 0.960 | 0.989 | 1.0107 |
| Reference, real | 42.224 | 42.634 | 1.0080 |
| Aligned indexed, development | 13.223 | 12.982 | 0.9945 |
| Aligned indexed, real | 379.885 | 379.144 | 0.9987 |

The shortlist is sliced after candidate generation and sorting, so it is not expected to reduce detector search work. Paired runtimes were nearly equal and changed direction across cohorts. These are single-process descriptive timings while other local corpus work was active, not a performance benchmark.

Other search bounds were unchanged by the cap. On real files, the reference detector marked 3 of 128 cases as search limited and aligned indexed marked 23 of 128. Aligned indexed recorded 485 saturated seed buckets under both caps. Results therefore describe shortlist sensitivity conditional on the other fixed bounds. They do not show what an unbounded search would select.

## Interpretation

The cap of 80 is mostly telemetry for the selected top three in these cohorts, but it is material in a small number of aligned indexed cases. Raising it to 400 did not change any top ranked family or any reference output. It changed lower ranked aligned output in one development case and two unlabelled real files. The larger cap did not improve development recovery and produced a small precision decrease from one extra selected family.

This evidence does not justify changing the default. The real cohort is small and unlabelled, the synthetic cohort is development data and the cap of 400 still truncated aligned candidates in 118 of 128 real files. A default decision would need a separately frozen labelled or human review protocol that evaluates lower ranked family usefulness and cross-part variety.

## Reproduction and receipts

The command used for the frozen run was:

```bash
nice -n 10 python scripts/compare_shortlist.py \
  --source "datasets/Lakh MIDI Clean" \
  --manifest research_local/pilot_indexed_v01/sources.jsonl \
  --output research_local/shortlist_sensitivity_v01
```

The output directory must be absent or empty. For an exact rerun, reconstruct an isolated checkout from `source_snapshot/` and use the recorded dependency files. The shared working tree advanced in `samuged/evaluate.py` and `samuged/experiment.py` while the already imported frozen run was executing, so rerunning the command against the current working tree is a new experiment. The completion verifier confirms the saved snapshot and result bytes are unchanged.

- Start receipt SHA256: `f31cbf2f7749fc48818c5b0904ba35ed16b3ce0c43d2c582a4e3b0bce1bb0e83`
- Configuration SHA256: `04081895903632b258d7b960f2ff79beafa44f59059092211d7bfb51f58b98c3`
- Case cohort SHA256: `0927c97757eed21c6f9762ff485127f3a8fe59bf43ec0a6904632317595c6673`
- Source snapshot SHA256: `d3dadaf12fa2abf51222ddbf956fc97f2c862d34ddb8824689a5371b3b7cfc44`
- Raw results SHA256: `c62c0882b31757f3e9f853bb81efcc61a13dd74295e57ff742f389ff6e624f61`
- Aggregate SHA256: `15a4076a0ecbe0a9465cfd88d63a88f33a1cbe7ff94540712caa3a5e534527d7`
