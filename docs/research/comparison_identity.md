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

Version 2 reports outcome counts for each side, every left to right transition and the IDs and paths of changed sources. Phrase payload changes remain a separate comparison by melodic and percussion kind. Parser `status` remains a strict invariant, so a parse success versus error difference still stops the comparison.

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
  --output research_local/indexed_full_comparison_v02
```

The result is an output and selection differential. It is not an accuracy or perceptual quality evaluation.
