# SaMuGeD local research work log

Entries are chronological checkpoints. Later entries supersede earlier running or pending states. See [the artifact index](artifact_index.md) for preferred completed evidence.

## Scope and time window

User requested continuous local research and delivery for ten hours from 2026-10-03 02:46:15 UTC to 12:46:15 UTC (04:46 to 14:46 Europe/Oslo). Local commits are authorized. No push, pull requests, dataset publishing, deployment or collaborator messages. Existing GUI and Windows work is outside scope.

## Starting evidence

- `git pull --ff-only` completed, main was current at `200c4a2`.
- Created branch `feature/recurring-phrase-dataset` from the clean main checkout.
- Initial `rg` inspection found 17,230 visible MIDI paths, approximately 811 MiB. The recursive inventory below corrects the count to 17,232. No new source corpus downloaded.
- `datasets/two_pointers_repeats_only` is a separate older extracted subset, approximately 32 MiB.
- Remote windows branch concerns packaging and old UI changes; not a newer research pipeline.
- `.venv` created with Python 3.12 and an independent research package, leaving legacy requirements intact.
- Source data, experiments and bulk outputs remain ignored. Small aggregate evidence and reproducible source belong in Git.

## Current work ownership

- Parent owns integration, corpus extraction, review packet, publication artifacts and final validation.
- Agent legacy_audit owns the separate aligned matcher and its tests.
- Agent research owns percussion benchmark reporting and an independent evaluation review.
- Agent midi_io owns the duplicate audit script and its tests.

## Method boundary

Output labels describe recurring symbolic melodic phrase candidates, not validated earworms. A heuristic ranking is not a learned or validated memorability model. Human review and rights/provenance decisions must remain explicit publication gates.

## Next actions

Complete deterministic MIDI input/output and phrase matching; run adversarial synthetic tests before full-corpus extraction. Keep the original algorithm as a baseline, measure ablations and runtime, audit duplicates and splits, generate a review package and short paper using measured evidence only.

## Scope update at 04:54 Oslo

User explicitly added a separate drum-pattern track. Keep pitched melodic phrases and percussion patterns distinct in method, scoring, schema and evaluation. Percussion pitch numbers identify instruments, so do not transpose them and do not collapse simultaneous hits to a skyline.

Raw source count is 17,232 MIDI paths. The first rg count omitted `.38 Special/Caught Up In You.mid` and `.38 Special/Fantasy Girl.mid`. Use recursive pathlib discovery including hidden directories. An exact source archive identity is not established by the count.

Continuation heartbeat id: `samuged-local-research-continuation`, every 15 minutes, deadline 2026-10-03 12:46:15 UTC.

## Reference implementation and pilot validation

The independent package, melody matcher, separate drum matcher, controlled benchmark, corpus builder and offline review packet are implemented. Existing application code is untouched. A second insertion/deletion tolerant alternative is being developed separately in samuged/aligned.py; it is not used by the reference corpus build.

128-file pilot `research_local/pilot_both_v03` completed with 128 successful source records, 376 melodic candidates and 346 percussion candidates. Independent source/export checks passed for all 722 MIDI files. Earlier pilots are retained to show the effects of seeding/resource changes and the discovered crossed drum note-off defect. Drum gates now explicitly clip at the next same-pitch hit after ensemble merging; source strikes and velocities are unchanged.

The earlier statement of zero search limits in a 64-file pilot refers to seed/comparison/note bounds. A later independent audit found candidate shortlist truncation was not visible. Separate raw group, shortlist and curation counts now expose it; expanded shortlists did not change that pilot's top3 outputs. Latest broader seeded fallback trades runtime for recall and can report limits on dense parts.

`research_local/evaluation_v01` contains a frozen 1000-case planted benchmark, 500 development and 500 test cases. Test occurrence F1: exact0.44695, transposed0.51558, approximate0.68451; approximate95percent case-bootstrap interval[0.63784,0.73139]. All methods had0/77 negative-case false positives in this synthetic test. These are temporal planted-motif diagnostics, not real-song accuracy. The legacy adapter ran24cases successfully, recovered both contiguous positive controls and2/20positive prototypes overall. Legacy occurrence F1 is unavailable because that detector never emits occurrence coordinates.

Full reference corpus build launched locally using:

```sh
source .venv/bin/activate
python -m samuged.cli build --source 'datasets/Lakh MIDI Clean' --output research_local/lakh_phrases_v02 --workers 4 --percussion
```

The first background-shell launch did not survive its shell. It produced no records. The actual foreground process started at approximately 03:27 UTC in persistent exec session 39812, PID71527. The job log is `research_local/lakh_phrases_v02.log`; PID is recorded in `research_local/lakh_phrases_v02/.build.lock` while active. Do not start a duplicate. Read its progress and record counts, then audit all outputs with --require-full. The build stores its own code snapshot and hashes. Do not claim full corpus completion before sources.jsonl/phrases.jsonl/summary.json exist and reconcile17,232sources.

Next: finish hardened audit, verify/review full corpus, evaluate the aligned alternative on development data only, freeze a fresh untouched evaluation namespace for any tuned version, prepare dataset card and concise scientific PDF from actual final metrics. Human quality ratings remain uncollected.

## Independent audit and review packet at 05:35 Oslo

Hardened pilot audit reconciles source records, phrase manifest membership, IDs, split assignments, source hashes, code snapshot, original note coordinates and complete exported tempo/meter/program/track lengths. Re-extraction reproduced all128source records and722phrases. Parent fixed an independent audit nearest-neighbour matching flaw for closely spaced percussion hits, adding a regression fixture and a canonical drum-family fingerprint check. Pilot passes these checks too.

