# POP909 theme annotation diagnostic

## Scope

The [Theme Transformer theme retrieval page](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html) describes annotations from three people with musical training for six POP909 test songs. The page emphasizes that theme labeling is subjective, gives annotators freedom to choose boundaries away from bar lines and suggests regions of roughly two to four bars. It reports beat-region F1 against each annotator and Cohen kappa.

This local evaluation asks a narrower question: how often do notes covered by SaMuGeD's highest-ranked recurring phrase families coincide with the notes placed on the human `Theme Regions` track? It is an exact note-classification diagnostic. It does not reproduce the authors' beat-region F1, score occurrence families or establish corpus accuracy, musical quality or memorability.

## Frozen inputs and adapter

The run uses the six official annotation archives recorded in [`theme_annotation_input_audit.json`](../../research_local/theme_annotation_input_audit.json). Each archive contains three human files and five published method outputs. The evaluator reads MIDI members in memory and independently verifies the recorded archive and human-member hashes.

For each song, annotator 0's two musical tracks are merged into one part. The adapter replaces the track, channel, program and name with track 0, channel 0, acoustic grand piano program 0 and `canonical_melody`. This removes the annotation partition identity before detection. A note identity is the exact tuple `(onset beat, end beat, MIDI pitch, note-on velocity)`, represented with rational beat values.

The adapter checks all three annotator files before scoring:

- Their normalized note multisets are exactly equal for each song.
- The metadata track contains no notes and Tracks 1 and 2 are nonempty and disjoint.
- The shared universe has no duplicate exact note identities, so every label joins to one canonical source index.
- PPQ and meter metadata agree. All files use 480 PPQ and 4/4.
- Tempo metadata does not agree. Annotator 0 carries the song tempo, while annotators 1 and 2 carry 600,000 microseconds per beat. The canonical song uses annotator 0 metadata. Scoring uses exact beat-normalized identities, so this tempo difference does not change labels.

The input audit also compares the annotation domain with the six downloaded POP909 source MIDIs. Each official `MELODY` track has the same note count and rank-ordered pitch and velocity sequence as the canonical annotation union. None has the same exact onset and end identity. Five songs have systematic timing shifts and song 422 has an approximately 0.5 timing scale plus an offset. The diagnostic therefore uses the common annotation timing domain. It does not substitute the original POP909 files or include their `BRIDGE` and `PIANO` tracks.

## Frozen evaluation design

The run uses unchanged default detector settings with `top_k=3`:

- Reference extractor in exact mode
- Reference extractor in transposed mode
- Reference extractor in approximate mode
- Indexed aligned extractor

No threshold or ranking parameter was selected from these six songs. The primary prediction is the set of exact canonical source-note indices in every verified occurrence of the top-ranked candidate. The sensitivity view takes the union for the top three candidates. Reference and aligned occurrences are joined through their skyline source indices and checked against their reported source ticks. No region is inferred from temporal gaps.

Precision, recall and F1 are calculated separately for each of the 18 song-annotator views. Per-song values average the three annotators. Macro results average the six songs so each song has equal weight. The 95% percentile interval resamples six songs with replacement 10,000 times using seed `20261003`; all three annotators remain together within each sampled song.

Pairwise raw agreement and Cohen kappa use every note in each song as a binary labeling item. These are note-domain agreement measures and should not be compared numerically with the authors' beat-domain values.

## Results

Primary top-one results:

| Detector | Precision | Recall | F1 | F1 95% song bootstrap interval |
| --- | ---: | ---: | ---: | ---: |
| Reference exact | 0.491 | 0.158 | 0.234 | 0.118 to 0.370 |
| Reference transposed | 0.491 | 0.158 | 0.234 | 0.118 to 0.370 |
| Reference approximate | 0.466 | 0.156 | 0.228 | 0.113 to 0.367 |
| Aligned indexed | 0.472 | 0.252 | 0.323 | 0.187 to 0.485 |

Top-three sensitivity results:

| Detector | Precision | Recall | F1 | F1 95% song bootstrap interval |
| --- | ---: | ---: | ---: | ---: |
| Reference exact | 0.539 | 0.403 | 0.445 | 0.346 to 0.594 |
| Reference transposed | 0.539 | 0.403 | 0.445 | 0.346 to 0.594 |
| Reference approximate | 0.539 | 0.424 | 0.452 | 0.355 to 0.595 |
| Aligned indexed | 0.481 | 0.488 | 0.465 | 0.280 to 0.641 |

The higher top-three F1 is a labelled sensitivity view. It expands predicted note coverage and cannot be interpreted as a top-one ranking improvement. Exact and transposed modes happened to return identical predictions on these six inputs. That does not establish general equivalence.

Mean F1 over the three annotators by song:

