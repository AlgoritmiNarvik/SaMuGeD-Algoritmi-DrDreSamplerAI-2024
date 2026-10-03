# SaMuGeD Earworms publication and loop rendering

Ostinato / Catchy musical hooks. Separate drum patterns are included.

The public dataset contains the audited closed corpus and a reference baseline.
The static Space contains 518 rendered cycles across three top 50 listening collections, ten familiar songs and Tool’s ostinatos. Tool has 37 riffs and 20 drum patterns from 12 songs, with 27 aligned three mode comparisons. Popular songs opens first, with Schism as a personal featured selection. The separate atlas retains five analysis views and uses the same SoundFont audio.
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

Audio rendering also needs FluidSynth and FFmpeg. The published renders used
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
Only one loop plays at a time. Stop, selection changes and page exit stop it.
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
playback after upload. The research continuation remains paused. Publication
does not restart the unfinished melody variant or require new listener ratings.

The [Tool case study](../research/tool_motifs.md) retains bass riffs and separate percussion. The interface uses square edges, dark gray panels and the Inter font. Its SIL OFL license is under `docs/assets/inter/`. Two Mermaid charts in the root README describe the method and outputs.

The piano preview for 2 Become 1 retains source notes, velocities, tempo and cycle length. It changes the loop MIDI program to 0 and records the original program 25 in metadata. Source instrument and Piano preview are separate choices, the primary dataset is unchanged.

Both listening views start at 50 percent volume and include a volume slider. The SaMuGeD Earworms wordmark uses Adamas by Colorblind. Other text uses Inter. Only the outlined logo is distributed, with source and use terms in `docs/assets/adamas/NOTICE.txt`. Popular songs has no Featured badge or introductory paragraph.

Playback uses lossless FLAC. The WAV button decodes it at 48 kHz and exports stereo PCM 24 bit in the browser. Playback volume does not change downloads. Original render hashes remain in the rendering receipts.