Review packet now uses actual source tempo maps and exact melodic note-index ranges. A sustained note previously could cause unrelated following notes to appear in the review excerpt. Six review tests pass including that boundary case. Browser playback/stop and source reveal run without console errors. The in-app browser did not emit a download event for a Blob URL, so JSON is also exposed in a read-only fallback field. UI verification parsed40unrated rows with both kinds and the smoke-test annotator ID. No automated ratings were saved as human evidence. Local review server is exec session16384 on127.0.0.1:8871.

`research_local/drum_evaluation_v01` contains1000constructed percussion cases. Initial test diagnostics: tolerant recovers375/375positive cases, exact249/375; strict F1 .89928and.70339respectively. Both return0/125negative cases, Wilson95percent upper bound.02982. Design has955distinct arrangements, and cross-split duplicate auditing is in progress. These easy constructed controls do not estimate real-song quality. Do not promote them to a general accuracy claim.

PDF artifact creation marker ran successfully. No PDF has been authored yet. Disk free27GiB; currentresearchoutputs below1GiB. Avoid unnecessary full-corpus copies.

## Evaluation and publication preparation at 06:00 Oslo

A four-page paper preview now exists at `research_local/paper_preview.pdf`. All four pages were rendered and visually checked. It still contains pilot counts and is not the final paper. The generator is `scripts/make_paper.py`. `scripts/package_dataset.py` makes a local metadata bundle, separate canonical-family views and an optional deterministic archive. Pilot archive checks verify all payload checksums, deterministic bytes and rejection of modified MIDI after audit. Full-corpus packaging must wait for its passing audit.

The harder percussion stress set has 480 distinct exact and beat-normalized arrangements, no cross-split overlap and 3–5 planted occurrences in longer contexts. Frozen test results: exact mode recovers60/60exact controls; tolerant mode recovers120/120supported controls; neither recovers80deliberately out-of-range/pickup diagnostics. Exact returns no output in40negative cases. Tolerant returns output in7/40negative cases, Wilson95percent interval[8.75%,31.95%]. These are negative-generator outputs, not automatically musical false positives. Development-only analysis is checking whether the generator contains chance approximate repeats. Do not tune against the disclosed test results. Existing easier drum metrics stay unchanged and are no longer sufficient alone.

The official JKU repeated-pattern development archive was downloaded for external evaluation only, not as a replacement source corpus:35,017,995bytes, SHA256 `9f5e1e1d225b8b9236c8d565ef643d855770ed30c05adece7b62664e453f9ee5`. Upstream CSV scores and annotations are used, not its checking MIDI. The adapter reproduces seven published MATLAB example metric tables within1e-5using mir_eval0.8.2. Five works each have monophonic and polyphonic variants. With unchanged top3reference modes, macro establishment F1 is.2447/.2518/.3982for exact/transposed/approximate monophonic and.1219/.2143/.3053polyphonic. Approximate occurrence F1 at.75threshold is.2507mono and.0786poly. These five classical development works are a diagnostic, not an official MIREX submission or evidence of popular-song accuracy. Adapter review is pending. Results: `research_local/jku_reference_v01/`.

The full reference build had reached15,800/17,232sources with240errors at03:57UTC. Core extraction modules remain frozen while it runs. The duplicate fingerprint process from an agent session disappeared after10,601cached files without a final report. Parent resumed compatible cached fingerprints in exec session25879, one nice10worker, logging to `research_local/duplicates_full_v02.log`. Do not run another copy. The resumed current verifier uses all qualified shingles for similarity denominators; older classifications from the prior verifier are invalid. After full build, rerun with its source manifest for cross-split diagnostics.

Aligned matcher optimization is still experimental and development-only. Old pilot reached search limits on all128files. Its optimization and tests are owned by legacy_audit. Parent saw temporary test failures during an edit, so run the entire suite again after agent handoff before claiming green or committing.

## Full reference output and validation at 06:15 Oslo

The full reference pass completed in 1,913 seconds. All 17,232 paths are accounted for: 16,967 parsed successfully and 265 have parse errors. Output contains 50,355 melodic candidates and 44,456 percussion candidates, or 94,811 excerpts and 73,657 canonical families. There are 103 parsed sources with no output. Melodic search limits occur in 791 files, candidate shortlist truncation in 15,930 files and percussion search/curation limits in 2,337 files. Exact-family overlap excludes 478 phrase rows across splits. These are extraction counts, not human quality labels.

Run fingerprint: `cb208cc6875b628d5d31d21054ac838fa18f1ec1baa2ce464f079d10746e00a6`. Source manifest SHA256: `fa4c3010b8b17fdd8fbd58c87257281c01abf4a7325f94481fd9b5dfd3380823`. Phrase manifest SHA256: `31b586ca1e9880ede1e007ab85f359c5e82bd8766e959dd82588f2fd42d3a718`.

All 112,043 source and phrase rows pass JSON schemas. Full artifact audit is still running in session 95164 (PID 18915). It loaded the earlier audit implementation. The parent then added independent drum bar-grid, meter, source-part and gate-policy checks with corruption fixtures. Once the original audit completes, retain its result and run the strengthened audit. All core extraction modules used by the full reference run are preserved under its provenance directory.

The full duplicate audit now exists at `research_local/duplicates_full_v02.json`. Compatible cached fingerprints were completed by parent session 25879; session 72095 applied the completed source manifest. It reports 6,153 symbolic near-duplicate pairs, including 77 cross-split edges. Candidate generation and pair-verification limits were reached, so this is not exhaustive. A conservative supplementary split-screening view is being designed; baseline manifests stay immutable.

Development-only investigation explains the stress negatives: 6 of 20 independent-pattern development cases return 18 selected candidates, all valid under the verifier. Seventeen pairs repeat within a generated four-bar phrase and one across independently generated regions. The generator's repeated shorter structure makes whole-song negative labels incomplete. No detector threshold was changed in response. See `docs/research/drum_specificity.md`.

