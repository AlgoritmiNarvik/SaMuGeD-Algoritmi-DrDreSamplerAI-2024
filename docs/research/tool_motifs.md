# Tool listening case study

A small tribute to one of Almaz Ermilov's favourite bands. Tool's layered rhythms, shifting accents and patient repetition are the reason for this collection.

Producer Sylvia Massy describes progressive arrangements and polyrhythms in her [GRAMMY interview](https://www.grammy.com/news/feature-underneath-undertow-examining-tools-classic-debut-album-25-years-later/). Danny Carey discusses the creative process in a [Modern Drummer interview](https://www.moderndrummer.com/2024/03/danny-carey-modern-drummer-podcast-4/). These sources explain the interest in the band, they do not label individual MIDI fragments.

## Listening collection

Nine source songs provide 27 saved melodic and 21 percussion candidates. Selection keeps up to three melodic and two drum phrases per song, ranked by verified recurrence, while removing identical pitch and timing sequences. This retains bass, guitar, longer phrases and contrasting patterns without applying the general melody diversity filter.

The result is **27 riffs and 14 drum patterns**, plus **20 aligned riff and drum versions**. The Space lets you filter by song or part and switch between Riff only and With drums. Both versions share the same source start, cycle duration and tempo. The combined version adds the actual source drums, it does not mix unrelated drum loops. The occurrence count belongs to the riff, joint repetition of both layers is not independently verified.

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

A source onset diagram shows the riff, kick, snare and other drum attacks over one cycle. Dot size follows MIDI velocity. Listen for coinciding accents and the return to the start of the loop. The grid uses quarter note beats. Riff length and source meter metadata do not establish the song's time signature or detect a polyrhythm.

H. and Intermission have no drum notes in these MIDI arrangements. One Stinkfist bass passage has only one drum hit, so it does not receive a paired version. MIDI instrument names and programs can disagree, source names are retained. These arrangements can simplify the originals. The selection is structural curation, not a listener ranking or a complex rhythm accuracy benchmark. No new corpus extraction is used.

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
