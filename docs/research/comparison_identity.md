# Algorithm comparison identity boundary

`scripts/compare_variants.py` compares two complete audited builds over the same source corpus. Source identity and detector output are separate checks.

## Strict source invariants

The comparison requires the same source ID set, record filename set and split assignment. The following source fields must match for every source:

* source path, byte hash and byte count
* artist and title path keys
* parser status, error type and error text
* recovered MIDI fingerprint and ticks per beat
* parsed part and note counts
* warnings and metadata repair receipts

The per source record must still match its own audited manifest exactly. This prevents an outcome or phrase payload from being changed after that build was audited. Principal files and records are hashed before reading and checked again before the comparison is completed.

## Algorithm dependent outcome

`outcome` is not a source identity field. For a successfully parsed source it records whether that detector selected at least one phrase, commonly `matched` or `no_match`. Different algorithms can therefore produce different outcomes for the same MIDI without violating corpus identity.

Version 3 reports outcome counts for each side, every left to right transition and the IDs and paths of changed sources. Phrase payload changes remain a separate comparison by melodic and percussion kind. Parser `status` remains a strict invariant, so a parse success versus error difference still stops the comparison.

## Common content projections

The full `semantic_phrase` comparison remains available and still retains scores, matcher flags, family IDs and other selection evidence. Its changed source count therefore means that the full selected payload changed. The aggregate and raw outputs now also contain `common_content_comparison`, which separates note and interval content from selection metadata.

The prototype projection contains exactly these fields, in this order:

```text
kind, part_index, source_track, channel, program, start_tick, end_tick,
ticks_per_beat, pitches, onsets_beats, durations_beats, velocities
```

The projection reads each source record's phrase payload. Current payloads store PPQ at source level, so the projected `ticks_per_beat` value is null. The strict source identity gate above checks equal PPQ separately. Direct reconstruction from phrase manifests, which contain actual PPQ, gives the same changed source sets; raw projection hashes use the record representation. Consumers must use source PPQ or the exported phrase manifest when interpreting tick units.

The recurrence projection contains the same prototype fields plus `occurrences`. Each occurrence contains only `start_tick`, `end_tick` and `transpose_semitones`, sorted lexicographically by those three fields. Similarity, edit counts, inserted and deleted indices, substitutions, matched note pairs, timing residuals and source verification flags are excluded from this projection. This makes it an interval identity view rather than an alignment trace.

For each `melodic` and `percussion` kind the comparison reports exact changed source IDs and counts for:

* `ordered_prototypes`, which preserves selected phrase order
* `prototype_multiset`, which compares hashed prototypes with duplicate counts preserved
* `top1_prototype`, which compares the first selected prototype or null
* `ordered_recurrence_intervals`, which preserves phrase order and the sorted occurrence intervals

Score-only or matcher-only changes leave all four common content projections unchanged even though the full semantic payload can differ. Rank reordering changes the ordered and top-one views while leaving the prototype multiset unchanged. A pitch, tick or prototype metadata change is visible in the prototype views. An occurrence coordinate change is visible in the recurrence view while leaving the prototype views unchanged. The comparison version is `algorithm-variant-comparison-v3` and the projection version is `common-content-projection-v1`.

The existing source manifests for `research_local/lakh_phrases_v03` and `research_local/lakh_aligned_indexed_v01` contain 17,232 source rows. A read only streaming check with the corrected identity projection found zero identity differences and zero split differences. Outcome transitions were:

| Left | Right | Sources |
| --- | --- | ---: |
| error, parse error | error, parse error | 237 |
| ok, matched | ok, matched | 16,889 |
| ok, matched | ok, no match | 3 |
| ok, no match | ok, matched | 34 |
| ok, no match | ok, no match | 69 |

The 37 changed outcomes are detector output differences. They are not input corpus drift and do not indicate which detector is more accurate. The failed `research_local/indexed_full_comparison_v01` start receipt remains frozen; it stopped before producing a completed comparison because version 1 incorrectly included `outcome` in source identity.

## Reproduction

Run the focused tests before starting a replacement comparison:

```bash
source .venv/bin/activate
pytest -q tests/test_compare_variants.py
```

Then use a new output directory:

```bash
source .venv/bin/activate
python scripts/compare_variants.py \
  --left research_local/lakh_phrases_v03 \
  --right research_local/lakh_aligned_indexed_v01 \
  --output research_local/my_variant_comparison
```

The result is an output and selection differential. It is not an accuracy or perceptual quality evaluation.
