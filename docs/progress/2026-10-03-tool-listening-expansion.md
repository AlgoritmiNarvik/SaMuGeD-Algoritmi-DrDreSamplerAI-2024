## 2026-10-03: expand the Tool listening collection

The Tool collection adds 16 songs from separately screened web MIDI arrangements. Each new song has two melodic phrases and one percussion pattern. Every new melodic phrase has aligned With drums, Melody only and Drums only modes. The player now contains 28 Tool songs, 69 riffs, 36 percussion patterns and 59 paired comparisons. The primary dataset and other collections are unchanged.

Source download hashes, URLs and exact selected phrase IDs are stored in docs/research/tool_expansion_selection.json. The curation script accepts a configuration file and checks source and detector export hashes. The Space builder includes the additional selection and render receipts. Full source songs are not published.

The screen rejected malformed tempo metadata and incomplete drum arrangements. Disposition and Wings for Marie were not included because the checked sources did not provide enough qualifying melodic cycles with drums. Selection is based on source structure, without listener ratings.

The selected Adamas wordmark replaces Merkur in both listening views. Inter remains the interface font. Only the outlined logo is shipped, not the restricted font file.

Validation passed 642 local tests before the logo change and 30 focused tests after it. All 112 new FLAC files decode to the exact original stereo PCM24 samples at 48 kHz. Each paired mode has the same frame count, nonzero signal and no full scale clipping. All 518 existing audio files and the other collections remain unchanged. Browser checks cover the new song filter, default drums, 50 percent volume and all three playback modes.
