# Familiarity informed hook demonstration

## Purpose

This supplementary ten item set demonstrates recurrent MIDI phrases from songs
with independent song level familiarity evidence. It is a listening interface
cohort, not a benchmark and not a listener study. No source reports a listener
response for the selected SaMuGeD phrase IDs.

The selection keeps recognition, involuntary musical imagery and symbolic
recurrence separate:

- Hooked on Music measured how quickly listeners recognised song sections. A
  later ISMIR paper reproduces its ten leading song labels in Table 1. Nine of
  those labels have exact artist and title path matches in the closed corpus.
- Jakubowski et al. studied self reported involuntary musical imagery. Journey's
  `Dont_Stop_Believin` is appended as a separately labelled tenth song.
- SaMuGeD provides source verified symbolic recurrence evidence. Its score does
  not measure recognition, recall, memorability or earworm occurrence.

Primary sources:

1. Burgoyne, J. A., Bountouridis, D., van Balen, J. M. H. and Honing, H.
   (2013). [Hooked: A game for discovering what makes music catchy](https://www.mcg.uva.nl/mcg-2023/papers/Burgoyne-et-al-2013.pdf).
2. [UvA Music Cognition Group findings](https://www.mcg.uva.nl/news/).
3. Sergaki et al. (2019). [Data driven song recognition estimation using collective memory dynamics models](https://mever.gr/publications/Data-Driven%20Song%20Recognition%20Estimation%20Using%20Collective%20Memory%20Dynamics%20Models.pdf),
   Table 1.
4. Jakubowski et al. (2017). [Dissecting an earworm](https://www.apa.org/pubs/journals/releases/aca-aca0000090.pdf).
5. [Goldsmiths official study summary and reported song list](https://www.gold.ac.uk/news/scientists-find-key-to-writing-catchy-pop-hits/).

## Deterministic order

The first nine rows follow the published Hooked on Music recognition order.
Rank four, `Lady_Gaga/Just_Dance`, has no exact source path match in the closed
corpus and is omitted without closing the rank gap. The tenth row is Journey and
uses the separate earworm occurrence evidence type. This order is not a measured
ranking of the MIDI fragments.

| Demo order | Published rank | Exact corpus source label | Phrase source |
|---:|---:|---|---|
| 1 | 1 | `Spice_Girls/Wannabe.1.mid` | bounded `Girls` lead extraction |
| 2 | 2 | `Lou_Bega/Mambo_No._5_A_Little_Bit_Of..._.mid` | closed manifest |
| 3 | 3 | `Survivor/Eye_Of_The_Tiger.mid` | bounded `Melody` extraction |
| 4 | 5 | `ABBA/S.O.S.1.mid` | closed manifest |
| 5 | 6 | `Roy_Orbison/Oh_Pretty_Woman.2.mid` | closed manifest |
| 6 | 7 | `Michael_Jackson/Beat_It.mid` | closed manifest |
| 7 | 8 | `Whitney_Houston/I_Will_Always_Love_You.4.mid` | bounded `CANTO` extraction |
| 8 | 9 | `The_Human_League/Dont_You_Want_Me.1.mid` | closed manifest |
| 9 | 10 | `Aerosmith/I_Dont_Want_to_Miss_a_Thing.1.mid` | closed manifest |
| 10 | n/a | `Journey/Dont_Stop_Believin.2.mid` | closed manifest |

Seven phrase rows and their MIDI exports are copied unchanged from
`research_local/lakh_aligned_closed_v01`. The three named lead parts are run
through `detect_indexed_part` with the frozen configuration stored in each
source record. Each expected family and source tick interval is asserted. This
is three bounded source file operations rather than a corpus extraction.

Supplement phrase IDs are the first 32 hexadecimal characters of SHA256 over
the namespace `samuged-familiar-hooks-v1`, source ID, source hash, phrase kind,
part index, family ID and start tick. The ID changes if the source or phrase
identity changes. Each occurrence retains the detector's source verification
fields. Candidate, comparison, group, note and window limits are written to
`selection.json`; any capped lead search remains disclosed.

## Build

Activate the repository environment before running Python:

```bash
source .venv/bin/activate
python scripts/curate_familiar_hooks.py
```

The ignored output is `research_local/publication_v01/familiar/`:

- `phrases.jsonl` contains ten renderer ready phrase rows in demo order;
- `sources.jsonl` contains the ten complete closed build source records;
- `selection.json` provides the ordered phrase IDs, evidence URLs, song
  evidence type, rationale, extraction limits and input manifest hashes;
- `midi/melodic/` contains copied or newly exported phrase MIDI.

The source records remain unchanged. For a bounded supplemental phrase, its
standard phrase row and `selection.json` carry the added provenance. This avoids
rewriting a closed source record as though the original full build had selected
the new lead phrase.

The loop renderer accepts `selection.json` directly because it reads the
ordered `candidates` list and each object contains `phrase_id`.

## Publication language

Suitable wording:

> Selected from songs reported as rapidly recognisable in Hooked on Music or
> frequently named as involuntary musical imagery, then filtered for recurrent
> melodic or riff shaped MIDI phrases.

Do not call the phrases scientifically proven hooks or earworms. Artist and
title values are corpus path labels, not verified recording identities. A later
fragment level listener study would be needed to measure recognition or recall.
