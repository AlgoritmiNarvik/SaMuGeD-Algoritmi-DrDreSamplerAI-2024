## 2026-10-05: player control alignment

Layer and transport buttons share two column widths and a 44 px height. The volume control stays alongside transport on desktop and moves below it on narrow screens. Browser measurements confirm matching edges and no horizontal overflow at phone width.

Long drum envelopes use additional segments with a bounded count of 40. Short envelopes preserve their earlier spacing. The first segment highlight and release are retained. Segments remain in cached SVG paths, so the number of animated elements is unchanged.

Validation includes 34 player tests, desktop button geometry, mobile layout and playback. Audio and corpus files are unchanged.
