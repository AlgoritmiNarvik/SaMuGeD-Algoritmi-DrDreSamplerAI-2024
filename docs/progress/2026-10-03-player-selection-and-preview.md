## 2026-10-03: continue playback across phrase selections

Both players retain playback intent when another phrase is selected. The current cycle continues while the next buffer loads, then playback switches to the selected phrase. Stop cancels pending requests. Rapid selections cannot restart an older request. Selection while stopped stays silent. Default drum layers and 50 percent volume are retained.

Added an Adamas sharing card, favicon and metadata for direct player links and the Hugging Face Space thumbnail. The outlined artwork is reproducible from the existing wordmark and Inter assets. Audio and dataset contents are unchanged.

Removed session logs and personal status notes from the public documentation. The release page now describes published artifacts and evidence limits. The original project PDFs are English and predate this release.

Validation covers 12 JavaScript transport tests, 30 targeted Python tests and browser checks in the main player and Top 50 analytics. Checks include rapid selection, switching during loading, Stop cancellation and selection while stopped.
