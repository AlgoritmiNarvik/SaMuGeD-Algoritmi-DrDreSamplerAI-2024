# Optional melodic part prior

## Question and claim boundary

The aligned closed detector ranks recurrence candidates without an explicit melodic part prior. This study asks whether a small prior based only on source note structure makes the first selected phrase agree more often with the official POP909 `MELODY` track label.

The label is a dataset part role. It does not establish hook quality, phrase boundary accuracy or human memorability. `BRIDGE` and `PIANO` riffs may be useful sampling material. The method therefore remains optional.

## Frozen data and procedure

The input contains 180 official POP909 multitrack MIDI files from upstream commit `d83e6edba6872a704f5d3b8b32f5cb540088dae6`. The six previously inspected songs `065`, `284`, `310`, `422`, `449` and `464` were excluded. A deterministic hash order assigned the first 60 files to development and the next 120 files to heldout evaluation.

The source files and split are recorded in `research_local/external/pop909_role_v01`. Exact input hashes are in the start receipt. The study receipt froze the source code, detector configuration, preset grid and cohort before detection.

For every song, aligned indexed detection generated one candidate list. The baseline applied the unchanged closed exact pattern selector. The optional method added a part score to candidate ordering, then applied the same redundancy and closed extension rules. Both methods selected three phrases from the same generated list. The reranking operated on the full retained shortlist, after the detector's existing limit of 80 candidates per part.

The features use pitches and timing only:

- onset monophony, the ratio of near onset groups to notes
- voice independence, computed from the number of notes active at each group onset
- a broad onset density fit
- continuity from inter onset gaps
- median register
- skyline pitch mobility

Track names, source track numbers, channels and programs were blanked before detection and feature calculation. Unit tests check invariance to those fields and compare the active voice heap sweep with a brute force reference.

Eight rules were declared before fitting. Development selection maximized top one `MELODY` agreement, then top three agreement, fewer changed outputs, lower strength and declaration order. The selected rule used only onset monophony with weight 0.65 and voice independence with weight 0.35. Its additive strength was 0.08:

`adjusted score = recurrence score + 0.08 * (part prior - 0.5)`

The selected rule was written to `frozen_rule.json`. The evaluator then wrote and hashed all 120 heldout predictions without role labels. It dereferenced the source part names and scored the heldout set only after that freeze. The source MIDI files necessarily contain the role names, so this is a procedural and code enforced boundary rather than physical label removal.

## Development fit

| Preset | Strength | Top one MELODY | Top three MELODY | Changed songs |
| --- | ---: | ---: | ---: | ---: |
| none | 0.00 | 35/60 | 51/60 | 0 |
| monophony weak | 0.04 | 47/60 | 58/60 | 33 |
| monophony | 0.08 | 57/60 | 60/60 | 38 |
| structure weak | 0.04 | 39/60 | 55/60 | 23 |
| structure | 0.08 | 44/60 | 58/60 | 33 |
| balanced weak | 0.04 | 38/60 | 54/60 | 20 |
| balanced | 0.08 | 40/60 | 57/60 | 30 |
| register weak | 0.04 | 38/60 | 54/60 | 20 |

These are tuning results and should not be read as independent evidence.

Development tests also cover four designed counterexamples. A low monophonic line ranks above a higher chordal accompaniment, a dense melody ranks above a sparse bridge without a register cue, a single part preserves baseline selection under the zero prior and a polyphonic representation receives a lower monophony score. These tests establish intended mechanics only.

## Heldout results

| Metric on 120 heldout songs | Baseline | Optional prior | Paired difference, 95% bootstrap interval |
| --- | ---: | ---: | ---: |
| Top one is `MELODY` | 76/120, 63.3% | 110/120, 91.7% | +28.3 points, [20.8, 36.7] |
| Top three contain `MELODY` | 102/120, 85.0% | 119/120, 99.2% | +14.2 points, [8.3, 20.8] |

Intervals use 10,000 paired song bootstrap samples with seeds `20261003` and `20261004`. The optional rule changed the selected three phrase set on 73 of 120 songs and changed the top part on 35. Of those top part changes, 34 moved a non `MELODY` baseline result to `MELODY`; none moved a baseline `MELODY` result away from that role. One change moved `PIANO` to `BRIDGE`. Song `637` remained the only heldout song without `MELODY` in the selected three, although a `MELODY` candidate existed in its retained shortlist.

Every baseline and optional run returned exactly three phrases. The candidate shortlist contained a mean of 216.9 candidates per heldout song. All 120 heldout songs had at least one part whose candidates were truncated, 319 of 360 part shortlists reached the 80 candidate cap and three songs were search limited. These limits mean this study evaluates reranking within the retained candidates, not exhaustive part selection.

Summed detector elapsed time was 350.5 seconds for all 180 files in one reduced priority process. Mean heldout selection time was 0.31 ms for the baseline and 2.02 ms for the optional prior. Candidate generation dominates runtime.

## Decision

