# POP909 source part role diagnostic

This diagnostic measures which full source parts are selected by the unchanged detector configurations. It uses the six official POP909 MIDI files already recorded under `research_local/external/theme_transformer/pop909_original`. The source receipts and files were checked byte for byte before execution.

The track names are dataset specific role labels: `MELODY` is melody, `BRIDGE` is bridge and `PIANO` is piano. Bridge and piano are grouped as accompaniment for the summary. These labels describe source track names. They are not human theme labels and this report does not calculate theme F1 or phrase quality.

The frozen cohort contains all six full multitrack files:

| song | bridge notes | piano notes | melody notes | PPQ |
| --- | ---: | ---: | ---: | ---: |
| 065 | 376 | 1,710 | 286 | 480 |
| 284 | 226 | 1,312 | 341 | 480 |
| 310 | 165 | 1,083 | 433 | 480 |
| 422 | 388 | 1,270 | 443 | 480 |
| 449 | 500 | 1,269 | 379 | 480 |
| 464 | 118 | 1,069 | 405 | 480 |

The two frozen runs used `Config(mode="approximate", top_k=3)` and `AlignedConfig(top_k=3)` through `extract_indexed`. Each run returned three retained candidates and none reported a search limit. Separately, every run reached the fixed 80-candidate per-part shortlist cap: the complete saved shortlist contained 160 to 240 candidates before final top-three selection. This per-part cap, rather than `top_k=3`, is what the recorded `curation_truncated` flag denotes.

| method | top one melody | top one bridge | top one piano | top three melody | top three bridge | top three piano |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| reference approximate | 3/6 | 0/6 | 3/6 | 11/18 | 0/18 | 7/18 |
| aligned indexed | 3/6 | 1/6 | 2/6 | 10/18 | 2/18 | 6/18 |

Top one selections by song were:

| song | reference approximate | aligned indexed |
| --- | --- | --- |
| 065 | PIANO | PIANO |
| 284 | MELODY | MELODY |
| 310 | PIANO | BRIDGE |
| 422 | MELODY | MELODY |
| 449 | MELODY | MELODY |
| 464 | PIANO | PIANO |

Accompaniment supplied three of six top one selections for both methods. It supplied 7 of 18 retained top three candidates for the reference method and 8 of 18 for the aligned method. The preregistered diagnostic flag was set only when bridge plus piano exceeded half of top one selections, so neither method is flagged. The result still shows that piano can rank ahead of the named melody part on this small source specific cohort.

Every retained candidate in the raw result has the source part index, track, channel, program, original part name and role label. Every occurrence retains its emitted start and end ticks, skyline note index, note count, similarity and transposition. The diagnostic also records the corresponding original `Part.notes` indices and checks that the occurrence coordinates reconstruct the source part interval. All 36 retained candidate rows had all occurrences source verified. Aligned rows retain their emitted edit, matched pair and `source_verified` fields.

The complete machine readable result is `research_local/pop909_part_role_v01`. It contains `design.json`, immutable start and completion receipts, the executable source snapshot, `raw_results.json` with all retained candidate details and `aggregate.json` with role counts. The completed receipt verifies the raw and aggregate bytes. The source receipt manifest hash is `af1c0dc74a10324cd9bc2f805eb15cc9549215421e385ea96b86256d46462a32`. The frozen source hashes and code snapshot hashes are recorded in the design and receipts.

The official source reference is the [POP909 dataset repository](https://github.com/music-x-lab/POP909-Dataset). This result diagnoses source part selection. It does not establish that a selected part contains a human theme, that the detector has musical phrase quality or that these six songs represent the wider corpus. The annotation archives use a different note timing and track construction, so their theme labels were intentionally not used here.