Independent review found a mir_eval 0.8.2 keyword mismatch: wrapper occurrence scores labelled threshold 0.5 actually used 0.75. Only the saved v01 .5 occurrence metrics are invalid. The corrected adapter verifies all 17 comparable official metrics and records shortlist caps plus code/dependency snapshots. A fresh run from frozen reference core plus corrected adapter is in session 12231, output `research_local/jku_reference_v02`. No tuning on JKU occurred.

First local commit: `2579ad9` (`feat: add local melodic and percussion phrase extraction`). No push. Per-file diffs were inspected and saved locally; stable core and schema checks passed. Further experimental modules and paper remain uncommitted.

Parent is testing an exact-representative cache for the approximate reference matcher. It only caches fixed prototypes, retains original pitch/timing verification semantics and can recover exact matches after approximate comparison budgets are spent. Development and fixed 128-source differential comparison is session 12999, output `research_local/cache_comparison_v01`. Do not treat this new current module as the frozen full reference version; its original source snapshot is authoritative.


## Audited reference and optional algorithms at 06:47 Oslo

Both the initial full audit and the strengthened audit passed. The latter checked all 94,811 MIDI exports, 16,967 parsed sources and 265 reproducible input errors with zero failures. It includes independent drum bar-grid, meter, source-part and gate-policy checks. `audit.initial.json` retains the first result. Schema validation passed all 112,043 source and phrase rows.

Corrected external evaluation is complete at `research_local/jku_reference_v02`. All 17 comparable published metric values pass the golden check within 1e-5. Frozen reference synthetic reruns are `evaluation_reference_v02` and `drum_evaluation_reference_v02`; cohort designs, metrics and all 1,000 generated melodic case MIDI bytes match the earlier runs. The new receipts freeze executable sources and dependency information before evaluation. Earlier JKU v01 occurrence scores labelled threshold 0.5 remain invalid and must not be cited.

The exact prototype cache preserves phrase outputs on 500 development cases and the fixed 128-source real pilot. Real comparisons fell from 9,491,458 to 7,541,693 and measured runtime from 41.142 to 37.208 seconds. It is local commit `d9e6820` (`perf: cache exact phrase representatives during matching`). The original full reference uses its saved pre-cache source snapshot.

The frozen aligned comparison at `research_local/aligned_frozen_v01` measures test occurrence F1 0.838450 versus reference 0.684508, paired difference 0.153941 with 95 percent case-bootstrap interval [0.099147, 0.211201]. Most gain is insertion/deletion support. It regresses contiguous adjacent exact cases and has one negative-case output versus zero. On 128 real sources it takes 323.055 versus 37.114 seconds and reaches search limits on 23 versus 3 files. Keep reference as default; aligned is optional and not proven perceptually better. An independent development-only index optimization is in progress without editing the frozen aligned module.

The homogeneous duplicate rerun at `research_local/duplicates_full_v03.json` is complete. All 17,232 source receipts use one method key, with zero cache reuse. It fingerprints 16,967 parsed sources, generates 7,644,656 pair events and verifies 1,026,114 source pairs without global generation, verification or report caps. It retains 6,153 near-duplicate candidates and the same 77 cross-split near-duplicate edges. Its melodic shingle model still misses unknown forms of similarity. The 265 strict parse errors remain outside symbolic screening.

A supplementary group-level split view is now implemented in `scripts/screen_splits.py` and generated at `research_local/screened_splits_reference_v01`. It uses all strong candidate edges, including same-split links, before connected-component exclusion. It quarantines 44 original groups and 766 sources, newly excluding 1,739 validation and 2,126 test phrase rows. This differs from the earlier proposed 43-group view because same-split links propagate one additional group into an implicated component. It preserves the original manifests, all 478 family exclusions and zero retained cross-split candidate edges. It is a sensitivity view with distribution changes, not duplicate ground truth.

Optional metadata recovery now preserves invalid key events as ignored metadata in memory. Strict loading remains the default. The integrated probe recovers all 28 key-error sources by changing only 124 metadata type bytes, emits exact JSON receipts and leaves all source hashes unchanged. Parent is integrating optional aligned and recovery CLI/build controls; an independent audit extension and strict JSON schemas are in progress. Do not launch a full new build until these checks pass and freeze its runner before further edits.

Active jobs: no full dataset or duplicate job remains running. The earlier local review server may remain on port 8871. New output assembly and paper are not final. Work continues until 12:46:15 UTC (14:46:15 Oslo), local only. No push or publication.

## Updated full builds and independent review at 07:10 Oslo

Two full jobs are running from the immutable local runtime snapshot `research_local/corpus_runner_v03`. Session 53496 builds the updated reference corpus at `research_local/lakh_phrases_v03` with two workers, percussion and explicit invalid-key metadata recovery. Session 18207 builds the optional aligned indexed corpus at `research_local/lakh_aligned_indexed_v01` with four workers and the same recovery policy. Logs use each output directory name plus `.log`. Do not modify that runner or start duplicate jobs. These jobs do not use later edits in the working checkout.

The indexed 128-source pilot contains 379 melodic and 346 percussion candidates. All 725 exports pass independent reconstruction and MIDI checks, and re-extraction also passes with zero failures. All 853 manifest rows pass schemas. Integration testing caught and corrected two schema defects: recovery receipts omitted their SMF hashes, and the aligned source condition wrongly required melodic matcher flags on percussion phrases. A mixed recovered source fixture now covers both.

External comparison at `research_local/jku_aligned_v01` confirms identical indexed and unindexed aligned outputs on all ten JKU representations. Indexed runtime is 10.242 seconds versus 11.385 for unindexed aligned and 1.121 for reference approximate. Aligned monophonic occurrence F1 at 0.75 rises from 0.250742 to 0.421554, while polyphonic establishment F1 falls from 0.305294 to 0.239229. These mixed diagnostics do not justify replacing the reference default.

