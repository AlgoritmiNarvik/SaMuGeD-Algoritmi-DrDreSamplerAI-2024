## 2026-10-04: interactive notes in the loop player

Added a note view for each listening selection. Phrase shows the rendered cycle. Song shows the source MIDI with the selected passage marked. Zoom, position, Find phrase and Fit view let listeners inspect either scale. All instruments is an optional source overview. Moving around the source view does not play the full song, audio remains the selected loop.

The visualization follows the existing audio clock. Active notes receive a restrained highlight and new views appear softly. Reduced motion disables decorative transitions. Playback, volume, layer selection and continuous track replacement retain their existing transport.

Built views for 262 unique phrases from 181 source MIDI files. Source hashes are checked before generation. Source notes load on selection and are cached, audio files and dataset records are unchanged. The existing explicit key metadata recovery handles damaged source metadata without changing notes.

Validation includes transport and viewport tests, source hash checks and browser playback, track replacement, phrase focus and a 390 pixel mobile layout. Browser emulation does not verify physical iPhone audio routing.
