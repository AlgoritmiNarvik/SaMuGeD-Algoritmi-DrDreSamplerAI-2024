## 2026-10-05: separate phrase selection from drum accompaniment

The song list no longer contains phrase buttons that can be mistaken for accompaniment controls. Prepared phrases remain available in the player above the note view and on the song map. Their labels distinguish melody from drums.

The right hand player has a Drums on / Drums off toggle for the current source passage. A separate Drums only option remains where its audio is available. Selecting another phrase in the same song preserves melody only playback. Percussion phrases and passages without accompaniment show an explicit disabled state. Piano previews clear the drum toggle to match their audio.

Validation covers 32 player tests, browser playback while changing layers and phrase selection without changing the song. The audio renderer and assets are unchanged.

Phrase selectors and song map markers stay within the selected phrase kind. Melodic entries exclude drum patterns and percussion entries exclude melodies. Imagine's three melodic passages contain 29, 31 and 39 notes at different source positions, so they remain distinct. Labels include note count and explicit start position.

Selecting a phrase resets the main and analytics cameras to that cycle. The introduction retains its song overview. Highlights now release smoothly after note ends. Drum envelopes and highlights share an instrument specific decay duration, with longer tails for cymbals than closed hats. This remains a symbolic cue rather than measured isolated instrument energy. All 33 player tests pass.
