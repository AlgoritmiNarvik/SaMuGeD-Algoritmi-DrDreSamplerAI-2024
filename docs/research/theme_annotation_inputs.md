# Theme Transformer annotation inputs

This note records a read-only audit of the six official Theme Transformer input archives stored under `research_local/external/theme_transformer/`. The audit compares the three human annotation files and the published baseline MIDI files before defining an evaluation domain. It does not run the SaMuGeD detector and does not claim that the six songs represent complete phrase families.

## Primary sources and provenance

The [Theme Transformer homepage](https://atosystem.github.io/ThemeTransformer/) publishes qualitative results and links to the six song archives. The [theme retrieval details](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html) describe a small manual annotation study on six songs from the POP909 test set. The page says that three musically trained annotators marked theme regions by beat indices, that the labels are subjective, that regions are roughly two to four bars and need not start or end on bar lines and that results are reported against each annotator with F1 and Cohen's kappa. Archive links follow the official pattern `https://atosystem.github.io/ThemeTransformer/thmret/{song}.zip`.

The local download receipt is `research_local/external/theme_transformer/download_receipts.json`, SHA-256 `d19f5d8814f15e0177c6a16b989dcb9a6cdd9d012e279a9526d2217d8b970868`. The six local archive hashes are:

| song | archive | SHA-256 |
| --- | --- | --- |
| 065 | `065.zip` | `85b61c47c81e6fd408ba0d96ee2a1726d96b7ba500ae9008248bb6daa16d712e` |
| 284 | `284.zip` | `46c8588751950a1dc5b4332e802760effc207a5844f015565a01f94939ed508b` |
| 310 | `310.zip` | `7e32a7ef3393067d567bd1ca3490eb3051947bf5b569788da42bf4cc85ad5c1d` |
| 422 | `422.zip` | `52fdebcf8ef4182c01f576203bae126832553f2ffb1910b532e26ed7780bd8e2` |
| 449 | `449.zip` | `8b5f983b77942adda7c7860b23d4f8fdf388cce685d9b29451bdc74524dcfada` |
| 464 | `464.zip` | `fa0cfbbadefbb9b520e8251f538628924f4570c56a68d6207b12f896d9966c34` |

The machine-readable audit receipt is [`research_local/theme_annotation_input_audit.json`](../../research_local/theme_annotation_input_audit.json). It contains every MIDI member hash, parser observations and comparison counts.

## Read and comparison method

Each ZIP was opened with Python `zipfile.ZipFile` over an in-memory `BytesIO` buffer. No archive member was extracted to disk. MIDI files were parsed with `mido` after activating the repository `.venv`.

Every archive MIDI file is type 1 with three tracks and PPQ 480. Track index 0 contains tempo and other metadata and no notes. Track index 1 is named `melody` (or `MELODY`) and track index 2 is named `Theme Regions`. The README describes the two musical tracks as Track 1 non-theme notes and Track 2 theme notes; the zero-based MIDI track indices therefore appear as 1 and 2 after the metadata track.

Notes were reconstructed from absolute MIDI ticks and matched note-on/note-off events. The comparison identity is the multiset tuple `(onset beat, end beat, MIDI pitch, note-on velocity)` after dividing ticks by PPQ. MIDI channel is excluded because it is not part of the published note identity used here. A second identity, `(onset beat, MIDI pitch, note-on velocity)`, detects duration-only changes. No file had unmatched note starts.

## Findings

All three annotator files for each song have exactly the same full melody multiset under the normalized four-field identity. This holds for all six songs. The annotators differ only in which notes they assign to the two tracks. Exact track 1 and track 2 overlap is zero in every annotator file and every baseline file, so an exact note event is assigned to one musical track in each file.

| song | full melody notes | annotator non-theme counts | annotator theme counts |
| --- | ---: | --- | --- |
| 065 | 286 | A0 130, A1 138, A2 99 | A0 156, A1 148, A2 187 |
| 284 | 341 | A0 240, A1 207, A2 240 | A0 101, A1 134, A2 101 |
| 310 | 433 | A0 277, A1 325, A2 157 | A0 156, A1 108, A2 276 |
| 422 | 443 | A0 339, A1 327, A2 184 | A0 104, A1 116, A2 259 |
| 449 | 379 | A0 275, A1 140, A2 120 | A0 104, A1 239, A2 259 |
| 464 | 405 | A0 280, A1 338, A2 184 | A0 125, A1 67, A2 221 |

The 30 published baseline files do not share the full melody union with Annotator 0. The table reports multiset additions and removals as `added/removed`; they are exact four-field differences, followed by the corresponding onset/pitch/velocity identity differences. `duration-only` counts shared onset/pitch/velocity identities whose end beat differs.

| song | method | baseline notes | exact added/removed | identity added/removed | duration-only |
| --- | --- | ---: | ---: | ---: | ---: |
| 065 | Cl | 286 | 105/105 | 105/105 | 0 |
| 065 | Cl_wo_NoteDur | 286 | 63/63 | 63/63 | 0 |
| 065 | Cl_wo_PthSft | 286 | 162/162 | 162/162 | 0 |
| 065 | Cm | 285 | 87/88 | 87/88 | 0 |
| 065 | Cosiatec | 286 | 12/12 | 12/12 | 0 |
| 284 | Cl | 341 | 45/45 | 45/45 | 0 |
| 284 | Cl_wo_NoteDur | 341 | 40/40 | 40/40 | 0 |
| 284 | Cl_wo_PthSft | 341 | 55/55 | 55/55 | 0 |
| 284 | Cm | 341 | 116/116 | 116/116 | 0 |
| 284 | Cosiatec | 341 | 6/6 | 6/6 | 0 |
| 310 | Cl | 433 | 150/150 | 150/150 | 0 |
| 310 | Cl_wo_NoteDur | 433 | 72/72 | 72/72 | 0 |
| 310 | Cl_wo_PthSft | 433 | 228/228 | 228/228 | 0 |
| 310 | Cm | 433 | 174/174 | 174/174 | 0 |
| 310 | Cosiatec | 433 | 14/14 | 14/14 | 0 |
| 422 | Cl | 443 | 21/21 | 21/21 | 0 |
| 422 | Cl_wo_NoteDur | 443 | 5/5 | 5/5 | 0 |
| 422 | Cl_wo_PthSft | 443 | 100/100 | 100/100 | 0 |
| 422 | Cm | 443 | 87/87 | 87/87 | 0 |
| 422 | Cosiatec | 443 | 6/6 | 6/6 | 0 |
| 449 | Cl | 379 | 18/18 | 18/18 | 0 |
| 449 | Cl_wo_NoteDur | 379 | 18/18 | 18/18 | 0 |
| 449 | Cl_wo_PthSft | 379 | 18/18 | 18/18 | 0 |
| 449 | Cm | 379 | 35/35 | 35/35 | 0 |
| 449 | Cosiatec | 379 | 3/3 | 2/2 | 1 |
| 464 | Cl | 405 | 96/96 | 96/96 | 0 |
| 464 | Cl_wo_NoteDur | 405 | 57/57 | 57/57 | 0 |
| 464 | Cl_wo_PthSft | 405 | 96/96 | 96/96 | 0 |
| 464 | Cm | 405 | 63/63 | 63/63 | 0 |
| 464 | Cosiatec | 405 | 9/9 | 7/7 | 2 |

Thus the baseline files are not alternate encodings of the same full melody input. Most differences change onset, pitch or velocity. The only duration-only cases are one shared identity in `449_Cosiatec` and two in `464_Cosiatec`. The 065 Cm file also has one fewer note than the annotator union.

## Comparison with official POP909 source MIDI

The six official POP909 source MIDI files were downloaded from the URLs recorded in `research_local/external/theme_transformer/pop909_original/download_receipts.json`. The receipt SHA-256 is `af1c0dc74a10324cd9bc2f805eb15cc9549215421e385ea96b86256d46462a32`; each source file was read directly from disk with `mido` over `BytesIO` and was not modified.

The source MIDI track named `MELODY` has the same note count and the same rank-ordered pitch and note-on velocity sequence as the canonical annotator union for every song. It does not have an exact normalized `(onset beat, end beat, MIDI pitch, note-on velocity)` multiset match in any song. Since note counts are equal, each comparison has the full song note count added and removed under the exact tuple. The timing differences are systematic shifts or rescaling rather than a different pitch or velocity sequence:

| song | melody notes | exact added/removed | pitch/velocity rank match | source onset fit from annotation ticks | bridge notes | piano notes |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| 065 | 286 | 286/286 | 286/286 | `1.000010 * t + 2729` | 376 | 1710 |
| 284 | 341 | 341/341 | 341/341 | `0.999980 * t + 3935` | 226 | 1312 |
| 310 | 433 | 433/433 | 433/433 | `1.002728 * t + 1579` | 165 | 1083 |
| 422 | 443 | 443/443 | 443/443 | `0.499986 * t + 698` | 388 | 1270 |
| 449 | 379 | 379/379 | 379/379 | `0.999998 * t + 120` | 500 | 1269 |
| 464 | 405 | 405/405 | 405/405 | `1.000000 * t + 398` | 118 | 1069 |

The affine fit is descriptive only and is not used to turn non-identical timing into an exact match. It shows that the annotation files preserve the official melody's pitch and velocity content while using a shifted, quantized or rescaled timing representation. Song 422 has an approximately 0.5 timing scale relative to the official source. The official files also contain separate `BRIDGE` and `PIANO` tracks with the note counts shown above. Those accompaniment tracks are outside the annotation-derived melody universe, so the canonical input is the official `MELODY` content with revised timing and with bridge and accompaniment excluded.

The official source download receipt and per-file hashes are included in the machine-readable audit. The source URLs resolve through the [POP909 dataset repository](https://github.com/music-x-lab/POP909-Dataset), while the annotation archive provenance remains the [Theme Transformer homepage](https://atosystem.github.io/ThemeTransformer/) and [theme retrieval details](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html).

## Recommended evaluation domain

Use these archives as a six-song POP909 theme-retrieval diagnostic. Define the canonical note universe for each song as the exact four-field union from any one human annotator file, since all three unions are identical. Keep each annotator's Track 2 assignment as a separate gold view. Do not collapse the three labels into a majority label because the assignment counts show substantial disagreement.

The primary result should score note labels on the canonical universe using exact note identity and report precision, recall and F1 separately for each song and annotator, with macro and micro aggregates clearly separated. Preserve the note identity tuple in result files so the evaluation is reproducible. Report the annotator disagreement through the three per-annotator scores rather than presenting one consensus as ground truth.

For an algorithm that emits a different melody union, report input coverage first: the count and fraction of predicted note identities in the canonical universe and the count of out-of-domain predictions. Score theme labels on the canonical identities that are present, with coverage and out-of-domain predictions kept as separate quantities. A full-union comparison can be reported as a distinct result, but it should not be described as a shared-input comparison for the published baseline files.

A beat-region metric is appropriate only when the original beat-index annotations are available as explicit labels. The local MIDI files provide note-track assignments, not a separately encoded canonical boundary consensus. Do not infer beat regions from the first or last note, quantize boundaries to bars or interpolate missing beat labels. If beat-level labels are later recovered from the primary annotation source, pre-register the beat tolerance and report it as a sensitivity analysis alongside the exact note metric.

## Limitations and uncertainty

The official page characterizes the annotation as subjective and the sample contains only six songs. The archives support exact note assignment comparisons and show identical annotator melody inputs, but they do not establish complete phrase-family coverage, a unique theme consensus or a corpus-wide quality estimate. The README's two-track wording refers to the musical tracks; the parsed files also contain a metadata track at index 0. The published baseline MIDI inputs differ from the human melody union, so baseline scores need an explicit coverage convention. No source annotation was treated as more authoritative than another.