The independent drum pair oracle at `research_local/drum_oracle_v01` evaluates 240 development stress cases and sixteen real 32-bar clips. It performs 292,091 comparisons without reaching its pair budget. All 589 synthetic and 157 real direct prototype edges satisfy the independent symbolic rule. All-pairs family coverage is much lower because only three selected families are returned. Other pairs within a prototype-centred family need not match each other: approximate similarity is not transitive. This is symbolic validation, not human musical assessment.

Read-only packaging review reproduced a cross-corpus stale-audit acceptance bug, insufficient verification of supplemental split mappings and nondeterministic PDF metadata. Independent agents are repairing exact manifest/config audit binding, reconstructive split-view validation and method-aware reproducible paper generation with regression tests. No final release archive or final PDF is ready yet. The current six-page preview is `research_local/paper_full_reference_preview_v02.pdf`.

The review packet now shows the prototype and up to two distinct other intervals, avoiding a duplicated prototype card. Synthetic playback remains explicitly labelled and all human rating fields remain empty.

## Further experiments at 07:16 Oslo

Independent drum enumeration results are now documented in `docs/research/drum_specificity.md` and a compact hash receipt. No production drum algorithm change has been made. An ignored candidate adds a fixed-prototype exact cache using integer relative ticks. It matches the frozen outputs on 500 easy development cases, 240 stress development cases and 128 real pilot sources. In the measured pilot it reduces drum comparisons from 497,238 to 435,296 and runtime from 9.379 to 8.822 seconds; stress runtime is slightly worse. This is not yet a promotion decision. Full-corpus differential validation is session 98690, output `research_local/drum_cache_full_v02`, comparing immutable snapshots of the original drum module and `research_local/drum_cache_candidate_v02.py`. Do not modify those candidates or start another copy.

The duplicate audit tool now supports explicit metadata recovery, records repair receipts and binds its cache method to that policy, the recovery implementation and Mido version. Strict and recovered cache modes are separately tested. A new full duplicate report must use the completed v03 source manifest and recovery option, before the final v03 screened split view is assembled.

Six small public Theme Transformer annotation archives were downloaded from the authors' official page to `research_local/external/theme_transformer` with URL, byte-size and SHA256 receipts. They contain three human theme annotations plus published baseline selections for POP909 songs 065, 284, 310, 422, 449 and 464. An independent input audit is checking whether the labelled melody notes agree before defining any evaluation domain. No detector has been tuned against these annotations. The archives are external evaluation material, not additions to the Lakh source collection.

Core integration is saved in local commit `0e3fbca` (`feat: add verified note alignment and metadata recovery`). Root reviewed the per-file diffs and reran 122 focused core, schema, recovery and audit tests successfully. The audit now binds input hashes before parsing and checks them again before writing the result, with a concurrent-mutation regression. Older audit receipts must be regenerated before packaging. No push.

## Human annotation diagnostic and receipt checks at 07:48 Oslo

The six-song Theme Transformer note-domain diagnostic is complete at `research_local/theme_evaluation_v01`. The canonical melody merges the human annotation partitions before detection and strips their track names, programs and channels. All three annotators have identical note universes per song. Top-one macro note F1 is 0.228 for reference approximate and 0.323 for aligned indexed, with wide song-bootstrap intervals. Top-three sensitivity values are 0.452 and 0.465. Human agreement varies greatly, including negative pairwise kappa. This is neither the authors' beat-domain score nor a corpus quality estimate. No parameters were tuned. Root replayed all 24 detector outputs and independently reconstructed all 144 classification rows successfully.

Independent integrity review found completion receipts could omit raw results, fixed receipt paths could escape the experiment directory through symlinks and review snippets did not reject every shifted source slice. Repairs and regression tests are in progress. Paper validators are also being strengthened to reconstruct cohort coverage, snapshot hashes and published metric examples rather than trust status fields. A new drum stress run at `research_local/drum_stress_v02` now freezes executable provenance before detection; all 480 cases and scientific outcomes match v01 exactly, excluding runtime and receipt fields. Older artifacts remain unchanged.

The full updated reference build, full aligned indexed build and full drum-cache differential experiment remain active. The cache is still an ignored candidate and has not replaced the production drum matcher. No final publication package or final PDF has been declared ready. Local-only work continues to the agreed deadline.

## Updated reference corpus and replication at 08:13 Oslo

The reference build `research_local/lakh_phrases_v03` is complete. It accounts for all 17,232 input files, with 16,995 successful parses and 237 recorded errors. Explicit metadata recovery restored 28 files through 124 event-type byte changes in memory. Output contains 50,439 melodic and 44,511 percussion candidates, 94,950 MIDI files and 73,751 canonical families. The 103 parsed no-match sources remain accounted for. There are 700 melodic search-limited sources, 15,959 shortlist-truncated sources and 2,339 percussion-limited sources. All 112,182 source and phrase rows pass the schemas. Independent full audit is still running in session 39278; packaging waits for its result.

Run key is `95f9733b8098731b813476102cced7c8790581db9992d7dc4c6634da409aa828`. Source manifest SHA256 is `062691ad29739cd58bdfb8c55258d63d72868d3ee3e4c30badeceaa917c8c76f`; phrase manifest SHA256 is `f7a1ccff7483bb70a07c0c3f04b7cd6d5090942b524272eac942d0ee3739160e`. Original split counts are 77,445 train, 8,786 validation, 8,239 test and 480 overlap-excluded rows. These counts describe structural candidates, not human acceptance.

Preferred completed evaluation artifacts are now `evaluation_reference_v04`, `drum_evaluation_reference_v03`, `drum_stress_v03`, `jku_reference_v03`, `aligned_frozen_v02`, `drum_oracle_v02` and `theme_evaluation_v02`. Their receipts include the executable local import closure. The melodic completion receipt also binds all 1,000 generated case MIDI files. Root compared the aligned and drum-oracle replication raw rows with their earlier runs: every scientific field is identical after explicitly excluding runtime and provenance fields. Aligned v02 uses 2,000 bootstrap replicates instead of 1,000; its unchanged test occurrence F1 difference is 0.153941, with interval [0.096845, 0.212337]. Runtime measurements come from each individual run and must not be interchanged.

