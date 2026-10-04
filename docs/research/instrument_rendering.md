# Instrument rendering

The player streams precomputed FLAC loops. A larger instrument bank affects offline rendering, not the phone's synthesis workload.

The comparison is generated locally with the command below. It is separate from the published listening collection.

## Options

| Option | Fit for this collection | Tradeoff |
| --- | --- | --- |
| FluidSynth with FluidR3 GM | Existing General MIDI baseline | Some instruments sound dated |
| FluidSynth with GeneralUser GS 2.0.3 | Compatible alternative with 261 presets and 13 drum kits | Different timbres need listening comparison |
| FluidSynth with Arachno SoundFont 1.0 | Complete bank, preferred in earlier auditions | Preference depends on the instrument |
| FluidSynth with MuseScore General 0.2.0 | Complete GM bank with documented sample sources | Shares some source samples with FluidR3 |
| BASSMIDI with Arachno | Same bank through another whole MIDI engine | Proprietary runtime, separate license and effects defaults |
| Timbres of Heaven 4.00(G) with FluidSynth or BASSMIDI | Complete GS bank with two whole MIDI render setups | Louder samples need lower synthesis gain, redistribution needs permission |
| Musyng Kite with FluidSynth | Complete GM/GS bank with another guitar, bass and drum palette | About 1 GB of samples, individual balances need listening |
| Shan SGM Pro 17 with FluidSynth | Updated full bank with adjusted instrument balance | Some sounds retain a vintage character |
| ColomboGMGS2 17.02 Vanilla with FluidSynth | Full bank with GM2/GS and XG drum mappings | Shares some sample sources with other banks |
| Muse Sounds | Expressive score playback | A different score and instrument workflow, not a direct replacement for our batch renderer |

