## 2026-10-05: song phrase navigation and drum views

Phrase navigation now keeps the selected song, collection and scroll position. Prepared alternatives appear beside the selected list entry and on the interactive song map. The listening demo adds 750 saved detector candidates from existing source songs. Every main collection entry now has multiple prepared phrases. Existing defaults remain except the two listening edits below. The corpus is unchanged.

Wannabe uses its existing 8.57 second lead phrase instead of a 42.86 second guitar cycle. Y.M.C.A. has an explicit 4 second demo cycle instead of 16 seconds with a long melodic gap. Its detector excerpt remains unchanged. The new cycle clips the final release by two MIDI ticks. Metadata records the edit and retains the original recurrence count without claiming an independently verified joint loop.

The shared note display separates melody above and named drum voices below. Both follow the same audio clock. Drums only expands the kit lanes. Symbolic decay envelopes are not isolated audio waveforms. The obsolete static Tool rhythm chart has been removed.

Validation: 656 Python tests and 32 JavaScript tests passed. Browser checks covered Schism, Iris and drum patterns, stable song and collection selection, continuous loop playback and the mobile layout at 390 pixels. Asset checks confirmed alternative coverage for every entry in all five main collections. Extra audio uses the existing ColomboGMGS2 renderer and a pinned revision in the separate audio repository.