The recovered full duplicate diagnostic is complete at `research_local/duplicates_recovered_v01.json`: 16,995 successful fingerprints, 237 errors, zero cache reuse and one method key. It verifies 1,026,277 pairs without global caps, retaining 6,164 near-duplicate candidate pairs, including 77 cross-split pairs. A new screened split view is pending a provenance repair. Read-only packaging review reproduced missing-payload entries in metadata-only checksums and an unverifiable duplicate-report hash claim; small-fixture repairs are in progress before a full package is created.

The 60-candidate full reference listening packet is `research_local/lakh_phrases_v03/review.html`, served locally on port 8872 by session 4376. Browser playback actions for both kinds, stop and blank JSON export ran without console warnings or errors. All ratings and annotator IDs remain empty. Source roles were also checked on six full official POP909 files. Both methods select accompaniment for 3 of 6 top-one results. This small diagnostic describes part choice, not human theme quality.

The shortlist sensitivity study at `research_local/shortlist_sensitivity_v01` compares caps of 80 and 400 on 500 development cases and 128 real sources. No reference output or either method's top-one output changes. Three lower-ranked aligned outputs change, with a small synthetic precision loss. No cap change is justified. A separate candidate for exact closed-pattern selection is being tested on a fresh frozen synthetic namespace and the fixed real cohort, with no production change yet.

Local commits `c62e830` and `d614745` save frozen experiment receipts, theme evaluation and symbolic recurrence suites. Root inspected the per-file diffs and reran the relevant tests. The most recent complete suite passed 291 tests, followed by focused checks for additional schema and review fixes. No push or publication has occurred.

Still active: full aligned indexed corpus session 18207 from `research_local/corpus_runner_v03`; full drum-cache differential session 98690; full reference audit session 39278. Do not change the frozen runtime. The latter two may finish before the next checkpoint. The duplicate job 30402 and aligned replication 75908 are finished. Continue local work until 12:46:15 UTC (14:46:15 Oslo).

## Audited local package and closed variant at 08:40 Oslo

The full reference v03 audit passed all 94,950 exported MIDI files, 16,995 parsed sources and 237 reproducible input errors with zero failures. Its audit is bound to the exact source manifest, phrase manifest, build configuration and summary. All 112,182 manifest rows pass schemas. The local metadata package and archive are `research_local/releases/reference_v03` and `reference_v03.tar.gz`. Root independently verified all 94,983 payload checksums, archive metadata and the archive checksum. The archive is 173,102,352 bytes with SHA256 `0917f946e662aec35563ab01d43682707a10be302560848530499a025400732d`. It remains local and immutable.

The recovered duplicate screening view is `research_local/screened_splits_reference_v03`. It reconstructs all 6,168 strong edges from a bundled, hashed duplicate report and excludes 44 groups containing 766 sources. The source report contains 6,164 near-duplicate candidate edges and four additional exact-arrangement edges. There are zero retained cross-split strong edges. This remains a sensitivity view rather than duplicate ground truth.

The current paper is `output/pdf/samuged_recurring_phrases.pdf`, five pages. It uses the audited reference v03, current screening and verified evaluation receipts. All five rendered pages were visually inspected. The PDF and its input receipt will be updated after the remaining closed-pattern evidence is validated. The local review packet has no human ratings. An import and agreement workflow is being tested separately; no listening quality labels have been generated.

The exact closed-pattern selector has replicated on a fresh 500-case synthetic namespace. The authoritative experiment is `research_local/closed_patterns_v01_replication`, with automatic local import closure. Positive recovery rises from 404 to 420 of 423, occurrence F1 from 0.831091 to 0.894309 and candidate F1 from 0.841667 to 0.888889. Both variants produce zero outputs on 77 negative cases. The 128-source unlabelled pilot changes 19 files through 29 extension steps. These results support an optional variant, not a claim of better perceived musical hooks. No default was replaced.

The integrated closed pilot at `research_local/pilot_closed_v01` passes independent reconstruction, full re-extraction and all 853 schema rows, including 725 MIDI exports. A full closed build started in session 15333 at 06:37:46 UTC from the immutable `research_local/corpus_runner_closed_v01`, with four workers, percussion and explicit invalid-key metadata recovery. Output is `research_local/lakh_aligned_closed_v01`, with a matching `.log`. Do not modify its runner. The full aligned indexed build remains active in session 18207, about 8,000 of 17,232 sources at this checkpoint.

Local commit `3b88698` adds automatic static import closure to experiment snapshots. The original drum-cache differential is finished: 16,951 of 16,967 parsed files have identical outputs, with changes confined to 16 baseline-limited sources. The measured runtime reduction is about 6.6 percent, but selections change, so the candidate remains experimental. A separate source-coordinate audit passes its changed direct prototype edges. A fixed real-source metamorphic study is still running. Work continues locally until 12:46:15 UTC; no push or publication.

## Additional validation and optional part ranking at 09:10 Oslo

Local commits `c82d9a5`, `4954029` and `318ec42` save the optional closed selector, independent trace geometry checks and dataset packaging and review workflows. Root reviewed the changed files and reran focused tests. A further 33 paper, metamorphic, cache and variant comparison tests passed. No push or remote publication.

The real-source metamorphic diagnostic at `research_local/metamorphic_v01` is complete. It covers 128 sources, three detectors and three transformations, 1,152 comparisons in total. Tempo changes, doubled tick resolution and melodic transposition with drum pitches preserved produced zero musical payload, family-order or telemetry differences and zero skips. This checks representation consistency, not human phrase quality. The five-page PDF now includes the verified result; its page layout has been inspected.

