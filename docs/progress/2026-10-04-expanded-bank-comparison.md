## 2026-10-04: expand the local instrument bank comparison

Added optional Musyng Kite, Shan SGM Pro 17 and ColomboGMGS2 17.02 Vanilla inputs. The comparison uses the existing six phrase MIDIs and FluidSynth for each new bank. The player retains looping, 50 percent starting volume and one active audio player at a time.

FluidSynth comparison rendering now retries with lower synthesis gain when the intermediate reaches the headroom threshold. This avoids hiding integer output overload under final peak normalization. The published collection and its default rendering have not changed.

Downloaded banks and listening artifacts stay local. The code includes source links and reproduction options.

Validation passed for nineteen audio and comparison tests. All sixty FLAC files were checked for matching cycle lengths, 48 kHz stereo, 24 bit samples and no output clipping. Complete FluidSynth intermediate peaks stay below 0.95. Each new bank has all 128 GM programs and percussion presets. Browser checks covered the three new Schism players, looping and switching between versions.
