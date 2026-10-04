## 2026-10-05: separate phrase selection from drum accompaniment

The song list no longer contains phrase buttons that can be mistaken for accompaniment controls. Prepared phrases remain available in the player above the note view and on the song map. Their labels distinguish melody from drums.

The right hand player has a Drums on / Drums off toggle for the current source passage. A separate Drums only option remains where its audio is available. Selecting another phrase in the same song preserves melody only playback. Percussion phrases and passages without accompaniment show an explicit disabled state. Piano previews clear the drum toggle to match their audio.

Validation covers 32 player tests, browser playback while changing layers and phrase selection without changing the song. The audio renderer and assets are unchanged.