A corrected cache comparison at `research_local/cache_comparison_v02` freezes the actual comparison driver and dynamically loaded baseline. All 500 development and 128 real-source outputs match. On the real pilot, comparisons decrease from 9,491,458 to 7,541,693 and measured runtime from 46.534 to 42.134 seconds; the synthetic runtime is slightly slower. Earlier experiment bytes remain unchanged.

The completed independent melodic metric audit reconstructs 7,000 score rows, 6,745 candidates and 14,163 predicted intervals using exact Fraction IoU and maximum-cardinality matching. It finds no metric, match-coordinate, rounded-IoU or recovery-rank mismatches. No predicted interval has multiple eligible truth matches, so the known generic greedy-matching weakness does not affect these frozen rows. Its separate adversarial regression retains the limitation for other truth geometries. Root review of this audit is ongoing.

The official POP909 part-role cohort contains 180 strict-parsed sources, 60 development and 120 heldout, with six previously inspected songs excluded. A frozen grid selected the monophony prior on development data. The reported heldout top-one MELODY agreement is 76/120 for aligned closed and 110/120 for the optional prior; top-three coverage is 102/120 and 119/120. Heldout predictions were saved before role scoring. Official role names existed in the source files, so this is a procedural boundary, not physical blinding. An independent audit is checking these results. The prior remains optional because accompaniment riffs may also be desirable and role agreement is not phrase quality.

A stricter synthetic drum diagnostic is being prepared with oracle-certified negative cases, so absence of a planted repeat is not silently equated with absence of every admissible repeat. The full aligned indexed and closed corpus jobs remain active from their immutable runners. At the latest checkpoint they have processed about 10,300 and 2,200 of 17,232 sources. Work continues locally to 12:46:15 UTC (14:46:15 Oslo).

## Independent audits and installed package check at 09:27 Oslo

Local commits `05d863c`, `f126ac1` and `04194ff` save independent metric/variant audits, cache and representation diagnostics and the verified paper generator. Root reran 19 metric/comparison tests and 20 cache, shortlist, comparison and metamorphic tests successfully. A second independent metric audit at `research_local/melodic_metric_audit_root_v01` reproduces zero mismatches across all 7,000 rows.

The independent part-role audit confirms the heldout improvement is exactly 34 of 120 top-one choices, with 76 correct-to-correct, 34 incorrect-to-correct, 10 incorrect-to-incorrect and zero correct-to-incorrect cases. It replayed all 60 development and 12 stratified heldout candidate lists from the frozen snapshot and checked all 180 feature, role and selection records. The aligned score does not use part program/name/channel metadata, and all 540 official POP909 parts already use program zero. This resolves the metadata-blanking concern for this study, while the Lakh transfer and human-quality limitations remain. A build option and real Lakh pilot are in progress.

The new certified drum controls contain 240 negatives and 120 planted positives with 360 unique exact and beat-normalized arrangements. Independent replay audits all 360 saved MIDI files and exhaustive oracle labels. Each mode returns zero candidates on the 120 heldout negative cases. Each recovers all 60 heldout planted families. Direct prototype-edge coverage is 120/180 and is deliberately not called occurrence recall: a three-occurrence family has two direct prototype edges but three possible unordered pairs. The generation is conditioned on the symbolic oracle and does not estimate real-song specificity. The v01 on-disk start receipt was created after generation and before detector execution; the source-defined generation policy was not a separate pre-generation receipt.

An isolated wheel from commit `04194ff` installed outside the checkout with only Mido, packaging and SaMuGeD. Both reference and aligned-closed build/audit paths passed on seven local synthetic files including drums. The check found a cosmetic installed-CLI error: optional Git metadata printed a fatal-not-repository message even though extraction succeeded. A reusable smoke harness also covers an invalid-key recovery fixture, two workers and unchanged source bytes, and correctly rejects that old stderr behavior. The repair and runtime dependency provenance are being integrated before a new wheel smoke run.

The full indexed and closed builds have processed about 12,000 and 4,000 of 17,232 sources respectively. They retain their immutable runtimes. No push or publication. Continue local work until 12:46:15 UTC.

## 2026-10-03 09:49 Oslo: optional melody build and package check

Committed the fixed optional `aligned_melody` path as `b855b6b`. It retains indexed candidates and the closed selection rules, adds the frozen 0.08 monophony prior and records separate ranking evidence without changing recurrence scores. Root validation passed 73 focused integration, audit and schema tests. An independent review confirmed the metadata independence after part partitioning and the remaining causal audit boundary: the complete candidate-order digest and replacement decisions require `--reextract`, whereas ordinary auditing checks source features, selected scores and note geometry.

The 128-file pilot has 379 melodic and 346 percussion candidates, all 725 exports passed full reextraction and all 853 rows passed schemas. The optional selection changed top phrases in 52 files and top parts in 49. All percussion payloads and candidate search telemetry matched the closed baseline. These are unlabelled Lakh selection changes, not accuracy measurements.

The isolated wheel smoke at `research_local/packaging_smoke_v03` passed reference, closed and optional melody extraction outside the Git checkout. Each method processed eight inputs, including a drum-only fixture and one recoverable invalid key signature, then passed full reextraction auditing. Root independently verified all 235 completion-bound payloads. The wheel SHA256 is `69af066c879cfcd49c54888c27d846d7aa4b033d289f89ed8fb1d557fe466a9a`. A subsequent smoke adds the exact test-driver snapshot to the receipt; v03 remains unchanged.

The third full build started around 09:48 Oslo in session 19713 at `research_local/lakh_aligned_melody_v01`, using the committed 29-file snapshot `research_local/corpus_runner_melody_v01` with receipt SHA256 `eac86df5adbef90000043e22c21d74a9749b1d23f2db5b6492f196727652c9c5`. It uses four workers, separate percussion and explicit key-metadata recovery. The earlier indexed and closed full runs continue. None of the three new full datasets is yet a verified release.

