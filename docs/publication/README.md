# SaMuGeD Earworms publication and loop rendering

Ostinato / Catchy musical hooks. Separate drum patterns are included.

The public dataset contains the audited closed corpus and a reference baseline.
The static Space contains 630 rendered cycles across three top 50 listening collections, ten familiar songs and Tool’s ostinatos. Tool has 69 riffs and 36 drum patterns from 28 songs, with 59 aligned three mode comparisons. Popular songs opens first, with Schism as the first selection. The separate atlas retains five analysis views and uses the same SoundFont audio.
The ten familiar song selections have separate song level research evidence.
They are not listener validated fragment labels.

## Inputs

The publication builder needs the completed local release metadata and archives,
the corresponding extraction directories and the original source MIDI snapshot.
The archives contain executable provenance and exact source hashes. The original
upstream acquisition checksum is unavailable, so a fresh download should not be
assumed to reproduce the processed snapshot byte for byte.

Activate the environment and install publication dependencies:

```sh
source .venv/bin/activate
uv pip install -r requirements-research.lock -r requirements-publication.lock
```

Audio rendering also needs FluidSynth and FFmpeg. The initial renders used
FluidSynth 2.5.6 and FFmpeg 8.0.1. The authentic FluidR3 GM file came from the
[Debian fluid soundfont package](https://deb.debian.org/debian/pool/main/f/fluid-soundfont/fluid-soundfont-gm_3.1-5.3_all.deb).
Its SHA256 is `74594e8f4250680adf590507a306655a299935343583256f3b722c48a1bc1cb0`.
The included Debian copyright file records the SoundFont licence. The legacy
file with the same filename in this repository is a different font.

## Prepare data

```sh
python -m scripts.prepare_publication --output NEW_PUBLIC_DATASET_DIR
python -m scripts.curate_familiar_hooks \
  --dataset research_local/lakh_aligned_closed_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --output NEW_FAMILIAR_DIR
```

The first command changes presentation metadata only. It retains the old
archives, regenerates checksums and creates four Parquet views. The second
command copies seven saved phrases and extracts three fixed leading parts.
It asserts their source hashes, candidate identities and coordinates.
See [familiar hook selection](../research/familiar_hooks.md) for evidence and
[top 50 analytics](../research/top50_analytics.md) for the recurrence ranking.

## Render cycles

```sh
python scripts/render_audio_loops.py \
  --phrase-ids-json SELECTED_PHRASES.json \
  --dataset PHRASE_DATASET_DIR \
  --source 'datasets/Lakh MIDI Clean' \
  --soundfont AUTHENTIC_FLUIDR3_GM.sf2 \
  --output NEW_AUDIO_DIR --flac
```

The selection JSON contains a `candidates` list with `phrase_id` fields.
Measured occurrence start differences determine supported cycle lengths.
Otherwise the source meter at the phrase start defines whole bar padding.
This fallback formats a loop and does not establish phrase boundaries.
Later meter changes remain in the MIDI but do not alter the fallback boundary.

The renderer uses every selected part note onset inside the cycle, clips note
ends at the cycle boundary and preserves pitch, velocity, tempo and program.
It renders six cycles and cuts one middle cycle to carry earlier releases and
reverb into the beginning. Symmetric endpoint correction affects 5 milliseconds
on each side only when the boundary step exceeds the recorded threshold.
WAV is 48 kHz stereo PCM 24 bit with a peak target of minus 1 dBFS.
The manifest binds source bytes, renderer code, library versions and tool versions.

The static player decodes lossless FLAC into a Web Audio buffer and sets `loop = true`.
Only one loop plays at a time. Selecting another phrase while playing continues with that phrase. Stop and page exit end playback.
MP3 is optional export only, it is not used for canonical looping. The atlas uses the same lossless renders and continuous playback. It contains no oscillator or noise preview. Its note plot shows the detector excerpt while audio covers the complete source cycle.

## Assemble and publish

The Space builder expects `recurrence_selection.json`, `familiar/`,
`recurrence_audio/`, `familiar_audio/`, optional `tool_selection_expanded.json`, `tool_audio_expanded/` and `tool_layers/`, plus the font package under its base directory.
All audio directories must contain completed render manifests and receipts. To include the atlas, provide `atlas/` and render its missing phrase IDs into `atlas_audio/`. The builder checks audio coverage for every shown phrase. Optional `piano_audio/` contains labelled timbre alternatives. `source_layers/` adds source drum accompaniment. `schism_audio/`, `external_tool_audio/`, `external_tool_layers/` and `drum_solos/` provide the separate Tool listening supplements. These are not added to the four dataset subsets.
See the Tool case study for the selection and aligned layer rendering commands.

```sh
python -m scripts.build_loop_space --base PUBLICATION_BASE --output NEW_SPACE_DIR --compact-audio
python -m scripts.publish_huggingface \
  --owner ACCOUNT_NAME --dataset PUBLIC_DATASET_DIR --space PUBLIC_SPACE_DIR \
  --receipt UPLOAD_RECEIPT.json
```

The upload command previews file counts and sizes by default. Add `--publish`
when publication is authorised. It verifies the authenticated owner, uploads
explicit file inventories and records both remote commit IDs. Local metadata
copies used for archive verification are excluded from the upload.

Verify the hosted dataset, Parquet row counts, archive checksums and Space
playback after upload. The experimental melody variant is excluded from the release.

The [Tool case study](../research/tool_motifs.md) retains bass riffs and separate percussion. The interface uses square edges, dark gray panels and the Inter font. Its SIL OFL license is under `docs/assets/inter/`. Two Mermaid charts in the root README describe the method and outputs.

The piano preview for 2 Become 1 retains source notes, velocities, tempo and cycle length. It changes the loop MIDI program to 0 and records the original program 25 in metadata. Source instrument and Piano preview are separate choices, the primary dataset is unchanged.

Both listening views start at 50 percent volume and include a volume slider. The SaMuGeD Earworms wordmark uses Adamas by Colorblind. Other text uses Inter. Only the outlined logo is distributed, with source and use terms in `docs/assets/adamas/NOTICE.txt`. Popular songs has no Featured badge or introductory paragraph.

Playback uses lossless FLAC. The WAV button decodes it at 48 kHz and exports stereo PCM 24 bit in the browser. Playback volume does not change downloads. Original render hashes remain in the rendering receipts.

## Sharing preview

Both player pages use the Adamas wordmark and a versioned 1200 by 630 sharing image. The Space card sets the same image through Hugging Face's [thumbnail field](https://huggingface.co/docs/hub/spaces-config-reference). Open Graph and Twitter card metadata cover direct player links. Messaging services can retain an older cached preview.

The outlined artwork and generated PNG are under `docs/assets/adamas/`. Regenerate them with `python scripts/build_social_preview.py` in the project environment, with fonttools and `rsvg-convert` available. The original font file is not redistributed.

## Revise audio and the opening example

The current collection uses ColomboGMGS2 17.02 Vanilla by Tharii314 with the explicit Original effect profile. The bank license is CC BY SA 4.0. The bank itself is not redistributed. Historical rendering receipts retain the FluidR3 baseline.

```sh
python scripts/rerender_loop_space.py \
  --space PREVIOUS_SPACE_DIR --output NEW_SPACE_DIR \
  --soundfont ColomboGMGS2_Vanilla.sf2 \
  --bank-name 'ColomboGMGS2 17.02 Vanilla' \
  --license SOUNDFONT_LICENSE.txt --workers 2
python scripts/prepare_space_revision.py \
  --space NEW_SPACE_DIR --demo-source VERIFIED_SCHISM.mid \
  --audio-base-url PINNED_AUDIO_BASE_URL
```

The revision renders the existing loop MIDIs without extracting phrases again. It verifies cycle lengths and headroom, updates waveforms and records old and new hashes in `rendering/audio_revision.json`. Audio files are hosted in a separate [audio repository](https://huggingface.co/datasets/AlmazErmilov/samuged-earworms-audio), pinned by commit in the catalog. MIDI downloads stay in the Space. Replace current FLAC paths only after the remote inventory matches the local hashes. Earlier Space commits remain recoverable.

The opening Schism example reads actual source notes, verified occurrence spans and aligned drum hits. Song, Phrase and Loop animate the same note objects into the selected cycle. Highlights use the audio clock. The diagram is a piano roll, not staff notation or an inferred time signature. Reduced motion disables zoom transitions. The main player and example share playback and volume.

The explanation starts open on desktop and phones. Its cards select the example diagram stages. On phones, users can collapse it with the summary button. Changing viewport size preserves their choice.

## Public cards and citation

The root README and `CITATION.cff` provide GitHub citation metadata. `CITATION.bib` contains the same dataset citation. The Hugging Face card source is [dataset_card.md](dataset_card.md). Publish it as the dataset `README.md` with both citation files. The card of the listening audio repository is [audio_dataset_card.md](audio_dataset_card.md). Publish it as that repository `README.md`. The two cards name the main dataset and the supplement differently so the release parts are not confused. Preserve the four data configurations when editing the card. Card updates do not require rebuilding archives or Parquet files.

The player labels its limited listening selection and links to the full phrase dataset. Additional web MIDI examples by Tool remain separate from the dataset.

### Player note views

The player can show a loop cycle or its position in the source song. Source navigation changes the visual view only. Audio stays on the selected loop. Note data is loaded when a selection opens, so the initial page does not download every song.

After building the Space, run `scripts/build_player_notes.py` with `--space` and one or more `--source-root` arguments pointing to the original MIDI collections. The command verifies the source hash stored in render metadata and writes `notes/` and `player_notes.js`. Upload those files together with the revised `index.html`. Keep generated note data outside the code repository.

The same note renderer now serves the introductory example and the atlas. Publish `player_notes.js`, `loop_explainer.js`, `atlas_notes.js` and `note_explorer.css` at the Space root, together with both page templates and `notes/`. The note builder also includes rendered atlas selections, an index of available variants per source MIDI and tempo aware beat positions. Source overview data is loaded after the smaller phrase payload.

Drum views use kit lanes and attack pulses. Overview markers and the variant selector navigate only among prepared audio loops from the same source file. Original curated defaults are preserved. Each player filters the shared index to its own available selections.
