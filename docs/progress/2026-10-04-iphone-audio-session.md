## 2026-10-04: use a music playback session on iPhone

Both loop players now request the playback audio session before creating or resuming Web Audio. iPhone browsers can otherwise treat Web Audio as ambient sound and silence it when the ringer switch is muted. Browsers without the API retain their existing playback path. An unavailable session setting does not block playback.

Regression checks cover session selection before context creation and API failures. The main audio source responds with a FLAC signature and cross origin access enabled. A real iPhone listening confirmation is still needed, desktop viewport emulation does not test its audio routing.
