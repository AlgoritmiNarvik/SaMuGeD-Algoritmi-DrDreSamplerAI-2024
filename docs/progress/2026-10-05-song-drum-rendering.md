## 2026-10-05: reduce static drum drawing work

Browser measurements did not show changing visualization height during playback or scrolling. The initial 55 second Schism run reported no layout shifts or long tasks. The 95th percentile animation frame interval was 15.7 ms with three intervals above 35 ms. This does not establish the cause of the user's intermittent scrolling delays.

Full song views now group static drum attacks by MIDI pitch and velocity. Each attack keeps its exact position, lane height, color, opacity and stroke width. The selected passage keeps individual animated hits and the detailed phrase envelopes remain unchanged. The SVG viewport declares its existing aspect ratio and isolates layout and painting.

For the default Schism page, total SVG descendants fell from 7534 to 3862. Its overview groups 1838 contextual attacks into 16 paths. Dense percussion overviews use the same path grouping. Full source coverage and repeat bands remain available.

All 36 transport and animation tests pass. Browser checks confirmed active notes and release highlights, grouped attack counts and identical visualization height when switching between melodic and percussion examples at the same browser width. No console errors were observed. The temporary profiler is local only and is excluded from publication.