Root reviewed the six-page paper draft and reran its 29 tests. The draft adds independently checked POP909 part-role and certified drum controls. Root corrected a prose denominator error in the drum study notes: the 0/120 heldout Wilson upper limit is 0.031019, while 0/240 pooled gives 0.015754. The frozen numeric artifacts were already correct. A stricter drum audit is being added to reject embedded-design and replay-telemetry inconsistencies.

## 2026-10-03 10:16 Oslo: external selectors and search sensitivity

The current six-page paper now includes the selector comparison on six externally annotated popular songs and five JKU works in two representations. All 48 runs have truncated candidate shortlists. Closed selection and the optional part prior leave Theme note F1 unchanged. The part prior changes three JKU polyphonic outputs, with establishment F1 0.239229 to 0.237214 and unchanged occurrence F1 0.084361. These reused development diagnostics limit the interpretation of the positive POP909 role result. Root independently reran all 48 outputs and checked the preferred Theme v02 regression.

A development-only seed-bucket sensitivity comparison raises the bound from 192 to 768 on 500 synthetic cases and 46 fixed real files. The 23 selected seed-limited real files fall to one limited file, with one changed output and no labels establishing its quality. Synthetic and unlimited control outputs are unchanged. The optional CLI setting is committed with the existing default retained. Root replayed the changed source and both full output payloads.

The stricter certified-drum replay at `research_local/certified_drums_strict_root_v01` passes all 360 cases, oracle labels and exact telemetry checks. Its audit SHA256 is `a53316d6353e85ef9539f3eaf5d9fb6706d05d08414322efa1e42054ea80a801`. The isolated wheel smoke v04 binds its exact driver and all 236 payload checksums; reference, closed and melody extraction and full reextraction audits pass outside the checkout. Source MIDI bytes remain unchanged.

Local commits now also include `703cafc`, `f117501`, `c59fe8e`, `666eae8`, `b999884` and `306a54a`. Package metadata explicitly distinguishes source/MIDI auditing from complete algorithm selection replay. The paper validator reconstructs external metrics from verified note coordinates and rejects a missing completion receipt or inconsistent frozen cohort. Root passed 40 paper and external-selector tests.

Full builds remain active: indexed session 18207 (about 16,200 sources), closed session 15333 (about 7,500) and melody session 19713 (about 1,800). These progress counts are checkpoints, not final totals. Each runner is immutable. A deterministic source-sample reextraction audit, full-corpus curation descriptions and an isolated Counter iteration experiment are being prepared. Work continues locally until 12:46:15 UTC (14:46:15 Oslo), with no push or publication.

## 2026-10-03 10:34 Oslo: completed indexed extraction and Unicode reader repair

The full indexed build in session 18207 has finished. It accounts for 17,232 inputs, 16,995 successful parses and 237 errors, with 16,923 matched sources and 72 parsed no-match sources. It exports 50,568 melodic and 44,511 percussion candidates (95,079 total), in 74,292 canonical families. Its source manifest SHA256 is `0cac11bb2289cadca8555b0d5eb222d185e9bb797b74bc6c266b16544206143f`, phrase manifest SHA256 `84cb5483eaa38981542a0358a2d0f610b5274b25284a6651440a868e502e68b3`. These extraction totals are not yet a passed audit.

The first frozen full-validator runner stopped before writing an audit result. Root reproduced the cause: `str.splitlines()` splits a valid JSON string at Unicode U+0085 in the selected part name of `Genesis/Mad_Man_Moon.1.mid`. Standard line iteration parses all 17,232 source rows and all 95,079 phrase rows correctly, with unchanged manifest hashes. A bounded fix is replacing JSONL-specific `splitlines()` use while preserving non-JSON text readers and all source/detector output bytes. Regression coverage includes Unicode separators and actual pipeline metadata.

The queued v01 validation wrappers for closed and melody were stopped (owned shell PIDs 4587 and 4604). Their underlying full builds continue normally in sessions 15333 and 19713. Do not restart the old validator. A new immutable validator will be frozen after tests. The old `validation_runner_v01` and failed indexed log remain evidence, with snapshot SHA256 `b96fa22b236dbfec04420ca0b89bf461942c9c939aec27c2872ebbc0a3e166c9`.

The reference selection replay passes all 256 fixed sources with zero failures. Curation diagnostics also replay exactly on every reference source and phrase row; temporal overlap is descriptive and not an error or musical quality label. Local commits `41871a6`, `63b6a8a` and `8996b7d` save verified external paper evidence, stratified selection replay and curation diagnostics. The current paper remains six pages and reference-based. The Counter iteration candidate agrees on all 628 development/pilot cases but gives only about one percent end-to-end timing improvement, so it is not promoted.

The new full reference build comparison at `reference_build_comparison_v02` freezes all 15 local dependency files and reproduces every scientific aggregate from v01. Only receipt and input inventory fields change, now including the completed v03 audit. A paired blinded review pilot and source-verified example figures are being prepared for later human use; no ratings have been invented. The planned next verification is six-worker selection replay of every successful indexed source, once the ordinary audit and Unicode fix pass. Continue to 12:46:15 UTC (14:46:15 Oslo), local only.

## 10:54 Oslo checkpoint: Unicode-safe validation and review tools

Commits `504a985` and `fb8934b` preserve valid U+0085/U+2028/U+2029 within JSONL strings and add explicit all-successful selection replay. Root corrected two mechanical regressions before commit (indentation and trailing blank JSONL rows), then all 481 current tests passed. The Unicode fixture includes both a source path with all three separators and a Latin-1 track name with U+0085. Detector and source MIDI bytes remain unchanged.

Immutable validator `research_local/validation_runner_v02` contains 35 files at commit `fb8934bf45c3520ebc341edac7ca824670cec1c1`, snapshot SHA256 `4fc55d00849ea97a86752749a1f4913eead1b34b335cd1231eea71c688df2cf2`. Wrapper `run_full_validation_v02.sh` is active for indexed (session 1793), closed (42107) and melody (51218). Indexed runs ordinary full audit, schema and diagnostics, then replays every successful source with six workers. Closed and melody wait for their build locks to clear, then run the same checks and a 256-source replay. The full replay is pending, not passed. GC state is not recorded by the build receipts or evidenced launchers; no claim that worker GC was disabled is supported.

