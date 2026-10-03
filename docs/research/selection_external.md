# External selector diagnostic

This frozen local study compares three selection policies over the same aligned indexed candidate generator. It uses `aligned_indexed`, `aligned_closed` and the optional `aligned_melody` part prior with the unchanged default `AlignedConfig(top_k=3)`. The inputs are reused development diagnostics, not fresh heldout data.

## Design and integrity

The POP909 side uses the six audited [Theme Transformer annotations](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html). Each song is reconstructed from the exact annotator 0 note union as one neutral piano Part. Human labels remain outside the detector input. This representation cannot test part role selection. It can only test whether the closed selection rule changes the chosen recurrence families. The study scores exact source note identities against each of three annotators using the existing note classification adapter.

The classical side uses the five official JKU Pattern Development Database works in both monophonic and polyphonic representations. Predictions are scored with the existing `mir_eval.pattern` adapter. Its seven published metric examples and all 17 comparable values passed the existing tolerance check before JKU detector execution.

The start receipt froze 16 cases, all source hashes, one detector configuration, the three method names and the executable local import closure before any detector ran. The completion receipt binds the two result artifacts. Verification with `scripts/verify_experiment.py` passed.

| Artifact | SHA256 |
| --- | --- |
| Start receipt | `f1f6ff70a57c169631818d24f28ee88e1fe31338068d0fac4924df35668fc7b2` |
| Source snapshot manifest | `7d6646c979c0d6e5518d8d283fc758e55f9f834949463b7d23b8e5a7a2b8bf1f` |
| Raw results | `fcd016105b823d3d4677fd5d0b39d51afd8e8049d242a78aa02d44053e69ee69` |
| Aggregate | `3c42d63e475a9bced336f5b97b671e429f5f2feeebe98549ec40700cb2e58fb1` |
| Completion receipt | `1da625c8cb05e0c7dc67250d635faef320d508cda8506d9a6579eede840ef297` |

The receipt links are config `bff54708273eb4b5f16ba2160786f5c34a49da6d1cd0c8dc2778ea72af181181`, cohort `02c8074c71c5396f218f1acb5c30094d568bea1a4221b2ca4b55f3df34361282` and executable source snapshot `b4cc624329b322196e90ace4dbab2ccac2cc8cb406866efadcd78c9b7e3e96ca`.

## Results

All three methods produced the same ThemeTransformer note classification scores.

| View | Precision | Recall | F1 | Closed minus indexed F1 | Melody minus indexed F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top one | 0.472442 | 0.251713 | 0.322875 | 0.000000 | 0.000000 |
| Top three | 0.480734 | 0.487879 | 0.464651 | 0.000000 | 0.000000 |

Every paired six song bootstrap interval for the Theme precision, recall and F1 differences was `[0, 0]`. Song 464 did change the second and third selected family under closed selection, but the union of predicted source note identities was unchanged in both scored views. `aligned_closed` and `aligned_melody` had byte identical selected phrase payloads for all six songs, as required by the single Part representation.

On JKU, closed selection did not change any of the ten ordered outputs or metrics. The optional part prior changed three polyphonic ordered outputs. One was an order change with the same three families and two changed family membership.

| Representation and selector | Establishment F1 | Occurrence F1 at 0.75 | Three layer F1 |
| --- | ---: | ---: | ---: |
| Monophonic indexed | 0.416720 | 0.421554 | 0.393390 |
| Monophonic closed | 0.416720 | 0.421554 | 0.393390 |
| Monophonic melody prior | 0.416720 | 0.421554 | 0.393390 |
| Polyphonic indexed | 0.239229 | 0.084361 | 0.232067 |
| Polyphonic closed | 0.239229 | 0.084361 | 0.232067 |
| Polyphonic melody prior | 0.237214 | 0.084361 | 0.227257 |

The mean polyphonic melody prior differences were `-0.002015` for establishment F1, `0` for occurrence F1 at 0.75 and `-0.004809` for three layer F1. Five works are too few for a useful selector confidence interval, so none is reported. These mixed development results provide no external reason to promote either optional selector.

The unchanged indexed outputs exactly matched both earlier indexed studies when comparison was valid. The Theme prior has a completed receipt. The older JKU prior has an internally verified start receipt and raw to aggregate hash binding but predates completion receipts. In both cases the aligned detector source hashes, configuration and case cohort were identical and all phrase and prediction hashes matched.

Root repeated all 48 runs in `research_local/selection_external_root_v01` and compared every nonruntime run field, selected phrase, prediction and Theme classification row with the initial study. All matched. A separate regression check against the preferred `theme_evaluation_v02` also matched; the initial study had used the earlier v01 comparison artifact. The verification is saved in `research_local/selection_external_root_comparison_v01.json`. Root reran 30 focused external metric, input and selector tests successfully.

All 48 detector runs completed without a search limit. Every run reported shortlist curation truncation at the fixed 80 candidate cap. The comparison therefore measures selection over the saved bounded shortlist. It does not measure what an unbounded candidate generator would have supplied. Total detector time was 43.725 seconds.

## Reproduction

```bash
source .venv/bin/activate
nice -n 10 python scripts/evaluate_selection_external.py \
  --theme-root research_local/external/theme_transformer \
  --theme-audit research_local/theme_annotation_input_audit.json \
  --jku-root research_local/external/jkupdd \
  --theme-prior research_local/theme_evaluation_v01 \
  --jku-prior research_local/jku_aligned_v01/aligned_indexed \
  --output research_local/selection_external_v01
python scripts/verify_experiment.py \
  --experiment research_local/selection_external_v01
```

The raw artifact retains every selected phrase and occurrence coordinate, exact note predictions, method telemetry, per annotation Theme scores and per representation JKU scores. The study does not assess memorability, perceptual phrase identity, complete Lakh behavior or POP909 part role accuracy.
