## 2026-10-05: show detected repeats in song views

The shared note explorer now shows muted bands for saved occurrences of the selected phrase. The current loop retains a brighter outline. The lower song map also shows the occurrence ranges. This applies to the main player, Schism example and analytics player, including percussion.

The note builder accepts repeated `--phrase-manifest` arguments and reads selection receipts from the Space rendering folder. It converts saved occurrence ticks through the source tempo map, verifies the source hash and checks the part binding. Merged percussion records must match the source drum parts. It does not infer new matches or change audio.

The release includes repeat windows for all 50 motif examples, all 50 drum examples, all 105 Tool examples and 53 of 55 popular examples. Some manually curated excerpts have no matching saved detector record and show only the selected passage. Paired drum accompaniment is not claimed to repeat jointly with the melodic phrase.

Validation covers source and part mismatches, merged percussion, tempo changes, duplicate windows and invalid ticks. All 34 transport tests pass. Browser checks cover the shared Schism view and the dense percussion overview.
