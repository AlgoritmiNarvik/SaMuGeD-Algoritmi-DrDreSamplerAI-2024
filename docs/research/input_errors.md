# Lakh parse error triage

The preferred current corpus reference is the completed recovered build in [`research_local/lakh_phrases_v03`](../../research_local/lakh_phrases_v03). Its independent audit passes for all 17,232 discovered source files: 16,995 sources are verified, 237 remain recorded errors and 94,950 MIDI phrase rows are verified. The phrase counts are 50,439 melodic and 44,511 percussion. The audit reports `failure_count: 0`, `full_source_coverage_required: true` and 112,182 valid source and phrase rows in the schema report. The build uses the explicit invalid-key metadata recovery option; it does not change the strict triage conclusions below. The audit SHA256 is `e89f8275936e2813f577ba42eaf092c930a8a7170bc7777fecd04dbac4e37ecf`, with source manifest `062691ad29739cd58bdfb8c55258d63d72868d3ee3e4c30badeceaa917c8c76f` and phrase manifest `f7a1ccff7483bb70a07c0c3f04b7cd6d5090942b524272eac942d0ee3739160e`.

This bounded triage inspected the 265 failed rows in the frozen full source manifest. All source byte lengths and SHA256 hashes matched the manifest. The 16,967 successful files were not rescanned. No original file was changed.

| Failure category | Files | Interpretation |
|---|---:|---|
| Malformed channel data | 190 | A channel data byte exceeds the MIDI range. |
| Malformed event status | 9 | Running status is missing or the status byte is undefined. |
| Truncated or empty input | 21 | A declared structure ends prematurely. |
| Oversized event length | 5 | Declared message length exceeds the parser limit. |
| Missing or non-MIDI header | 7 | No SMF header is present. |
| Invalid track header | 5 | A track header is absent at the expected position. |
| Invalid key-signature metadata | 28 | Signed key or mode values in a key event are invalid. |

The original manifest records 237 `ValueError` failures and 28 `KeySignatureError` failures. Exact bounded messages and framing counts are preserved in `research_local/input_error_triage_v01.json`.

## Framing evidence

There are 258 standard headers and seven nonstandard headers. Standard headers declare format 0 in 58 files and format 1 in 200 files. None declares format 2; one uses an SMPTE time division. Exclusive framing outcomes are 180 complete declared structures, 48 unexpected track chunks, 23 track payloads extending past EOF, six trailing-byte cases and seven nonstandard headers. These framing categories overlap differently with the parser failure categories above.

## Metadata recovery probe

An exploratory in-memory probe changed invalid key-signature payloads to a valid placeholder. All 28 copies then parsed with mido. It changed 124 metadata events (247 payload bytes), with no note, channel or timing byte changes. This probe establishes that the malformed metadata can be isolated. It does not establish that C major is the correct key and its placeholder policy is unsuitable for the dataset.

A separate optional recovery implementation is now available through `--recover-invalid-keys`. It validates the complete SMF structure and retypes only invalid key events as sequencer-specific metadata in memory. It preserves the full original payload. This changes 124 event-type bytes across the 28 affected files, leaves note, channel and timing bytes unchanged and avoids inventing a key. Every repair records its track, event, tick and byte offsets together with hashes of the original and recovered SMF payload. RIFF MIDI wrapper offsets are explicitly distinguished from unwrapped SMF offsets.

The strict loader remains the default. Recovery is attempted only after the normal parser raises a key-signature error. Unit and mixed melodic/percussion integration fixtures validate the receipts. The complete updated corpus run used the explicit recovery option and subsequently passed independent reconstruction and export checks before packaging. Its final counts belong to that run's own manifest and must not be substituted into the earlier strict run.

The other 237 files require altered or inferred event data or container structure. They remain errors. Clipping note data or guessing missing status and track boundaries is outside this recovery policy.

## Completed recovered reference run

`research_local/lakh_phrases_v03` has finished with 16,995 verified files and 237 recorded errors. The 28 recovered sources contribute 84 melodic and 55 percussion candidates. All originals retain their recorded hashes. These counts belong to that recovered run; the strict-run diagnostic above remains unchanged. The 112,182 source and phrase rows pass the schema validation report and the independent full artifact audit is recorded in `audit.json` with `passed: true`. The original bounded triage remains [`input_error_triage_v01.json`](../../research_local/input_error_triage_v01.json), whose SHA256 is `4bef03682dba0cb1de425a604616d3c0123703908e3f655c4e65dd7eed6977b9` and whose source manifest is the earlier strict v02 manifest.
