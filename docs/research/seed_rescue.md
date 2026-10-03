# Seed rescue development diagnostics

## Decision

No experimental variant should replace the default from this evidence. The
terminal onset variant and the v02 union variant are bounded follow-up
candidates. Terminal onset makes two of the three previously empty sources
nonempty, one with the exact saved windows and one as a one-note leading
boundary extension. The union makes all three nonempty and exactly recovers
two target pairs. Neither changes recovery or negative-case outcomes in the
existing 500-case development cohort or the new 500-case seed cohort.

The union is not free. It changes selected output in 19 of 128 unlabelled real
files, increases proposed pairs and runtime and makes one additional real file
search limited through seed bucket saturation. A larger labelled evaluation
is needed before exposing it as an optional method.

The v01 short-key replacement should not be promoted. It lost 27 existing
development recoveries and 24 recoveries on the reused v01 seed cohort. The v02 union was a
separate frozen experiment designed after that result and retains the terminal
composite keys rather than replacing them.

These are candidate retrieval diagnostics. They do not measure perceived
musical quality, memorability or corpus-wide accuracy.

## Frozen methods

All methods use unchanged `AlignedConfig`, exact cache, resource limits,
fixed-prototype verifier, nonoverlap, ranking and curation.

- `baseline` is the existing `aligned_indexed` implementation.
- `terminal_onset` retains the composite paired and single anchor design but
  replaces the duration-sensitive `max(onset + duration)` span cue with the
  last onset. This cue matches the later terminal timing constraint more
  closely.
- The v01 `terminal_onset_short_distinct` method uses terminal-onset composite
  keys above eight notes. For six through eight notes, it replaces composite
  keys with one transposition-invariant pitch-interval key per encoded offset.
- The v02 `terminal_onset_union_short` method keeps terminal-onset composite
  keys at every length and adds one offset key for six through eight notes.
  Admission uses the existing mixed vote counter. Three votes can combine
  phase or composite keys with distinct-offset keys. They do not prove three
  independent anchors. The unchanged final verifier decides validity.

The key substitution is process local and restored after every extraction.
The run used two worker processes.

The v01 short replacement is not a rescue superset. An eight-note window uses
`short_distinct` keys while a nine-note window uses composite terminal keys,
so they have no shared seed namespace. The exact cache also requires equal
length. Approximate 8-to-9 pairs therefore cannot be proposed by this variant
even though the final verifier permits one insertion.

Eight-to-seven pairs use the same short key namespace, so their measured
losses have a different cause. In a traced development deletion case, the
fixed-offset interval anchors after the deleted note shift position. The pair
shares only two short keys against the required three, while the final aligned
verifier accepts it with one deletion. This one trace explains that case and
is not asserted as proof for every deletion loss.

## Cohorts

The design and all inputs were frozen before detector execution.

| Cohort | Cases | Use |
| --- | ---: | --- |
| Known no-match regressions | 3 | Development cause and target-window diagnostic |
| Existing synthetic development | 500 | Existing `generate_cases(1000)` development half |
| Fixed real pilot | 128 | Paired unlabelled output and workload diagnostic |
| Reused synthetic seeds, v01 | 500 | Same generator, seed namespace 30,000,000 through 30,000,499, previously observed in the closed-pattern study |
| Fresh synthetic seeds, v02 | 500 | Same generator, seed namespace 40,000,000 through 40,000,499 |

Both namespaces are disjoint from the existing 10 million development
namespace and from each other. Each seed rescue run was frozen before its own
detector execution, but that alone does not make its cases fresh. A later
cross-study audit found that all 500 v01 cases in the 30 million namespace had
already been used in `closed_patterns_v01_replication`. Their frozen metadata
is identical after removing cohort and case labels. The v01 `fresh_seed_500`
field is therefore a historical mislabel: these are reused development
diagnostics, not fresh heldout evidence for seed rescue.

The v02 40 million namespace has no overlap with those two prior cohorts.
It was frozen and executed without an edit or result-inspection boundary.
It remains a synthetic sample from the same generator, not an external
heldout corpus. The correction is recorded in
`research_local/seed_rescue_namespace_audit_v01.json`; original receipts and
results remain unchanged. The earlier closed-pattern study's original use
of 30 million seeds is unaffected by their later reuse.

## Known regressions