| Primary top one | 065 | 284 | 310 | 422 | 449 | 464 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reference exact | 0.539 | 0.176 | 0.111 | 0.057 | 0.322 | 0.198 |
| Reference transposed | 0.539 | 0.176 | 0.111 | 0.057 | 0.322 | 0.198 |
| Reference approximate | 0.539 | 0.329 | 0.111 | 0.057 | 0.134 | 0.198 |
| Aligned indexed | 0.681 | 0.151 | 0.410 | 0.128 | 0.339 | 0.227 |

| Top-three sensitivity | 065 | 284 | 310 | 422 | 449 | 464 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reference exact | 0.789 | 0.332 | 0.445 | 0.321 | 0.438 | 0.344 |
| Reference transposed | 0.789 | 0.332 | 0.445 | 0.321 | 0.438 | 0.344 |
| Reference approximate | 0.789 | 0.378 | 0.445 | 0.321 | 0.437 | 0.344 |
| Aligned indexed | 0.832 | 0.430 | 0.469 | 0.098 | 0.550 | 0.409 |

Human note-label agreement varies sharply:

| Song | Mean raw agreement | Pairwise raw range | Mean kappa | Pairwise kappa range |
| --- | ---: | ---: | ---: | ---: |
| 065 | 0.867 | 0.815 to 0.930 | 0.730 | 0.625 to 0.860 |
| 284 | 0.457 | 0.334 to 0.701 | -0.212 | -0.459 to 0.283 |
| 310 | 0.409 | 0.113 to 0.723 | -0.164 | -0.559 to 0.485 |
| 422 | 0.688 | 0.650 to 0.756 | 0.358 | 0.348 to 0.369 |
| 449 | 0.333 | 0.314 to 0.348 | -0.273 | -0.517 to -0.136 |
| 464 | 0.524 | 0.289 to 0.669 | 0.009 | -0.340 to 0.256 |

The negative kappas and wide detector intervals are material. Six songs are too few for a stable population estimate and the labels do not define one consensus theme.

## Bounds, runtime and published outputs

All 24 detector runs produced three ranked candidates. No run reached the note, window, comparison, seed-bucket or group search bounds. Every run did reach the default 80-candidate curation cap before final diversity selection. Results are valid outputs of the frozen defaults, but the cap means this diagnostic does not show what an unbounded candidate pool would rank.

| Detector | Six-song runtime | Search-limited songs | Curation-truncated songs |
| --- | ---: | ---: | ---: |
| Reference exact | 0.177 s | 0 | 6 |
| Reference transposed | 0.191 s | 0 | 6 |
| Reference approximate | 0.267 s | 0 | 6 |
| Aligned indexed | 2.673 s | 0 | 6 |

These are single local timings from the preferred v02 run for provenance, not a performance benchmark. Earlier v01 timings are not reused here.

All 30 published method MIDIs differ from the canonical full note universe. Their exact canonical-note coverage ranges from 0.434 to 0.992, with a mean of 0.824. The run reports coverage only. It does not calculate or compare F1 for those files because doing so would mix prediction labels with changed input notes.

## Reproducibility artifacts

The preferred completed run is [`research_local/theme_evaluation_v02`](../../research_local/theme_evaluation_v02). Its scientific fields match v01 after excluding receipt, source snapshot and runtime provenance fields. The v01 directory remains a historical earlier receipt-backed run and is not the preferred reference.

- Start receipt SHA-256: `d55ae8d29338cec4172f3c617f3a10cf10f32b822819204f5778cb2c5c5e5361`
- Completion receipt SHA-256: `f225e3d57784f11ea9010dbefdf0015f508c59cfb3a93b763578778afaf89329`
- Frozen source snapshot SHA-256: `67675145e919955a0dc55182592b0aaec2ff5e9099cd501a4092d0ea7ef286d2`
- Input audit SHA-256: `6ef0eb464551816b640e46f96af4adec783cced625cf36b0a822cb7b8721da8e`
- Original POP909 source receipt SHA-256: `af1c0dc74a10324cd9bc2f805eb15cc9549215421e385ea96b86256d46462a32`
- Raw results SHA-256: `458c682ab67fab385907968b5b4234a12ca43a6b758ca5c90ea527fcef8ec3df`
- Aggregate results SHA-256: `57306121f8e17f7916c7035b06a5bb57784718f71e2ef7086b2c3abc988e8cd4`

The initial receipt remains `started`. A separate `completion_receipt.json` binds the raw and aggregate result bytes to that receipt, detector configuration, cohort and executable source snapshot. The full per-annotator metrics, prediction indices, cap telemetry, input coverage and member hashes are in `raw_results.json` and `aggregate.json`. The preferred v02 completion receipt verifies successfully; the report remains a note-domain diagnostic rather than the authors' beat-domain evaluation.