Commit `500df27` adds deterministic source-verified recurrence figures, with all 14 focused tests and figure receipt checks passing. Commit `f6b68a9` adds paired listening review. Root browser testing caught and repaired an SVG class assignment error before cards could render. Pilot v03 retains the verified v02 melodic packet and corrects signed integer conversion in deterministic percussion noise. Twelve pairs render, playback starts and stops, and blank export preserves all preferences and notes as null. Seven pairs are identical and five informative. The source and rendered note arrays are checked independently; no human judgements exist.

Installed wheel check `packaging_smoke_v05` passes all eight fixtures under reference, closed and melody variants from commit `500df27`. Root verified all 236 receipt payloads. Full builds and subsequent packaging remain local; no push or publication occurred.

## 11:12 Oslo checkpoint: full indexed artifact audit and portable replay evidence

The Unicode-safe full indexed audit passed, reconstructing all 95,079 exported MIDI excerpts and 16,995 successful source records, with 237 reproducible input errors and zero failures. Schema validation is still running before the queued six-worker all-successful selection replay. Reference all-successful replay is also active in session 66265, using immutable validator v02 with two workers and output `selection_all_reference_v01`. Neither full selection replay is yet complete.

Commit `d0a2c82` packages a completed replay only after receipt, selected cohort, raw cases, detector settings and exact dataset bindings agree. The copied evidence is checked again, and primary artifact auditing remains separate from selection replay. Root passed 68 combined package, receipt, replay and paired-rating tests. The existing 256-source reference replay also passes the new real-data packaging verifier.

Commit `f115a65` corrects a comparison boundary: whether a source has selected phrases is an algorithm output, not source identity. All 17,232 reference and indexed source identities and split assignments agree. Indexed changes 34 no-match files to matched and three matched files to no-match. The failed earlier comparison receipt stays frozen. These transitions do not measure quality.

Commit `3c20815` adds the offline A/B rating analyzer. Root verified the preferred all-null smoke receipt and all seven current packet generator file hashes. The generic analyzer reports internal packet consistency, not independent historical generator or source-note replay. No human ratings exist. Commit `0cadca8` adds concise indexed, closed and part-prior method descriptions to the paper. The draft with the first full comparison still fits six pages; its new methods page was rendered and visually checked. The promoted PDF will be regenerated after remaining full builds and audits.

## 11:43 Oslo checkpoint: portable verification and short phrase recall diagnosis

The full indexed schema check passes all 112,311 rows with no invalid records. Full reference and indexed selection replays remain active, at approximately 10,600 and 3,200 of 16,995 successful sources respectively. The closed and melody builds have processed approximately 15,100 and 8,800 inputs. These are progress counts, not final validation results.

Commit `897091d` adds a portable release verifier. Root independently ran it over the existing reference metadata and archive, reproducing the exact report SHA256 `7a444fe4848e1c12b803a02f534a31a2bae78633b59ec820c039b453b7ac320a`. It verifies 94,950 MIDI payloads, 33 metadata payloads, 94,984 archive members, source status counts and audit bindings, then rechecks input bytes before writing its report. Its 15 local dependency hashes also match. The scope is byte integrity and recorded consistency, without source-note reconstruction or publisher authentication.

Commit `e3691ae` diagnoses all three reference-to-indexed no-match regressions. Root reproduced every raw case row, including full detector outputs and independent generation traces. Each reference pair passes the final aligned verifier but is missed by the seed index. Two fail a full-duration span bucket that is stricter than the verifier; the third has only two shared phase keys under a three-key threshold. These three named files establish a concrete recall gap, not its corpus frequency. A frozen bounded experiment is testing terminal-onset keys and a distinct-offset short-window rescue without changing the active full builds or default algorithm.

Root passed 34 focused no-match, package and portable verification tests. Commit `3b6f664` adds common note-content projections to comparisons, separating prototype changes, recurrence-coordinate changes and complete algorithm-specific payload changes. The new full comparison is running in a fresh directory. All work stays local, with no push or publication. Continue until 12:46:15 UTC (14:46:15 Oslo).

## 12:25 Oslo checkpoint: full reference replay and updated package

The full reference selection replay at `selection_all_reference_v01` passes all 16,995 successful sources with zero discrepancies. The completion receipt SHA256 is `3e606ae6fcf60fd979df9a6e238514f54887e5d0631ebed6102fb66b84cbf830`. Root independently reconstructs exact cohort coverage, successful status and every canonical source record hash. The 237 input errors remain separately reproduced by the ordinary artifact audit.

The new immutable `reference_v04` archive includes the full replay, the consumer guide and screened split views. Its SHA256 is `76bab9daf6ad75cc952bc361ee6f2b1badf6de106c52f9b9574d11a31de676a2`, with 181,957,781 compressed bytes and 95,009 archive members. Portable verification passes all metadata and MIDI payloads. The old v03 release is preserved. A separate archive extraction and recipient-side verification is running.

Commit `8c78bb6` records two bounded seed rescue studies. Replacing short-window keys loses insertion/deletion recoveries and is rejected. A separately frozen union avoids those synthetic losses and recovers two of three exact named regression targets, but changes 19 unlabelled real outputs and adds one saturation-limited source. No production detector changes. Root replays all three methods on 16 targeted cases with exact non-runtime output agreement. All 566 current tests pass in 95.22 seconds.

The closed full build is complete with 50,566 melodic and 44,511 percussion candidates. Its ordinary audit is running before packaging and full-corpus comparisons. Indexed all-successful replay and the melody full build remain active. Continue local work until 12:46:15 UTC, with no push or publication.