The heldout result supports keeping the note structure prior as an optional part preference. It should not replace the default detector ranking because the target is POP909 role agreement and the reranking changed 61% of heldout phrase sets. A sampling workflow may reasonably prefer recurring accompaniment. External phrase annotations or listener judgments would be needed for a phrase quality claim.

## Reproduction and integrity

Run from the repository root after activating the environment:

```bash
source .venv/bin/activate
nice -n 10 python scripts/evaluate_part_ranking.py \
  --input research_local/external/pop909_role_v01 \
  --output research_local/part_ranking_v01
python scripts/verify_experiment.py \
  --experiment research_local/part_ranking_v01
pytest -q tests/test_part_ranking.py
```

The focused test result is 12 passed. The completed study has these identifiers:

- start receipt SHA256: `4f62de29a8b4d64f8b79490ebacb4578587d496d01cdd7a75418211f2caa8110`
- source snapshot SHA256: `3d8a00f820cfdbef4e712729fed8180fe0bdf10e62750c8b211fe69118a4fe5a`
- frozen rule SHA256: `009ace34be44a7a1b2fbf6be369a72c3aef0ec9feb627f1e3c35712019d78648`
- role free heldout predictions SHA256: `da3157d803bf994ebc35e012034d0a417643d8d7cf2e21e98b02be218ceb7d90`
- raw results SHA256: `c11d3d55465710cdb38a1dce822a1be1c13cab11c8ab0b1d10a7384092b5be69`
- aggregate SHA256: `6c457223f0f693c66e155adf604fc2e17fa105f884fde8aca9aad690e41aea71`

The frozen study module is `1190ea84b15d1c52c2623153adac63ee5d947963fcc63d0fb2268807bf28c209`. The evaluator is `fe4ccaee7218454c60d114cf2e9b634dac7a830d187d59119a35ac8602f1eb49`. Their exact experiment copies are retained under `research_local/part_ranking_v01/source_snapshot`.

## Optional build integration

The module hash in the preceding section identifies the frozen study implementation. The integrated module differs because it adds the build wrapper and causal evidence fields while preserving the fitted features and rule.

The fixed `monophony` preset is available through the explicit `aligned_melody` algorithm. The default remains `reference`. `aligned_closed` also retains its prior behavior. A local build can request the optional prior as follows:

```bash
source .venv/bin/activate
python -m samuged.cli build \
  --source /path/to/midi \
  --output research_local/aligned_melody_dataset \
  --algorithm aligned_melody \
  --percussion \
  --recover-invalid-keys
```

The implementation generates the full retained `aligned_indexed` candidate list for every nondrum part. It applies the fixed 0.08 note structure prior, then the frozen closed exact extension selector. Recurrence scores are preserved. Each source record contains the fixed prior configuration, recomputed part features and scores, selected candidate ranks, adjusted scores, replacement events and a SHA256 digest of the complete ordered candidate evidence. An ordinary audit recomputes source note features and selected adjusted scores. A reextraction audit regenerates the candidates and checks the complete evidence and final selection. The closed selector trace validator is not applied to this differently ordered traversal.

The POP909 study blanked track names, programs, channels and source track numbers after parsing and before candidate generation. Ordinary Lakh builds retain those fields in the output. The part prior reads pitches and note timing only; the aligned recurrence score uses matching quality, support, duration and boundaries, without an instrument term. The separate reference detector does have an instrument prior. POP909 role agreement therefore supports the optional note structure preference, while agreement with melodic roles on Lakh remains unmeasured.

The fixed 128 file Lakh pilot in `research_local/pilot_melody_v01` used the same source paths and aligned configuration as `research_local/pilot_closed_v01`. The aligned, indexed, closed, MIDI and drum source snapshot hashes were identical across both builds. Candidate counts and all saved per part search telemetry were equal for every file. Both builds produced 379 melodic and 346 percussion phrases, reported 23 melodic search limited files and 125 files whose candidate lists reached the curation limit. The optional prior changed the ordered melodic source selection in 90 of 128 files, the selected set in 83 files and the top phrase in 52 files. The top phrase moved to another part in 49 files. These changes have no Lakh accuracy labels and are reported only as selection side effects. Drum statistics and percussion payloads were identical for all 128 files.

The optional pilot took 109.868 seconds wall time and 422.058 worker seconds. The fixed closed pilot took 109.081 seconds and 418.650 worker seconds on the same cohort. This single paired run observed increases of 0.72% wall time and 0.81% worker time. It is not a controlled runtime benchmark. The optional build passed schema validation for 128 source rows and 725 phrase rows, followed by a full reextraction audit of all 725 exported MIDI files with no failures. Its run key is `6ae89edaea51de7b4dfbda9c12dc0500d2685a72c06fa877c597ca8fcff296e5`.

The pilot snapshot predates the later runtime fingerprint field. New builds record the Python implementation, Python version and installed Mido version in `build_config.json`, bind them into the run key and reject resume or audit under a different recorded numeric runtime. Older frozen datasets retain their prior run key contract and continue to audit. Git metadata collection is descriptive and now stays quiet when the package runs outside a Git checkout.