| Source | Baseline | Terminal onset | Union short |
| --- | --- | --- | --- |
| `Nat_King_Cole/Nature_Boy.mid` | no phrase | no phrase | exact 8-note target, rank 1 |
| `Bilk/What_Are_You_Doing_the_Rest_of_Your_Life.mid` | no phrase | 7-note leading extension | same 7-note leading extension |
| `Evans_Bill/All_the_Things_You_Are.mid` | no phrase | exact 8-note target, rank 1 | exact 8-note target, rank 1 |

The Bilk output starts one note before both saved six-note reference windows
and ends at the same ticks. It is a verified boundary extension, not an exact
recovery of the saved target coordinates. Source-level nonempty counts are
0/3, 2/3 and 3/3. Exact target counts are 0/3, 1/3 and 2/3.

## Synthetic results

### Existing development cases

There are 423 positive and 77 negative cases.

| Method | Positive recovered | Top-1 recovery | Candidate F1 | Occurrence F1 | Negative cases with output |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 409/423 | 0.936170 | 0.871140 | 0.862245 | 0/77 |
| Terminal onset | 409/423 | 0.936170 | 0.871140 | 0.862245 | 0/77 |
| Union short | 409/423 | 0.936170 | 0.871140 | 0.862245 | 0/77 |

Terminal onset and union short each change two selected phrase payloads and
one top-ranked family, but neither changes a case-level recovery outcome or
aggregate metric. Union short raises proposed pairs from 557,032 to 587,397,
shortlisted candidates from 14,057 to 14,259 and median paired runtime by a
factor of 1.098.

### Fresh-seed cases

The v02 40 million seed cohort also has 423 positive and 77 negative cases.

| Method | Positive recovered | Top-1 recovery | Candidate F1 | Occurrence F1 | Negative cases with output |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 404/423 | 0.926714 | 0.860490 | 0.850716 | 0/77 |
| Terminal onset | 404/423 | 0.926714 | 0.860490 | 0.850716 | 0/77 |
| Union short | 404/423 | 0.926714 | 0.860490 | 0.850716 | 0/77 |

Terminal onset and union short each change two selected phrase payloads but no
recovery rank or aggregate metric. Union short raises proposed pairs from
584,073 to 614,245, shortlisted candidates from 15,585 to 15,792 and median
paired runtime by a factor of 1.100. No positive condition loses recovery and
none of the 77 negative cases returns a candidate.

For context, the rejected v01 replacement lost 27 recoveries in development
and 24 in its 30 million seed cohort. All losses were inserted-note or
deleted-note cases with an eight-note prototype. One traced 8-to-7 deletion
pair shared only two fixed-offset rescue keys despite passing the final
verifier. The v02 union retains composite keys and shows none of those losses.

## Real pilot sensitivity

The 128 real files have no phrase correctness or quality labels. Counts below
only describe paired output and work.

| Measure | Baseline | Terminal onset | Union short |
| --- | ---: | ---: | ---: |
| Selected phrase payload changes from baseline | 0 | 18 files | 19 files |
| Top-1 changes from baseline | 0 | 8 files | 9 files |
| Shortlisted candidates | 54,883 | 54,989 | 55,042 |
| Proposed pairs | 33,036,469 | 32,655,599 | 33,151,817 |
| Repeat groups | 687,744 | 688,292 | 688,392 |
| Search-limited files | 23 | 24 | 24 |
| Saturated seed buckets | 485 | 508 | 508 |
| Detector time, summed across files | 522.07 s | 529.24 s | 544.17 s |
| Median paired runtime ratio | 1.000 | 0.987 | 1.041 |

All 18 terminal-onset changed files are also changed by union short. Union
short additionally changes `Bruce_Springsteen/Im_On_Fire.3.mid`.
`Stevie_Nicks/Edge_of_Seventeen.1.mid` is the additional search-limited file
for both variants, with eight saturated seed buckets versus none at baseline.
Runtime was measured during a concurrent two-worker run on a busy machine and
should be treated as workload context rather than a stable speed benchmark.

## Input reader correction after the frozen run

The frozen v01 executable used Python `splitlines()` for the pilot JSONL. That
method would incorrectly split a JSON string containing literal U+2028 or
U+2029. The exact bound pilot manifest contains zero occurrences of both byte
sequences, exactly 128 LF-delimited rows and no carriage returns. The corrected
LF-only reader returns the same 128 parsed objects in the same order as the
frozen reader. The parser issue therefore does not change the v01 cohort or
results.

