# Instrument rendering

The player streams precomputed FLAC loops. A larger instrument bank affects offline rendering, not the phone's synthesis workload.

[Listen to the instrument comparison](https://almazermilov-samuged-earworms.static.hf.space/comparison/index.html).

## Options

| Option | Fit for this collection | Tradeoff |
| --- | --- | --- |
| FluidSynth with FluidR3 GM | Existing General MIDI baseline | Some instruments sound dated |
| FluidSynth with GeneralUser GS 2.0.3 | Compatible alternative with 261 presets and 13 drum kits | Different timbres need listening comparison |
| sfizz with SFZ instruments | Useful for selected detailed instrument libraries | Requires instrument mapping and separate sample licenses |
| Muse Sounds | Expressive score playback | A different score and instrument workflow, not a direct replacement for our batch renderer |

Sources: [GeneralUser GS documentation](https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/README.md), [sfizz](https://sfz.tools/sfizz/), [Muse Sounds](https://sounds.musescore.org/).

## Comparison

Six phrases cover bass, piano, synth, brass, guitar and drums. Both banks receive the same exported MIDI, including source programs, velocities and tempo changes. Six repetitions are synthesized, then one middle cycle is extracted using the existing seam treatment. Both versions are peak normalized to -1 dBFS. This is not perceptual loudness matching.

The renderer now writes 24 bit intermediate WAV instead of 16 bit. This avoids quantization to 16 bit before the final 24 bit output. It does not by itself make an instrument more realistic. Existing collection assets retain their original rendering until explicitly rebuilt.

The comparison records bank and MIDI hashes, renderer provenance, elapsed time, file sizes and audio checks. In the initial local run all twelve outputs had matching cycle lengths and no output clipping. Input peaks were below full scale. Render plus FLAC conversion took 0.26 to 1.66 seconds per version. These are illustrative local timings, not a controlled performance benchmark.

GeneralUser GS permits music production, including commercial recordings. Its author notes incomplete historical provenance for some samples. The exact license is distributed with the comparison. The bank itself is not bundled in the Space.

No listener ratings or preference claim are attached to these examples. Keep FluidR3 as the collection baseline until the alternative is selected through listening. Detailed guitars may ultimately benefit more from a dedicated instrument than from replacing the entire GM bank.

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
