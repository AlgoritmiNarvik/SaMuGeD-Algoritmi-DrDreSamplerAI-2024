# Evaluation review

## Scope

This review audits the frozen local drum run in `research_local/drum_evaluation_v01` and the frozen melodic run in `research_local/evaluation_v01`. It does not change detector settings, cases, thresholds or measured outcomes.

The drum overlap audit uses the `symbolic_sha256` stored for every case. That signature hashes PPQ, meter events and exact note start, end, pitch and velocity. It proves exact symbolic equality when two hashes match. It is stricter than musical or perceptual equivalence, so it can miss grooves that differ only through a small quantization change, velocity or PPQ representation.

The melodic arrangement check loaded the 1,000 saved case MIDI files and hashed the same exact symbolic fields. All files were present. This was a read only check and was not added to the melodic benchmark output.

## Drum arrangement overlap

The two RNG seed namespaces are disjoint. Their generated arrangements are not disjoint.

| Measure | Result |
| --- | ---: |
| Cases | 1,000 |
| Unique exact symbolic arrangements | 955 |
| Duplicate case excess | 45 |
| Duplicate arrangement groups | 44 |
| Largest duplicate group | 3 cases |
| Development cases and unique arrangements | 500 and 488 |
| Test cases and unique arrangements | 500 and 487 |
| Exact arrangements shared across splits | 20 |
| Cases in those cross split groups | 40 |
| Share of each split in a cross split group | 4.0% |
| RNG seed values shared across splits | 0 |

There are 467 unique test signatures absent from development. At the case level, 480 of 500 test cases have a signature absent from development. The difference comes from 13 duplicate case excess within the test split.

| Condition | Cases | Unique arrangements | Shared across splits |
| --- | ---: | ---: | ---: |
| Changed instrument negative | 84 | 79 | 2 |
| Exact 1 bar | 84 | 78 | 2 |
| Exact 2 bar | 84 | 77 | 5 |
| Exact 4 bar | 84 | 82 | 0 |
| Extra strike | 84 | 82 | 1 |
| Independent rhythm negative | 82 | 78 | 2 |
| Meter change | 82 | 78 | 2 |
| Missing strike | 84 | 81 | 2 |
| PPQ variation | 82 | 82 | 0 |
| Shuffled rhythm negative | 84 | 81 | 1 |
| Simultaneous hits | 82 | 75 | 3 |
| Timing jitter | 84 | 84 | 0 |

The supplementary audit in `aggregate.json` contains the 20 exact signatures and every associated case ID and seed. It also records per split and per condition counts. The raw results and detector metrics were retained.

### Statistical interpretation

The drum test split is not fully arrangement independent. Calling it an independent held out arrangement cohort would be inaccurate. Separate seed namespaces establish separate random number streams, not separate generated outcomes.

There is no statistical model fitting inside this evaluation and the detector configurations were frozen. Exact cross split duplicates therefore do not create the usual training example leakage. They still matter in two ways:

1. Repeated arrangements reduce sample diversity. The test split has 487 unique exact arrangements rather than 500 independent arrangements.
2. The case bootstrap samples duplicate arrangements as if each were an independent observation. Its intervals can be narrower than a cluster bootstrap by arrangement signature.

The negative test denominator is 125 cases but only 122 unique exact arrangements. Five negative arrangements also occur in development. The reported zero false positive Wilson upper bound is 2.98% using 125 cases. As a simple sensitivity check, using 122 exact unique negative arrangements gives 3.05%. This small numerical change does not address near duplicates that the exact signature cannot detect.

The measured test outcomes remain valid descriptions of this generated case set. They support statements about the frozen interventions. They do not establish specificity on independent real songs or a general distribution of drum grooves.

## Melodic arrangement and seed audit

The melodic run has 1,000 unique exact full song arrangements among 1,000 saved cases. There are no exact cross split arrangement matches and no RNG seed values shared between development and test. The documented seed namespace separation is correct for this run.

Exact uniqueness does not imply broad musical independence. Every case comes from the same generator, pitch step set, context process and finite list of interventions. The test split samples the same condition distributions and perturbation ranges as development. It is a held out random seed cohort within that generator, not an external validation distribution.

The frozen melodic test split contains 423 positive and 77 negative cases. Approximate mode recovered 318 of 423 positive cases, with candidate F1 0.687 and occurrence F1 0.685. It returned candidates in 0 of 77 negative cases. A two sided 95% Wilson interval for 0 of 77 has an upper bound of 4.75%. The saved case bootstrap reports `[0, 0]` for the false positive rate because resampling cannot create an event that was never observed. That bootstrap interval should not be read as evidence that the population false positive rate is zero.

