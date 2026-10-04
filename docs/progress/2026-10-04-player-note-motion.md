## 2026-10-04: shared note motion and drum navigation

The opening Schism example, listening collection and recurrence atlas now share one note renderer. Camera transitions preserve source coordinates, active notes have a short release and a subtle cursor trail follows the existing audio clock. Reduced motion disables decorative effects. Offscreen views skip painting and fast repeated view changes retain at most two scenes.

Percussion uses named General MIDI kit lanes rather than pitch rows. Closed and open hats, toms, ride and crash remain distinct. Attack width and base intensity encode velocity. Filled tails make each hit easier to read in phrase view. They are labelled symbolic envelopes, not measured audio waveforms or isolated instrument stems. Quarter note and half note guides use source tempo changes. Audio still loops the original source cycle, with the selected renderer and volume.

Prepared variants from the same source MIDI can be selected through overview markers, a dropdown or previous and next buttons. The original curated defaults remain unchanged. Navigation only exposes already rendered selections available in the current player. There are multiple prepared selections for 31 source songs in the main collection. The note build now covers 348 selections from 240 source MIDI files across both pages.

Phrase notes appear before the full source map. Adjacent phrase metadata is prefetched. A new audio selection aborts the obsolete fetch and skips obsolete decoding while the current loop continues until its replacement is ready. Source hashes remain verified and no audio is rerendered.

Validation covers camera retargeting, note releases across loop boundaries, drum lane mapping, transport races and cancellation. Browser checks cover the shared Schism view, percussion playback in both players, navigation among Schism variants and a 390 pixel layout. Physical iPhone playback and device frame rate are not established by desktop browser checks.
