# Part ranking study audit

## Scope

This is an independent audit of `research_local/part_ranking_v01`. It checks
the saved development decision, heldout prediction boundary, structural
features, selected phrase identities and reported role agreement. It does not
change the detector, prior, study artifacts or paper.

The original completion receipt verifies successfully. The audit rechecked all
180 MIDI hashes and the three input manifest hashes before and after replay.
The current working copy of `samuged/part_ranking.py` differs from the study
snapshot, so replay loaded the exact saved package snapshot. The loaded frozen
module SHA256 is
`1190ea84b15d1c52c2623153adac63ee5d947963fcc63d0fb2268807bf28c209`.
The current working copy SHA256 during this audit was
`78dba3ec4f90ff75b46a30ad8a6c7e58cdcfc6b8d5f2a28743e04665904c14fc`.
All other saved source files matched their live counterparts at audit start.

## Verified design and execution

The frozen cohort contains 60 development songs followed by 120 heldout songs,
with no duplicate song IDs. Its order and split agree with the hash ranked
selection manifest. The start receipt contains all eight complete prior
presets, the detector configuration and the deterministic selection rule.

The audit independently replayed candidate detection on all 60 development
songs. Every candidate digest matched. It applied all eight declared presets,
reconstructed their development metrics and recovered the saved fit table
exactly.

| Preset | Top 1 MELODY | Top 3 MELODY | Changed songs |
| --- | ---: | ---: | ---: |
| None | 35 | 51 | 0 |
| Monophony weak | 47 | 58 | 33 |
| Monophony | 57 | 60 | 38 |
| Structure weak | 39 | 55 | 23 |
| Structure | 44 | 58 | 33 |
| Balanced weak | 38 | 54 | 20 |
| Balanced | 40 | 57 | 30 |
| Register weak | 38 | 54 | 20 |

The independently applied tie key selected `monophony`. It wins the primary
development criterion by ten songs, so later tie breakers do not determine the
winner in this run. The frozen rule and aggregate contain the same preset and
full configuration.

The audit reconstructed note structure features and weighted part scores for
all 180 songs without using saved feature values. All values matched. It also
verified that the object passed to detection and feature scoring had blank part
names and zeroed track, channel and program fields while preserving notes,
part indices, drum flags, tempo and meter.

This metadata blanking did not alter candidate generation in the frozen study.
The aligned indexed detector delegates recurrence scoring to the frozen aligned
scorer, whose score contains match quality, support, note length and boundary
terms only. Track, channel, program and part name are copied to output fields
but are not read by its detector or score. The 540 original nondrum POP909
parts also all had program 0, although their channels and source tracks varied.
The study's structural part prior likewise excludes these metadata fields.

All 180 saved baseline and selected prior family lists matched their phrase
summaries. Every selected phrase refers to an available nondrum part, starts on
a source note onset and ends on a source note end. Candidate count and complete
candidate part index sequences are valid for all songs.

The study does not save the full candidate family IDs or occurrence coordinates.
It saves a SHA256 over those identities and coordinates. This audit reproduced
all 60 development candidate digests and 12 deterministic, stratified heldout
digests covering improvements, unchanged correct results, changed correct
results and incorrect results. Full human readable candidate inspection for
the remaining 108 heldout songs would require detector replay because the
underlying candidate identities are not present in the artifact. This is an
auditability limitation, not an observed mismatch.

## Heldout boundary

The heldout prediction artifact contains 120 rows in the frozen cohort order.
It contains no role map, role labels or scored correctness fields. Each row is
an exact role free predecessor of the corresponding scored raw row after the
documented scoring fields are removed and the selected prior is placed back in
its prediction structure. Its SHA256 is referenced by both raw results and the
aggregate.

The frozen code writes and hashes this artifact before it reads the source
manifest or reloads MIDI names for heldout role scoring. This verifies a process
boundary. It is not physical blindness. Official role names already existed in
the local MIDI files and source manifest before execution. The study code had
filesystem access to those files even though the executed prediction path
stripped and deferred their labels.

## Independent metric reconstruction

Every saved role map agrees with both the source MIDI and the input manifest.
All baseline and prior labels, top 1 and top 3 totals and paired bootstraps were
independently reconstructed.