## Melodic metric weaknesses

### Truth boundaries depend on planted notes

Positive truth intervals are the minimum start and maximum end of each planted note list. Detector windows are also constructed from note starts and ends. Boundary recovery is therefore partly coupled to the generator and detector representation. The benchmark does not independently annotate musically appropriate phrase boundaries.

### Candidate recovery allows extra occurrences

A family is marked correct when its predicted occurrences match every planted interval. The definition does not require the predicted family to have the same number of occurrences as truth. A family with all planted occurrences plus extra occurrences is a candidate true positive. The occurrence metric counts extras as false positives, so candidate recovery and occurrence precision answer different questions.

### Greedy interval assignment is not guaranteed to maximize matches

The melodic scorer sorts all interval pairs by IoU and accepts the highest available pair. Greedy weighted assignment is not guaranteed to produce the maximum cardinality one to one matching for every possible overlap graph. A later [independent metric audit](melodic_metric_audit.md) checked all 7,000 score rows in the three preferred frozen melodic evaluations. Every predicted interval had at most one eligible truth interval at IoU 0.8. Greedy and maximum cardinality matching therefore agree on match counts for these rows; saved coordinates, rounded IoUs, recovery ranks and totals also matched. The generic limitation remains for future cases with ambiguous or overlapping intervals and is covered by an adversarial regression. The drum scorer already uses augmenting path matching.

### Negative coverage is narrow

Only `rhythm_negative` and `random_negative` are negative conditions. They contribute 77 test cases, compared with 423 positive cases. The rhythm negative preserves a pitch sequence while stretching timing, and the random negative follows one deterministic structural formula with seeded timing choices. These are useful controls but do not represent the range of repeated nonphrase material in real MIDI.

The statement “0 false positive cases” must retain its denominator and uncertainty. It means 0 of 77 under these two mechanisms. It does not mean a zero false positive rate on a corpus.

### Perturbations align with detector tolerances

Jitter is generated within the approximate timing tolerance. Duration changes are generated within the duration tolerance. The pitch mutation count is compatible with the configured pitch error fraction for supported lengths. These are appropriate in range controls, but perfect or high recovery on them mainly confirms implementation against its designed operating range.

Development and test use the same perturbation distributions. The split does not test tolerance to a shifted or unseen perturbation process.

### Some conditions are structurally easy

The polyphonic chord case adds notes below every planted melody note. Skyline selection chooses the planted top note by construction. This validates the intended skyline path but does not test melody extraction when accompaniment crosses above the melody, shares its register or has independent onset density.

The meter and PPQ case changes the meter at the second motif start. Melodic matching itself is note window based, while meter mainly affects boundary scoring. The case confirms representation consistency more strongly than it tests segmentation through a meter transition.

### Aggregate recall mixes supported and known unsupported cases

Inserted and deleted note cases are positive even though the fixed length matcher explicitly lacks insertion and deletion alignment. Including them in total recall is honest if the aggregate is interpreted as end to end coverage. It should not be presented as an estimate of accuracy within the detector's supported matching model. The per condition table is needed to separate designed support from documented limitations.

### Bootstrap uncertainty is conditional on the generator

The case bootstrap treats generated cases as exchangeable and independent. It measures variation within the frozen mixture of synthetic conditions. It does not include uncertainty about condition choice, generator realism, thresholds, annotation policy or real corpus prevalence. For the zero negative result it is degenerate, as described above.

### Legacy results are not a direct accuracy comparison

The legacy method runs on a 24 case subset and does not emit occurrence coordinates. The current report correctly avoids candidate and occurrence F1 for that method. Its prototype coverage and runtime should remain separate from the main detector metrics.

## Claim boundaries

The evaluations support these claims:

- The frozen exact and tolerant drum modes behave as measured on the planted interventions.
- The tolerant drum mode accepts the designed jitter and one strike variations and rejects the three designed negative mechanisms in this run.
- The melodic modes behave as measured on 1,000 exact unique arrangements from the frozen melodic generator.
- Neither run encountered configured search limits on these short synthetic cases.

They do not support these claims:

- The drum test split is fully arrangement independent from development.
- A zero real corpus false positive rate has been established.
- Synthetic bootstrap intervals describe uncertainty on real music.
- Recovered recurrence is a hook, an earworm or a memorable phrase.
- Piano roll recurrence quality has been validated by human annotators.

For future evaluation, preserve the frozen runs and add new versioned evidence. Group splitting by generated arrangement signature before evaluation would remove exact cross split drum overlap. Cluster bootstrap by signature would avoid treating exact duplicates as independent. A larger independent negative suite, external MIDI structures and two annotator review should remain separate from detector tuning.
