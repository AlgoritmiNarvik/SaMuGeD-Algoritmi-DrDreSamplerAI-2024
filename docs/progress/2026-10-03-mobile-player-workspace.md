## 2026-10-03: keep the mobile player and song list together

The phone layout now uses one viewport for a compact player and a taller song list. Playback, volume and the phrase display stay above the list. Metrics, source notes and downloads are available under a details disclosure. Selecting a phrase preserves the page and list position. The previous automatic page jump and Back to player button were removed.

The main player and Top 50 analytics use the same layout. Volume remains at 50 percent by default and follows the selected phrase in the analytics player. Desktop detail content remains visible.

Validation passed 12 audio transport tests and 20 loop Space and analytics tests. Browser checks at 390 by 844 and 375 by 667 covered list scrolling, successive song selections, Tool playback and volume retention. No horizontal page overflow was observed at the smaller size. These checks used browser viewport emulation, not a physical phone.
