## 2026-10-04: instrument bank comparison and render precision

Added a reproducible six phrase comparison of FluidR3 GM and GeneralUser GS 2.0.3. Both versions use the same source loop MIDI and peak normalization. The listening page loops each version and pauses other players when a new version starts.

Changed the intermediate synthesis WAV to 24 bit and recorded this setting in renderer provenance. The existing collection remains on its published bank. Alternative timbres have not been validated through listener ratings.

Validation covers cycle repetition, source program and velocity preservation, 24 bit sample round trips and the existing audio processing tests. Twelve real renders passed duration, silence and clipping checks. Browser playback and switching between banks were checked locally.
