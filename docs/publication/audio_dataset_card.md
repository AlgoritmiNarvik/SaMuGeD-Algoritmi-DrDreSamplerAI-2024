---
license: other
license_name: mixed-midi-sources
license_link: https://huggingface.co/datasets/AlmazErmilov/samuged-earworms-audio/blob/main/README.md
language:
- en
tags:
- music
- midi
- audio
pretty_name: SaMuGeD Earworms listening audio (supplement)
---

# SaMuGeD Earworms listening audio (supplement)

This is not the dataset. It is a supplement that only stores the rendered FLAC loops streamed by the Space player. Phrases, splits, MIDI bytes, archives and the research note are in the main dataset, [samuged-recurring-phrases](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases).

630 rendered loops for [SaMuGeD Earworms](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms). Phrase annotations and dataset splits are in [the recurring phrases dataset](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases).

Authors: Peiyi Wu, Asle Fjæran Øren, Shayan Dadman and Almaz Ermilov.

Audio uses FluidSynth with ColomboGMGS2 17.02 Vanilla by Tharii314. It uses the Original reverb and chorus profile selected through listening. The bank is available from [its author page](https://sourceforge.net/projects/colombogmgs2-sf2/). Its included CC BY SA 4.0 license is in soundfont-license.txt. The source bank credits Maxime Abbey, David Shan, Cose Vidal, OpenWrld, Milton Paredes and Rick Simon. The bank file is not distributed here.

Files are lossless 48 kHz stereo FLAC with 24 bit samples. Each file contains one complete source derived cycle. The player repeats it continuously. Source note timing, pitches, velocities and programs are preserved. This is synthesized MIDI audio rather than commercial song recordings.

The Space includes Lakh MIDI phrases and separate Tool listening supplements. The Tool supplements remain outside the recurring phrases dataset. Underlying composition and arrangement attribution remains incomplete. This repository does not grant new rights to reuse those compositions or arrangements. Consult the Space source metadata and dataset card before redistribution.

rendering/audio_revision.json records bank and source hashes, effects settings and audio checks. Source MIDI and per phrase metadata are available in the Space. Earlier rendering receipts there document the previous sound bank.