| Split | Baseline top 1 | Prior top 1 | Difference | Baseline top 3 | Prior top 3 | Difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, 60 songs | 35 | 57 | +22 | 51 | 60 | +9 |
| Heldout, 120 songs | 76 | 110 | +34 | 102 | 119 | +17 |

The heldout top 1 transition table is:

| Baseline result | Prior result | Songs |
| --- | --- | ---: |
| Incorrect | Incorrect | 10 |
| Incorrect | Correct | 34 |
| Correct | Correct | 76 |
| Correct | Incorrect | 0 |

The reported gain of 34 of 120 is arithmetically correct. It consists of 34
improvements and no regressions under the official MELODY role label. The
independent paired song bootstrap also matches:

* Top 1 difference 0.28333333, 95% percentile interval [0.20833333, 0.36666667]
* Top 3 difference 0.14166667, 95% percentile interval [0.08333333, 0.20833333]

This evidence supports a source role preference claim within this POP909
selection. It does not show that the selected phrase is a hook, a good sample
or the most musically salient recurrence.

## Material limitations

All 180 songs report candidate curation truncation. Three development and three
heldout songs also report a search limit. The result therefore describes
reranking of bounded detector shortlists, not all possible candidates.

Top 3 is presence in three selected phrase slots, not coverage of three distinct
parts. On heldout songs, the baseline selects all three phrases from one part in
45 of 120 cases. The prior does so in 66 cases, and in 65 of those all three
phrases come from the MELODY part. The top 3 increase is internally consistent
but partly reflects repeated selection from the preferred part.

The official MELODY label is a role label supplied by the dataset author. It is
not an annotation of hook quality, recurrence quality or memorability. BRIDGE
and PIANO phrases can still be valid recurring material for the intended
sampling dataset.

Preset selection uses development role labels as intended. The saved execution
and role free prediction artifact show no heldout label dependent choice after
the rule was frozen. Because all labels and files existed locally beforehand,
the result should be described as process separated heldout evaluation rather
than physically blind evaluation.

The metadata treatment still limits transfer claims. Ordinary source builds
retain track, channel, program and part name, while this experiment explicitly
blanked them. For the exact frozen aligned indexed detector and POP909 cohort,
that difference is inert for candidate identities and recurrence scores. It
does not establish invariance for other algorithms. In particular, the
reference detector's recurrence score includes a program based instrument
prior. The result therefore supports the tested aligned indexed candidate
generator plus metadata free reranker, not a claim that every Lakh build path
uses the same scoring pipeline. Lakh performance and the effect of its broader
instrument distribution remain unmeasured here.

## Receipts

Original study bindings:

* Start receipt SHA256 `4f62de29a8b4d64f8b79490ebacb4578587d496d01cdd7a75418211f2caa8110`
* Completion receipt SHA256 `245433043b52ddfb8495f384db29a140897cb53dc2119f2fabe0b58d5b4b6677`
* Frozen rule SHA256 `009ace34be44a7a1b2fbf6be369a72c3aef0ec9feb627f1e3c35712019d78648`
* Heldout predictions SHA256 `da3157d803bf994ebc35e012034d0a417643d8d7cf2e21e98b02be218ceb7d90`
* Raw results SHA256 `c11d3d55465710cdb38a1dce822a1be1c13cab11c8ab0b1d10a7384092b5be69`
* Aggregate SHA256 `6c457223f0f693c66e155adf604fc2e17fa105f884fde8aca9aad690e41aea71`

Independent audit bindings in `research_local/part_ranking_audit_v01`:

* Audit code SHA256 `896e08ba03cffdc4f6621d20b7d6ba02eb94d9039006a8077a8046284fba21ef`
* Start receipt SHA256 `e1df2c76bd3f5b16f9fe12bfc872d49291724bb3b0e283fcc519650025410918`
* Results SHA256 `1eb91ab66f3afb3746be5bb83c43e4c21d1e57ced63a37e3cb5c5e8b42afa9fa`
* Completion receipt SHA256 `03b0f8b8c93c6c3973a45bf712987385267b6c550f92883eccc01a7e40a8f659`

The independent receipt binds the original artifacts, input hashes, 180 MIDI
inventory, frozen source snapshot, exact loaded module paths and replay output.