The manifest also contains zero UTF-8 encodings of U+0085, the other Unicode
character for which `splitlines()` would create an unintended boundary.

After v01 completed, the v01 runner first received the LF-only reader and the
immediate worker byte check without a method change. The subsequent v02 study
then replaced the working-tree experiment definition with its separately
frozen union method and 40 million seed namespace. The immutable v01
executable is therefore
`research_local/seed_rescue_v01/source_snapshot/scripts/compare_seed_rescue.py`.
The current working-tree runner and the v02 snapshot are byte identical. Tests
cover U+0085, U+2028 and U+2029 and confirm that the union retains composite
key types across the 8-to-9 boundary.

The original run checked every source before freezing and after all detector
work. It did not hash again inside the worker immediately before parsing, so a
transient change followed by byte restoration was not detectable. No such
change was observed. The current worker adds an immediate pre-parse check and
narrows that timing gap, but it cannot eliminate a mutation between the hash
read and the MIDI loader's separate read.

## Provenance and validation

The preferred union study is `research_local/seed_rescue_union_v02`.

- Start receipt SHA-256: `256a2626db56f43546294e94af401a461395a077427377b2e12609416601667a`
- Executable snapshot SHA-256: `ce512df48b41d37fd504eab93b9d27e7abb700aa1ccddc966ead7bc870e37ae6`
- `raw_results.json`: `8635aaf3aacf9a51146a2c3f6f29a61e29a72e125d5d63fc71eb4a706df55910`
- `aggregate.json`: `bad017e8d327d44d8ff6dc1a1dc9a89238c79db4343a757b3a65b3083df07115`
- `input_manifest.json`: `640b0a34b3758eae22c0f9cdf62cf4e34be878d6e985b0e4f24a63c295655b23`
- Wall time: 867.15 seconds

The earlier replacement study remains immutable at
`research_local/seed_rescue_v01`.

- Start receipt SHA-256: `7eb1860756f9bf9937d2e6e85a317842e5352cd00ec1c18e836cb9c2f9f57fa3`
- Executable snapshot SHA-256: `4a03d03f80a098d8d838c9f832883288eab7c85da0d446ff8675e4d25b96fab4`
- `raw_results.json`: `a403bd2ab3724a0f6f4a6c662feb7cb8901e535ae1012ca90434c199c863840d`
- `aggregate.json`: `ac164b08895374abed3936b9499759cc5338a17c24ccb2fc72f31959c50782f3`

Both completion receipts verify their declared artifacts. Raw results retain
the full detector result for every case and method, including phrase payloads,
part statistics, limits, scores and execution order. Input receipts bind the
fixed pilot manifest, the completed no-match audit, the three source and
reference-record hashes and all generated case metadata.

An independent bounded replay at `research_local/seed_rescue_union_root_check_v01.json`
reproduces all three methods on 16 selected cases. These include the three
named regressions, both real files named above, every changed synthetic
phrase payload and insertion, deletion and negative controls from each
synthetic cohort. Full detector payloads, telemetry, comparisons and scores
match exactly after excluding measured elapsed time. This is a targeted
replay, not a second execution of the entire study. The saved replay driver
has SHA-256 `c6f553e0f606cc0e00c45ddae4fb9f2cb75a3fbeadbf764d27abf672e1de9cb7`.

The current preferred experimental runner reproduces the v02 design, with a
new output path to preserve the completed study. It can be invoked from the
repository root with:

```bash
source .venv/bin/activate
nice -n 10 python scripts/compare_seed_rescue.py \
  --source-root 'datasets/Lakh MIDI Clean' \
  --real-manifest research_local/pilot_indexed_v01/sources.jsonl \
  --regression-audit research_local/no_match_regressions_v01 \
  --reference research_local/lakh_phrases_v03 \
  --output research_local/seed_rescue_union_v03 \
  --workers 2
```

That command would create a new experiment with the current union design and
the same frozen 40 million seed namespace. It must not overwrite either
completed study. Replaying the rejected v01 design requires its frozen source
snapshot rather than the current working-tree runner. Neither command changes
the production detector or promotes a new default.
