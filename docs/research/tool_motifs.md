# Tool listening case study

A small tribute to one of Almaz Ermilov's favourite bands. Tool's layered rhythms, shifting accents and patient repetition are the reason for this collection.

Producer Sylvia Massy describes progressive arrangements and polyrhythms in her [GRAMMY interview](https://www.grammy.com/news/feature-underneath-undertow-examining-tools-classic-debut-album-25-years-later/). Danny Carey discusses the creative process in a [Modern Drummer interview](https://www.moderndrummer.com/2024/03/danny-carey-modern-drummer-podcast-4/). These sources explain the interest in the band, they do not label individual MIDI fragments.

## Listening collection

Nine source songs provide 27 saved melodic and 21 percussion candidates. Selection keeps up to three melodic and two drum phrases per song, ranked by verified recurrence, while removing identical pitch and timing sequences. This retains bass, guitar, longer phrases and contrasting patterns without applying the general melody diversity filter.

The player now contains **37 riffs and 20 drum patterns from 12 songs**. The original nine Lakh songs contribute 27 riffs and 14 drum patterns. Separate web MIDI arrangements add Schism, Lateralus and Forty Six & 2 only to the interface. They do not change any dataset subset.

The 27 paired selections open with source drums. Switch to Melody only or Drums only to compare the identical time window. Tempo and cycle length match. Counts belong to the detected riff, joint and accompaniment recurrence are not independently verified.

| Song | Riffs | Drum patterns | Paired versions |
| --- | --- | --- | --- |
| Eulogy | 3 | 2 | 3 |
| Flood | 3 | 2 | 3 |
| H. | 3 | 0 | 0 |
| Hush | 3 | 2 | 3 |
| Intermission | 3 | 0 | 0 |
| Intolerance | 3 | 2 | 3 |
| Prison Sex | 3 | 2 | 3 |
| Sober | 3 | 2 | 3 |
| Stinkfist | 3 | 2 | 2 |
| Schism (interface supplement) | 4 | 2 | 3 |
| Lateralus (interface supplement) | 3 | 2 | 2 |
| Forty Six & 2 (interface supplement) | 3 | 2 | 2 |

A source onset diagram shows the riff, kick, snare and other drum attacks over one cycle. Dot size follows MIDI velocity. Listen for coinciding accents and the return to the start of the loop. The grid uses quarter note beats. Riff length and source meter metadata do not establish the song's time signature or detect a polyrhythm.

H. and Intermission have no drum notes in these MIDI arrangements. One Stinkfist bass passage has only one drum hit, so it does not receive a paired version. MIDI instrument names and programs can disagree, source names are retained. These arrangements can simplify the originals. The selection is structural curation, not a listener ranking or a complex rhythm accuracy benchmark. The primary corpus is unchanged. The three external songs were processed separately with aligned_closed and a 12 candidate shortlist per kind.

## Reproduce

```sh
source .venv/bin/activate
python -m scripts.select_tool_motifs \
  --dataset research_local/lakh_aligned_closed_v01 \
  --output PUBLICATION_BASE/tool_selection_expanded.json
python scripts/render_audio_loops.py \
  --phrase-ids-json PUBLICATION_BASE/tool_selection_expanded.json \
  --dataset research_local/lakh_aligned_closed_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --soundfont AUTHENTIC_FLUIDR3_GM.sf2 \
  --output PUBLICATION_BASE/tool_audio_expanded --flac
python -m scripts.render_tool_layers \
  --base PUBLICATION_BASE --source 'datasets/Lakh MIDI Clean' \
  --soundfont AUTHENTIC_FLUIDR3_GM.sf2 \
  --output PUBLICATION_BASE/tool_layers
```

Use a new publication base and new output paths. The selection records both manifest hashes and source search limits. Rendering binds source notes, source hashes, renderer provenance and output bytes. The paired MIDI verification compares source drum note attacks and preserves the riff and tempo tracks exactly. Popular songs remains the first and default collection.

## Changing meters

A [published drum transcription](https://drummersonly.co.uk/the-tools-of-danny-carey/) describes a Lateralus passage as consecutive bars of 9/8, 8/8 and 7/8. These changing bar lengths are not three simultaneous rhythms. The interface gives this song context separately from its source note diagram. Neither a loop length nor a MIDI meter event establishes the meter of the original recording. The chosen Lateralus snippets do not claim to reproduce that exact passage.

## External listening sources

[Schism](https://midifind.com/files/t/tool/tool_schism_7/1822-1-0-60610), [Lateralus](https://midifind.com/files/t/tool/tool_lateralus/1822-1-0-60548) and [Forty Six & 2](https://midifind.com/files/t/tool/tool_forty_six_2/1822-1-0-60518) use downloaded MIDI arrangements. Source hashes, phrase choices and renderer receipts are in the Space rendering directory. Full source songs are not distributed. The pages provide downloads and describe creative use but do not state an explicit redistribution license. These excerpts are outside the Lakh attribution claim.

Schism replaces 2 Become 1 in the live Popular songs listening collection. Its first position is a personal feature, not a measured popularity or recurrence rank. The original analytic CSV cohort and the primary dataset remain available without this change.

The external builds use the same CLI with a separate source directory, aligned_closed, top_k=12 and percussion enabled. Run scripts/curate_schism_demo.py or scripts/curate_external_tool.py on the corresponding build, then render_audio_loops.py. render_source_layers.py adds drums from each identical source cycle. render_drum_solos.py renders those verified drum layers alone. Their manifests bind the input MIDI, code and output hashes.
