# Recurrence example figures

## Purpose and claim boundary

The figures illustrate one saved melodic recurrence family and one saved percussion recurrence family from the completed audited reference dataset. They show exact source positions, unchanged MIDI pitches and the source tempo map. They are scientific examples of the stored representation. They are not human quality labels and do not establish salience, catchiness, memorability or typicality across the corpus.

## Deterministic selection

The input is `research_local/lakh_phrases_v03`. Its saved audit passed with zero failures and full source coverage. The figure run verifies the audit bindings to both manifests, the summary and the build configuration before selection and rechecks those bytes before completion.

A row is eligible when it belongs to a successful source and has at least three distinct saved occurrence intervals, including its prototype interval. Melodic and percussion rows are ranked independently by SHA256 of the fixed seed, kind, source ID, family ID and phrase ID. The minimum rank is selected for each kind. Scores, filenames, rendered appearance and listening are not selection inputs. The fixed seed is `samuged-recurrence-figure-v1`.

For each selected row, the source path and SHA256 must agree between the phrase and source manifests and with the original MIDI bytes. Metadata repair receipts must exactly match a fresh parse. Melodic slices use the saved part, skyline stream, note index and note count. Percussion slices use the merged source drum ensemble, retaining simultaneous strikes and General MIDI kit pitch IDs. Any source, coordinate or repair mismatch stops the run.

## Figure definition

Each figure contains a timeline followed by three piano rolls.

The timeline spans tick zero through the last source note. It shows every distinct saved occurrence interval for the selected family. The prototype and the two displayed comparison occurrences are highlighted. Source ticks are converted to quarter note beats using the parsed PPQ. The line at the bottom of the timeline is the parsed source tempo map, labelled with its observed BPM range.

The piano rolls show the prototype and the first two other distinct saved occurrence intervals. Each roll starts at beat zero, but its exact source tick interval remains in the panel title. Pitch IDs are unchanged. The three panels share pitch and beat axes so transposition, note substitutions and rhythmic differences remain visible.

## Selected melodic example

The selected row is phrase `f575bd37d402064afc3ca696c2e22483`, family `fcdf1c0f4f45b67c567689cd8999a29ec82893af480881d990b407a74639c511`, from `Chicago/Youre_the_Inspiration.mid`. The source SHA256 is `8c01f348ff60ae3c5d69026029e52a294f67ae0787b0e4c9b4ca7dd52266a9ef`.

The family has four saved occurrences. The displayed source intervals are `[119040, 122750)`, `[126720, 130430)` and `[134400, 138110)` ticks at PPQ 480. Each displayed source slice contains 16 skyline notes. The source tempo is 77.000077 BPM throughout the parsed note span. The extraction method is `reference/approximate`.

![Melodic recurrence example](../../research_local/recurrence_examples_v01/melodic_recurrence.png)

The editable vector form is [melodic_recurrence.svg](../../research_local/recurrence_examples_v01/melodic_recurrence.svg).

## Selected percussion example

The selected row is phrase `7037c51473fc97352446e50104e1f346`, family `8de25015d4646e0a549cb0ff92ba4eaa5acbdf0bab1c452ee3d8e162f793ddf9`, from `Donna_Summer/McArthur_Park.mid`. The source SHA256 is `918fe701631869863c96916f0f6d5fe2cc573fd802cdf4010ae601afa6281dee`.

The family has eight saved occurrences. The displayed source intervals are `[29820, 31740)`, `[31740, 33660)` and `[33660, 35580)` ticks at PPQ 120. The source verified slices contain 57, 55 and 57 drum hits. Simultaneous kit strikes remain separate marks at their original pitch IDs. The source tempo map contains changes from about 85 to 169 BPM. The extraction method is `reference/approximate`.

![Percussion recurrence example](../../research_local/recurrence_examples_v01/percussion_recurrence.png)

The editable vector form is [percussion_recurrence.svg](../../research_local/recurrence_examples_v01/percussion_recurrence.svg).

## Reproduction and receipts

Run from the repository root with the project environment active:

```bash
python scripts/plot_recurrence_examples.py \
  --source "datasets/Lakh MIDI Clean" \
  --dataset research_local/lakh_phrases_v03 \
  --output research_local/recurrence_examples_v01
```

The experiment receipt binds the passed dataset audit, manifest hashes, complete selected rows, original source hashes, repair receipts, fixed selection rule and rendering source snapshot. `selection.json` retains the source verified note slices and tempo maps. The completion receipt binds both JSON results and all four figures.

| Artifact | SHA256 |
| --- | --- |
| `aggregate.json` | `94b7e574b13f84dcfa55c09e28d0b8dcf1b39d0f37140c97aae20c7a210b302b` |
| `selection.json` | `aa955fc96869772da60a0c1ae139c22613c6b8131ace288d56c7834837cdb70a` |
| `melodic_recurrence.png` | `7069b2615615551995b910ab4ddc725eb196be2ff7e8ae7972b3274d86dc761b` |
| `melodic_recurrence.svg` | `79aaa5ff802ff8a2198be13e1d6079fe5a44707e7033a509ad9ba3a9ced4d5e7` |
| `percussion_recurrence.png` | `8b2a1d20010c9531310a6420329c078ff5792bd4d8814a526552216b821e6dec` |
| `percussion_recurrence.svg` | `a4aa770a43e60f4fc58ea1de092836469175ccd22d7e5b9c96c3a325e1672128` |
| `completion_receipt.json` | `9853eebb3c0cd77114df0e14e775fc02517996ee519878a2636c750556200c9e` |

Both PNGs were inspected at full resolution and in cropped detail. Titles, source tick labels, pitch IDs, beat axes, tempo labels and footnote metadata are readable without clipping. The corresponding SVG files have the same layout and retained text labels. No PDF or audio artifact is produced.
