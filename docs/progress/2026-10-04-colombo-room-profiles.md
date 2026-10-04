## 2026-10-04: Colombo room auditions

The project owner selected ColomboGMGS2 17.02 Vanilla after comparing complete instrument banks. Added dry, close room and warm room profiles using the existing FluidSynth renderer. Room profiles disable chorus and use softer reverb reflections. Source MIDI notes, timing, velocities and programs remain unchanged.

The local comparison now includes eighteen additional FLAC renders across six phrases. Each render has matching cycle length, 48 kHz stereo and 24 bit samples. Complete synthesis peaks stay below 0.95 and final peaks below 0.9. The comparison verifies reference MIDI, bank and audio hashes before building the auditions. Playback and switching were checked in the browser.

Code tests cover effect settings, headroom retries and repeatable page updates. The final effect profile is awaiting listening selection. Public audio has not been rebuilt or deployed in this change. Downloaded banks, comparison audio and private receipts remain outside the code repository.