Sources: [GeneralUser GS documentation](https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/README.md), [sfizz](https://sfz.tools/sfizz/), [Muse Sounds](https://sounds.musescore.org/).

## Comparison

Six phrases cover bass, piano, synth, brass, guitar and drums. Every option receives the same exported MIDI, including source programs, velocities and tempo changes. Six repetitions are synthesized, then one middle cycle is extracted using the existing seam treatment. All versions are peak normalized to -1 dBFS. This is not perceptual loudness matching.

The renderer now writes 24 bit intermediate WAV instead of 16 bit. This avoids quantization to 16 bit before the final 24 bit output. It does not by itself make an instrument more realistic. The current collection was rebuilt with the selected Colombo bank. Original receipts retain the previous rendering hashes.

The comparison records bank and MIDI hashes, renderer provenance, elapsed time, file sizes and audio checks. In the initial local run all twelve outputs had matching cycle lengths and no output clipping. Input peaks were below full scale. Render plus FLAC conversion took 0.26 to 1.66 seconds per version. These are illustrative local timings, not a controlled performance benchmark.

GeneralUser GS permits music production, including commercial recordings. Its author notes incomplete historical provenance for some samples. The exact license is distributed with the comparison. The bank itself is not bundled in the Space.

No listener ratings or general preference claim are attached to these examples. The project owner selected ColomboGMGS2 17.02 Vanilla after local auditions. The collection uses one complete bank with the Original effect profile. This preserves the preferred audition settings and avoids instrument specific routing.

## Reproduce

Download the banks from their official sources, then run in the project virtual environment:

```sh
python scripts/compare_soundfonts.py \
  --space path/to/built-space \
  --baseline path/to/FluidR3_GM.sf2 \
  --candidate path/to/GeneralUser-GS.sf2 \
  --output path/to/comparison
```

Copy the GeneralUser license to `comparison/generaluser-license.txt` before publication. Review `receipt.json` and the audio before changing the collection default. Audio assets and downloaded banks stay outside the code repository.

Pass `--arachno` and `--musescore` with their bank paths to add both full banks. Add `--bass-runtime` with the extracted macOS runtime folder containing `core/libbass.dylib` and `midi/libbassmidi.dylib` for the BASSMIDI version of Arachno. Obtain these libraries from [Un4seen](https://www.un4seen.com/bass.html). They are not distributed here. BASS is free for noncommercial use under the vendor terms; commercial use requires a separate license review. The comparison uses no audio device and decodes float samples before normalization. Engine effects use each engine's defaults, so this is a comparison of complete rendering setups, not a controlled interpolation experiment.

Pass `--timbres` with the Timbres of Heaven bank path to add FluidSynth rendering. If `--bass-runtime` is also present, it adds BASSMIDI rendering of the same bank. Download it from [Don Allen's page at MidKar](https://midkar.com/SoundFonts/index.html). This local audition does not distribute the bank. The source requires permission to redistribute it. Rendered audio publication terms still need review before changing the public collection.

With Timbres enabled, the comparison contains forty two renders, seven setups for each of six phrases. FluidSynth uses synthesis gain 0.08 for Timbres instead of 0.45 because its samples exceeded the integer WAV range at the previous gain. Final peak normalization is the same for every setup. The receipt records this gain separately from normalization.

All forty two decoded FLAC files were verified as 48 kHz stereo with 24 bit samples, matching frame counts and no output clipping. Timbres input peaks in FluidSynth were 0.19 to 0.31 after reducing synthesis gain. In the earlier five setup run, MuseScore General took 0.19 to 0.34 seconds per version and BASSMIDI with Arachno took 0.06 to 0.93 seconds, including FLAC conversion. These local timings do not establish a performance ranking. The BASSMIDI intermediate buffer is floating point, which retains values above full scale until normalization.

HALion was not auditioned because its engine and GM library were not installed on the comparison host. Individual bass, guitar and drum library experiments were removed from the listening page. The comparison now uses complete instrument banks.

## Further bank auditions

Pass `--musyng`, `--sgm-pro` and `--colombo` with the matching SF2 paths to include Musyng Kite, Shan SGM Pro 17 and ColomboGMGS2 17.02 Vanilla. With all options enabled the page contains ten setups for the same six phrases. These three banks use FluidSynth and do not introduce instrument specific modules.

The comparison retries FluidSynth at half the synthesis gain if the complete intermediate render's peak reaches 0.95. This preserves headroom in the integer intermediate before the existing peak normalization. It records the final synthesis gain and peak and fails after eight attempts if headroom cannot be obtained. This check does not establish sample quality or detect distortion already present in a bank's samples.

Sources: [Musyng Kite author thread](https://www.kvraudio.com/forum/viewtopic.php?t=351893), [Shan SGM Pro 17 release](https://www.reddit.com/r/soundfonts/comments/1wezdu3/shan_sgm_pro_17_es8c_soundfont_released/) and [ColomboGMGS2 author page](https://sourceforge.net/projects/colombogmgs2-sf2/). Musyng Kite's SF2 was obtained from the [archived bank collection](https://archive.org/details/500-soundfonts-full-gm-sets). Downloaded banks and audition files stay outside the code repository. The selected Colombo renders are published separately as listening assets.

## Arachno and Colombo effect auditions

The final listening comparison contains only Arachno SoundFont 1.0 and ColomboGMGS2 17.02 Vanilla. The project owner reopened the bank choice after preferring Arachno's piano on Iris. This is a listening preference, not a general quality ranking. One whole bank remains the intended collection default.

Each bank receives the same exported MIDI and three explicit effect profiles beside its original audition:

| Profile | Reverb | Chorus | Purpose |
| --- | --- | --- | --- |
| Original | Room size 0.5, damping 0.3, width 0.8, level 0.7 | Three voices, level 0.6, speed 0.2, depth 4.25 | Preferred audition settings, now explicit |
| Dry | Off | Off | Hear the samples without global effects |
| Close room | Room size 0.4, damping 0.65, level 0.32 | Off | Smaller space with softer reflections |
| Warm room | Room size 0.6, damping 0.7, level 0.55 | Off | More space with darker reflections |

These numbers are FluidSynth settings, not percentages of the final audio mix. SoundFont modulators and MIDI effect sends also affect the result. See the [FluidSynth settings](https://www.fluidsynth.org/api/settings_synth.html). Reverb can suggest a shared acoustic space. It cannot supply missing articulations or replace the character of a piano sample. Notes, timing, velocities and programs are preserved. No random humanization is applied.

```sh
python scripts/compare_effects.py \
  --space path/to/built-space \
  --comparison path/to/comparison \
  --soundfont path/to/ColomboGMGS2_Vanilla.sf2 \
  --arachno path/to/Arachno.sf2
```

Run this after the bank comparison with `--colombo` and `--arachno`. It replaces the local comparison page with a paired view. Phrase and effect selectors keep two players visible at a time. Iris opens first for piano comparison. Schism, Blue Monday, Mambo No. 5, Thunderstruck and Low Rider retain the other instrument examples. Playback loops at 50% volume. Starting either player stops the other. Changing phrase or effects stops playback so hidden players cannot continue.

The script verifies MIDI, bank and original audio hashes before rendering. Room effects are synthesized over repeated cycles before extraction, so reverb continues across the loop boundary. The receipt records settings, synthesis headroom, output hashes and render time. There are 48 versions across six phrases, two banks and four profiles. The twelve original versions are retained from the earlier audition.

Some drum patches barely respond to global effects because their effect sends are low. This is a reason to audition melody and drums together rather than assume every patch receives the same reverb amount. All versions share a peak target of -1 dBFS. This is not perceptual loudness matching.

ColomboGMGS2 is by Tharii314. The downloaded bank includes a CC BY SA 4.0 license. Its sample credits are in the supplied preset list. Arachno is by Maxime Abbey. Downloaded banks and audition audio stay outside the code repository. The collection revision contains 630 Colombo renders. All decoded files were checked for 48 kHz stereo, 24 bit samples, unchanged cycle frame counts and no clipping. Source and loop MIDI hashes remain unchanged. Audio is stored in the [audio repository](https://huggingface.co/datasets/AlmazErmilov/samuged-earworms-audio) and pinned by commit in the Space catalog. This keeps the same Space link without duplicating the new audio in its Git history. The main dataset is unchanged.
