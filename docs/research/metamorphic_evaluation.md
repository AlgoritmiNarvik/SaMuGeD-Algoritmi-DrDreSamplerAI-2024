# Metamorphic evaluation of symbolic recurrence detectors

## Scope

This diagnostic asks whether three recurrence detectors return the same ranked
symbolic output after transformations that should preserve their musical input.
It uses the fixed 128 source cohort from `research_local/pilot_indexed_v01`.
The cohort and every source byte are bound in the experiment receipt before
detector execution.

This is an implementation invariance check. It does not measure whether a
selected phrase is musically important, memorable or correctly perceived by a
listener.

## Frozen design

The unchanged production implementations and default configurations are tested:

* reference approximate melodic extraction
* aligned indexed melodic extraction
* tolerant percussion extraction

Each source is parsed once. The baseline output is compared with outputs from
three in memory transformations:

* Tempo change modifies every tempo value while retaining PPQ and all symbolic
  event ticks.
* PPQ scaling doubles PPQ and every note, tempo and meter tick. Comparison maps
  all selected prototype and occurrence ticks back by exactly two.
* Melodic transposition adds five semitones to every non percussion note and
  retains percussion pitch IDs. Comparison subtracts five from melodic
  prototype pitches. A whole source is skipped for this transformation if any
  non percussion pitch is above 122, because the transformed MIDI pitch would
  exceed 127.

For every eligible detector and transform pair, the comparison requires exact
equality of the ranked phrase list after the declared inverse normalization.
This includes prototype fields, occurrence fields, scores, note counts and
ordering. Family ID order is checked separately and is expected to remain
stable because melodic family identity is transposition normalized and drum
identity retains kit pitch IDs. Search telemetry is reported separately and
does not determine the musical payload result.

The full 128 source cohort was retained because timings from the earlier paired
shortlist study implied a runtime below the predeclared 90 minute reduction
threshold. The process runs on one CPU at reduced priority.

## Results

The completed run contains 1,152 comparisons, comprising 128 sources, three
detectors and three transformations. All 1,152 comparisons passed exact
musical payload equality and exact family ID order equality. No source was
skipped because the cohort contained no non percussion pitch above 122. No
telemetry field changed.

| Detector | Sources with baseline phrases | Baseline selected phrases | Tempo failures | PPQ failures | Transposition failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference approximate | 126 | 376 | 0 | 0 | 0 |
| Aligned indexed | 127 | 379 | 0 | 0 | 0 |
| Tolerant percussion | 120 | 346 | 0 | 0 | 0 |

The empty baseline outputs are retained in the denominator. There were two for
the reference detector, one for aligned indexed and eight for percussion. The
result therefore includes both nonempty selections and deterministic empty
outputs rather than reporting only successful phrase extraction.

Search limits were present in three reference sources, 23 aligned indexed
sources and 20 percussion sources. The corresponding transformed runs reported
the same limits and the same output. This establishes invariance of the bounded
execution path for these transformations. It does not establish that the
selected phrases are complete when a search limit is reported.

Measured single process detector time was 419.39 seconds for the 384 baseline
runs and 1,262.43 seconds for the 1,152 transformed runs. These timings describe
this diagnostic execution order and machine load. They are not a controlled
performance benchmark.

The completion receipt verifies the frozen source snapshot and both result
artifacts. Key bindings are:

* Start receipt SHA256 `afe159d31c3a4410a252b2bc109187b706e658f69e6cf26b0105b62acc237692`
* Configuration SHA256 `917a69e56e96de62a2a53826cab3e96232fdb3d4897308811c00e17a79beac5b`
* Source snapshot SHA256 `5988ad71932d50c6d9a9cfa61b6bccdc7c7d2645ca56a8a3172514d204932769`
* Cohort SHA256 `fc7ec877de9775bd937737d28242673eca052fa195b39c3ff04bffdf606714b6`
* Raw result SHA256 `0f884c676d1421a038c9ec740806d20f9ba37bd3b0fcd25625e1001f5502797a`
* Aggregate SHA256 `5c03fa52c51519548d897d272361568b5c57f668e001a08e3be1ad71ea882115`

The source snapshot contains 13 files. It was created with the automatic static
local import closure and includes package initialization plus the transitive
local evaluator import.

## Interpretation limits

The study covers one fixed real source cohort and three exact symbolic
transformations. It does not cover lossy quantization, expressive timing edits,
instrument reassignment, bar origin changes or MIDI parser equivalence across
different encodings. Exact output equality is intentionally stricter than a
musical equivalence judgement. A failure can expose numerical sensitivity,
cap dependent search order or representation coupling, but it does not by
itself show a perceptually meaningful difference.

The detector configurations were not tuned after seeing these results. The
source snapshot supports replay of the executable study and its statically
reachable local imports. Third party package versions and dependency lock files
are recorded separately by the receipt.
