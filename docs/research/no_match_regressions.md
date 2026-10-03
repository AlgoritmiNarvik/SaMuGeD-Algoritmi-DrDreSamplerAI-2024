# Three aligned no-match regressions

## Finding

All three cases are candidate generation recall failures. They are not
differences between the reference matcher and the aligned final matching
rules. The saved reference occurrence pair passes the reference verifier, the
aligned dynamic verifier and the aligned timing first anchor verifier in every
case. The pair is never proposed because it has fewer than the configured
three shared seed keys.

The same result occurs with `aligned` and `aligned_indexed`. The exact first
cache in `aligned_indexed` is therefore not the cause. Both implementations
share the seed index and its minimum support rule. The aligned module already
states that heuristic anchors can miss valid alignments. These three corpus
examples show a concrete mismatch between that candidate heuristic and the
final verifier on short phrases.

| Source | Notes | Reference similarity | Aligned similarity | Aligned edits | Shared seed votes | Required votes | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `Nat_King_Cole/Nature_Boy.mid` | 8 | 0.812500 | 0.821354 | 1 | 2 | 3 | pair split into separate groups |
| `Bilk/What_Are_You_Doing_the_Rest_of_Your_Life.mid` | 6 | 0.825556 | 0.843333 | 0 | 0 | 3 | pair split into separate groups |
| `Evans_Bill/All_the_Things_You_Are.mid` | 8 | 0.776042 | 0.786458 | 1 | 0 | 3 | pair split into separate groups |

The indexed replay reproduced every frozen candidate generation counter for
each source, including window, group, proposal and rejection counts. At the
second saved occurrence, the first occurrence's group received 2, 0 and 0
votes respectively. Each second occurrence therefore created a new singleton
group. The later terminal timing, pitch feasibility and anchor alignment
checks were not reached for these pairs.

## Cause evidence

`Nature_Boy.mid` has one pitch substitution under a fixed shift of five
semitones. The aligned verifier permits one edit for an eight note window and
accepts the pair. The bounded paired anchor descriptors yield only two shared
phase keys. Counting phase keys requires three votes, so the valid pair is
missed.

The other two misses expose a separate mismatch. Every seed key includes a
quantized full span computed from onset plus duration, while the verifier
constrains terminal onset and tolerates bounded duration errors.

| Source | Full spans in beats | Shared complete keys | Shared keys with span bucket projected out |
| --- | --- | ---: | ---: |
| `What_Are_You_Doing_the_Rest_of_Your_Life.mid` | 5.108333, 4.375000 | 0 | 6 |
| `All_the_Things_You_Are.mid` | 5.062500, 4.432292 | 0 | 6 |

The Bilk pair has no pitch edits. Its maximum duration error is 0.8 beats but
its mean duration error is 0.213889 beats, so it remains valid under the frozen
duration rule. The Evans pair has one pitch substitution, terminal onset error
0.09375 beats and maximum timing error 0.119792 beats, all within the frozen
aligned bounds. Removing only the span component from the diagnostic key
projection restores six collisions in both cases. This projection was used
only to identify the failed component. It did not generate or accept a
candidate.

Both complete detector replays returned no phrases with `search_limited=false`.
The absence is therefore unrelated to window, group, comparison or posting
caps. The unindexed replay also made zero dynamic programming calls because
the target pairs were separated during group construction.

## Recommendation

This warrants a bounded follow up if recall for short reference style motifs
is part of the detector objective. A principled change is to make candidate
keys depend on constraints that the final verifier enforces. One option is a
short window rescue index based on individual three note pitch and rhythm
anchors, with support counted across distinct anchor offsets. Its span cue
should use terminal onset or include a span relaxed variant because note end
duration is deliberately tolerant in the verifier. Existing posting caps and
the unchanged final verifier can still bound work and decide acceptance.

Simply lowering `min_seed_support` from three to two is not well justified.
The current votes include phase variants, so two votes need not represent two
independent musical anchors. Any implementation should first be evaluated on
the frozen development and stress cohorts for recall, comparison growth,
bucket saturation and false candidate work. It should not silently invoke the
reference detector as a fallback.

## Method and provenance

The diagnostic reconstructs each saved reference window from the original
part skyline, saved note index and note count. It requires exact saved source
coordinates and prototype pitches. It then runs the reference matcher, the
aligned direct and anchor verifiers, an independent indexed candidate
generation trace and complete `aligned` and `aligned_indexed` extraction.
Indexed output and statistics must equal the frozen record. Every input hash is
checked again after detector execution.

The completed local study is
`research_local/no_match_regressions_v01`. Its start receipt SHA-256 is
`aa775fee016c21b1a625002bec074919def196db88499067567a67f2d9202fa0` and
its executable snapshot SHA-256 is
`3db32f615cdff4a0413d9f3c28e5222d56a32fce488e8a725b78b5cceacf8acf`.
The completion receipt binds:

- `raw_results.json`: `1926135814c27a6b19f67f32de5fb4005b051a3bdcb677e5f11250a6de11b48a`
- `aggregate.json`: `6f990447bd72a40dd4154e69946221619c81dd72633ac6eeedcff9c70e79e071`
- `input_manifest.json`: `f5cac04700fdbdba37962afcdacc28030e8882b9f5d5d2c38691e5243f95ec8c`

The input manifest binds the three MIDI bytes, six source records, both clean
dataset audit receipts and build configurations and the completed full
comparison receipt and raw result. The three source SHA-256 values match the
saved dataset records. This is a three case causal diagnostic, not an estimate
of corpus recall, musical quality or human relevance.

An independent root replay at `research_local/no_match_regressions_root_v01`
reproduces all three raw case rows exactly, including complete detector
outputs and the candidate generation traces. Both completion receipts verify.
The root completion SHA256 is
`7094f1ca1d4dedf760e7b0c811035fd0036c83cf4c0f17fed63e1c4df479d387`;
the comparison receipt is `research_local/no_match_regressions_root_check_v01.json`.

Reproduce it from the repository root with:

```bash
source .venv/bin/activate
python scripts/audit_no_match_regressions.py \
  --reference research_local/lakh_phrases_v03 \
  --indexed research_local/lakh_aligned_indexed_v01 \
  --comparison research_local/indexed_full_comparison_v02/raw_results.json \
  --source-root 'datasets/Lakh MIDI Clean' \
  --output research_local/no_match_regressions_v01
```

The output directory must be absent or empty because the start receipt is
immutable.
