# SaMuGeD status before the pause

This report records the research state at the pause on 3 October 2026. Running calculations had finished and saved their results. Automatic continuation was disabled and no new experiments were running. At that time, all outputs remained local, with no push or publication. The exact technical boundary is in [PAUSE_CHECKPOINT.md](PAUSE_CHECKPOINT.md).

## Results

The local Lakh MIDI Clean snapshot was processed with a pipeline for recurring melodic phrase candidates. Each result stores its source, notes, occurrence coordinates and a MIDI excerpt. Percussion is processed separately, preserving simultaneous hits and drum kit identities.

The run accounted for **17,232 MIDI files**. It parsed 16,995 successfully and recorded errors for 237. Invalid key metadata was recovered in 28 files without changing the source files or note data.

| Variant | Melodic phrases | Percussion patterns | Status at the pause |
| --- | ---: | ---: | --- |
| Reference | 50,439 | 44,511 | Full audit, full selection replay and verified archive |
| Indexed | 50,568 | 44,511 | Full audit and full selection replay, archive not built |
| Closed | 50,566 | 44,511 | Full audit, 256-source selection replay and verified archive |
| Melody prior | 50,566 | 44,511 | Build complete, audit and selection replay not started |

These row counts describe algorithm output. They do not show how listeners would rate the phrases.

## Algorithm findings

**Indexed** matches recurrences that contain inserted or deleted notes. On the same 500 synthetic test cases, occurrence F1 rose from **0.685 to 0.838**. This metric compares found occurrences with known planted recurrences. On a 128-file real pilot, the search took 425 seconds instead of 47 and reached limits more often.

**Closed** selects a verified longer recurrence when it meets the fixed support, geometry and score rules. On a separate new cohort of 500 cases, F1 rose from **0.831 to 0.894** and positive-case recovery rose from 404/423 to 420/423. These values cannot be compared directly with the earlier cohort.

**Melody prior** uses note structure to prefer a melodic part. On 120 heldout POP909 files, agreement with the `MELODY` role rose from 76 to 110. This evaluates part selection, not phrase quality.

External results were mixed. Indexed scored higher F1 on six Theme Transformer songs, while its polyphonic JKU result was lower on five classical works. Reference therefore remained the default. Several short index-key ideas were rejected or retained as experiments because they lost known recurrences or increased search limits.

## Verification

The main test set had **566 passing tests**. A further 1,152 checks covered expected changes under tempo, MIDI resolution and transposition changes. An independent recomputation of 7,000 metric rows found no differences.

Reference and indexed reprocessed **all 16,995 successful sources with no discrepancies**. Closed passed a separate 256-source check. The reference and closed archives passed verification both as archives and after extraction.

Duplicate screening produced a supplementary split that quarantined 766 sources. The remaining splits contain no known strong overlaps under the recorded rule. This does not prove that all covers or related arrangements were found.

Percussion has synthetic and more difficult tests. In the certified negative cohort, both detector modes returned no output in 120/120 cases. In another difficult cohort, output occurred in 7/40 negative cases. These values depend on the test construction and do not establish accuracy on natural music.

## Materials at the pause

- Presentation: `output/presentations/samuged_status_2026-10-03.pptx` and `output/pdf/samuged_status_2026-10-03.pdf`.
- Scientific draft: `output/pdf/samuged_recurring_phrases.pdf`. All 132 input files matched its receipt.
- Reference v04 archive: `research_local/releases/reference_v04.tar.gz`, 182 MB.
- Closed v01 archive: `research_local/releases/closed_v01.tar.gz`, 205 MB.
- Paired review packet: `research_local/paired_review_full_closed_v01/review.html`. It contains no human ratings.
- [Delivery and publication status](DELIVERY.md) and the [local artifact index](artifact_index.md).

## Current publication context

This is an archival pause report. The primary release is `closed_v01`, with 95,077 phrase rows: 50,566 melodic and 44,511 percussion. The conservative `reference_v04` package has 94,950 rows: 50,439 melodic and 44,511 percussion. Neither package contains listener labels, and listener ratings are not required for the algorithmic recurrence release.

The dataset is [Hugging Face: `AlmazErmilov/samuged-recurring-phrases`](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases). The static demo is [Hugging Face Space: `AlmazErmilov/samuged-earworms`](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms). The demo shows real source loop cycles and a separate song-level evidence view for familiar-hook selection. These are algorithmic evidence views, not listener annotations.

For current publication wording and the Lakh rights caveat, see [the research guide](README.md) and [the primary sources note](sources.md).
