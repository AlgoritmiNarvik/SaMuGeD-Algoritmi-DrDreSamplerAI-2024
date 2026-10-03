# Certified drum controls

This study defines a bounded symbolic control cohort for the unchanged exact and tolerant drum extractors. It is an algorithm independent control of one stated admissibility rule. It is not a real corpus specificity estimate, a listening study or evidence of musical quality.

## Frozen control rule

The generator uses a new namespace, `samuged-certified-drums-v1`, and deterministic standard library `random.Random` seeds derived from the namespace, split, case kind, case index and generation attempt. It covers 240 certified negatives, 120 for development and 120 for test. It also creates 120 planted positives, 60 for each split. Each accepted file has 16 to 32 bars, one of 4/4, 3/4, 6/8 or 7/8 and one of PPQ 96, 480 or 960.

The negative label is accepted only when `samuged.drum_oracle.enumerate_windows` and `enumerate_admissible_pairs` find zero admissible nonoverlapping pairs for one, two and four bar windows. The oracle uses a 1/12 beat onset tolerance, a ten percent maximum hit edit rule, at least eight hits and two pitches. For each small generated song the runner derives the finite number of within bucket window pairs and passes that exact number as the comparison limit, so every eligible pair is compared without a truncation cap. A candidate is accepted only when `pair_budget_reached` is false and `exhaustive_pair_enumeration` is true. Repeated exact and beat normalized arrangement hashes are rejected across all accepted controls. Generation stops with an error after 10,000 attempts instead of silently substituting cases.

Each planted positive contains three exact copies of a known one, two or four bar region. The target interval pairs are retained as labels only after the oracle confirms every target pair. Detector positive coverage is reported as the fraction of those labelled oracle edges that appear as direct prototype to occurrence edges in a returned family. This definition avoids treating any cross occurrence family pair as a direct detector match.

## Reproduction and outputs

Run the study from the repository root after activating the project environment:

```sh
source .venv/bin/activate
python scripts/evaluate_certified_drums.py \
  --output research_local/certified_drums_v01
```

The output directory must be new or empty. The start receipt and executable source snapshot are written before either detector mode runs. All generated MIDI files, the frozen design, oracle labels, raw rows and aggregate results are bound by the completion receipt. The result directory is intentionally ignored under `research_local/`.

## Completed v01 results

The completed output is `research_local/certified_drums_v01`. It contains 360 cases: 120 development negatives, 120 heldout negatives, 60 development positives and 60 heldout positives. Generation accepted all 360 first attempts, with 360 attempts and zero rejections against the 10,000 attempt cap. Exact and beat normalized arrangement hashes are each unique across all 360 cases.

The runner constructs the design in memory before calling the deterministic cohort generator. Its on-disk start receipt is written after the cohort has been generated and before either detector runs, so v01 proves a frozen detector-blind cohort and design snapshot but does not prove an on-disk pre-generation receipt. A future run should persist the pre-generation design and source receipt before candidate generation if that stronger ordering claim is required.

The preferred heldout denominator is the 120 certified negatives in the test split. Both exact and tolerant modes produced 0/120 negative outputs, with a Wilson 95% interval of `[0.000000, 0.031019]` for the output rate. The pooled 0/240 result has interval `[0.000000, 0.015754]` and is supplemental because development and heldout cases share the frozen generator and namespace. No detector search or candidate limit was reached. Heldout positive direct edge coverage is 120/180 labelled target oracle edges per mode (66.6667%), while pooled coverage is 240/360. This edge metric does not say that only two of the three planted target windows were recovered by a family.

The independent oracle compared 220,254 nonoverlapping eligible window pairs across the cohort. The finite exhaustive pair budgets totalled 246,762 comparisons, with a maximum per case of 1,367; no case reached its budget and all 240 negatives had zero admissible pairs. Generation and detector runtimes are recorded in `aggregate.json` and are environment measurements rather than scientific quantities.

Key integrity values are the source snapshot SHA256 `8179baa2f9f9977a2fba09c32468042fbffd3c7ffd16a950821ec1b6db00be0d`, aggregate SHA256 `28d2f8b6260f58cf8a5d0d41a5b1c6260ea90ed5dd142094f0ea87611116bcc6`, labels SHA256 `4703639dbb3fe1fe1d242c9aefb8f8783e0ac0133dd632477140d7b8d185fd27` and completion receipt SHA256 `9c2935fc4f8a0eb7499392274c76ec4ac66f1c2a21a2b57cda3d70b29286cf96`. The result links use receipt hash `de1960c65ab8daf3e5755eea9e42006008a65204fee3c33ceb97ac09185f3266`.

`research_local/certified_drums_audit_v01` independently rechecked all 360 saved MIDIs with the frozen source snapshot, recomputed all arrangement hashes and oracle certificates and replayed both detector modes. One returned family covered all three labelled target windows in 60/60 development and 60/60 test cases for both modes. This family result is separate from direct prototype edge coverage, which was 120/180 heldout target edges per mode because a three window family contributes two direct prototype to occurrence edges. The audit bound its input manifest to the v01 completion receipt and source snapshot. Its audit SHA256 is `0a39ed197215163fa3a90b6ffb5b530688926e01ec00cf36c45fe32dd0fb9257`.

The aggregate reports negative output rate with a Wilson 95 percent interval for each detector mode and split. It also reports positive target edge coverage, oracle pair counts, pair budget status, detector search limits, candidate limits, runtimes and arrangement uniqueness. `raw_results.json` retains per case detector statistics and the frozen oracle labels without embedding unbounded detector phrase payloads.

The stricter root replay at `research_local/certified_drums_strict_root_v01` also passed all 360 cases. It validates embedded design and configuration semantics against the frozen receipt, recomputes observable generation counters and fails on detector telemetry mismatches. Its audit SHA256 is `a53316d6353e85ef9539f3eaf5d9fb6706d05d08414322efa1e42054ea80a801`. The focused regression suite passed 15 tests, including changed design bodies with rebound artifact hashes. Rejected generation attempts are not saved individually, so their history cannot be reconstructed from accepted cases alone. The completed v01 cohort had no rejected attempts.

## Interpretation limits

The negative cohort is conditioned on the independent symbolic oracle finding no admissible repeated windows. That conditioning creates distribution bias and can remove hard negatives that contain shorter or approximate repetitions under this rule. The controls therefore test the declared symbolic boundary and the detector's behavior on that boundary. They do not support a claim about real world false positive rates, song level precision or human judgments. The existing stress results remain separate historical diagnostics.
