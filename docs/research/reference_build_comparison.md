# Reference build comparison

## Scope

This report compares the complete local reference builds `research_local/lakh_phrases_v02` and `research_local/lakh_phrases_v03`. Both contain the same 17,232 source IDs and record filenames. Version 3 adds the fixed-representative exact cache and optional recovery of invalid key-signature metadata.

This is an artifact differential. It does not replace either build's independent audit and it does not assess musical quality or memorability. The preferred v02 replication includes the completed version 3 audit in its frozen input inventory. The earlier comparison preceded that audit and remains unchanged.

## Frozen comparison

The runner hashes both source and phrase manifests, summaries, build configurations and every per-source record before comparison. It then checks every record against its corresponding source manifest row, reads one record pair at a time and hashes all inputs again before writing results. The start receipt binds the code snapshot, manifest hashes and a 34,464-record inventory. The completion receipt binds the inventory, raw differences, aggregate results and run log.

Phrase equality excludes only these fields:

- `phrase_id`, because it is generated from the build run key.
- `midi_path`, because its filename is generated from the build-specific phrase ID.
- `split` and `split_group`, because these are compared separately from musical content.

Every other phrase field participates in equality. This includes the family ID, rank, source part and track, start and end ticks, prototype note index, pitches, onsets, durations, velocities, score, score components, occurrence support, every occurrence coordinate and similarity and the exported MIDI SHA256. A changed exported MIDI SHA therefore counts as a semantic output change even though its build-derived path does not.

## Source outcomes

| Transition from version 2 to version 3 | Sources |
| --- | ---: |
| Parse error to parse error | 237 |
| Parse error to matched | 28 |
| Matched to matched | 16,864 |
| No match to no match | 103 |

The 28 recovered files contain 124 repair receipts. They add 84 melodic and 55 percussion phrase rows. No source identity field changed. Source SHA256, byte count, path, source ID and song key matched for all 17,232 inputs.

Only the 28 recovered files changed source-level musical metadata or drum statistics. The original MIDI files were not modified. Recovery retyped invalid `FF 59` metadata in memory and retained exact repair receipts.

## Phrase output changes

| Kind | Changed sources | Due to recovery | Due to cache with baseline search limit | Cache changes without baseline search limit |
| --- | ---: | ---: | ---: | ---: |
| Melodic | 119 | 28 | 91 | 0 |
| Percussion | 20 | 20 | 0 | 0 |

All 91 cache-related melodic changes occurred in files where version 2 already reported `search_limited=true`. Every cache-affected file retained three melodic selections before and after, so the cache caused replacements, reordered selections or changed support and score details rather than changing the total selected count. The raw report preserves the before and after family IDs, semantic payload hashes, exported MIDI hashes and bounded field-level difference paths for every changed source.

Version 2 had 791 search-limited successful sources and version 3 had 700. Of the 91 cache-affected outputs, 20 were no longer search limited in version 3 and 71 remained limited under another part or bound. Another 71 sources moved from limited to unlimited without changing selected phrases. The remaining 629 limited sources also kept the same selected phrases.

The provenance diff explains this boundary. Version 3 registers a fixed exact representative and appends exact transposed copies without spending a pair comparison. This changes how far a bounded search advances before reaching `max_comparisons` and can change selected candidates when version 2 stopped at that bound. No baseline-unlimited source changed its melodic semantic payload. This is evidence that the cache preserved complete-search outputs in this corpus while changing the expected result of some already truncated searches. It is not proof for inputs outside this build.

Normalized part search statistics changed in 459 non-recovered files, all of which were baseline search limited. The changed fields were group, repeat, truncation, saturation, overlap-removal and limit counters. The 28 recovered files account for the other part-stat changes. Pair comparison counts and the new exact-cache-hit counter were treated as implementation telemetry and reported separately from semantic equality.

## Counts, splits and families

| Measure | Version 2 | Version 3 | Difference |
| --- | ---: | ---: | ---: |
| Melodic phrase rows | 50,355 | 50,439 | +84 |
| Percussion phrase rows | 44,456 | 44,511 | +55 |
| Train phrase rows | 77,327 | 77,445 | +118 |
| Validation phrase rows | 8,776 | 8,786 | +10 |
| Test phrase rows | 8,230 | 8,239 | +9 |
| Overlap-excluded phrase rows | 478 | 480 | +2 |

No source changed its split or split group. Phrase split row counts reflect the newly recovered rows plus family-overlap screening recomputed across the changed cache selections and recovered rows.

| Family measure | Melodic | Percussion |
| --- | ---: | ---: |
| Version 2 families | 39,142 | 34,515 |
| Version 3 families | 39,205 | 34,546 |
| Common families | 39,052 | 34,515 |
| Version 2 only | 90 | 0 |
| Version 3 only | 153 | 31 |
| Common families with membership changes | 30 | 21 |
| Families with excluded members, version 2 | 150 | 203 |
| Families with excluded members, version 3 | 150 | 205 |
| Families spanning multiple active splits | 0 | 0 |

All 90 version 2-only melodic families occur in cache-affected sources. Of the 153 version 3-only melodic families, 93 occur in cache-affected sources and 60 in recovered sources. All 31 new percussion families come from recovered sources. The cache changes which bounded melodic candidates survive but adds no phrase rows overall. Recovery accounts for the full increase of 84 melodic and 55 percussion rows.

The absence of families across multiple active splits is the relevant leakage check. A family can have one or more rows marked `overlap_excluded`; those rows are not active training, validation or test examples.

## Interpretation

For the 16,176 successful version 2 sources that were not search limited, the fixed-representative cache produced identical semantic phrase output. It also left all non-recovered percussion output unchanged. The cache is therefore semantics preserving on the complete-search portion of this corpus.

For 91 baseline-limited sources, the cache changed the bounded search path and the selected melodic payload. These differences are material and should not be described as byte-only or telemetry-only. They include family selection, source coordinates, scores, support and exported MIDI SHA values. They are attributable to the interaction between the exact cache and the existing comparison bound because no baseline-unlimited source changed and the frozen provenance diff shows no other melodic algorithm change.

Recovery behaves as intended at the artifact level. It changes exactly 28 former parse errors into matched sources and introduces their melodic and percussion results. This comparison confirms build-to-build accounting and payload differences. The separate version 3 full audit passes source reconstruction and exported MIDI validity; this differential does not replace it.

## Reproduction and receipts

The preferred replication used:

```bash
source .venv/bin/activate
nice -n 10 python scripts/compare_builds.py \
  --left research_local/lakh_phrases_v02 \
  --right research_local/lakh_phrases_v03 \
  --output research_local/my_reference_comparison
```

The output directory must be absent or empty. The preferred replication is `research_local/reference_build_comparison_v02`. Its automatic local import closure contains 15 saved files. All scientific aggregate fields exactly match v01 after excluding receipt links and the changed input inventory, which now also binds the completed reference v03 audit. The older v01 five-file snapshot remains available with its original incomplete-import limitation.

- Start receipt SHA256: `85a53870df4b8c0518d2f27477b0171edde3a92716d78a5ce7f1c7af8d2a26a3`
- Configuration SHA256: `08aafd51f7f0115b33313cd0444c2add35ee4053e4c25f71ee21bd374cdf61d2`
- Source snapshot SHA256: `29910b458dee1183e8ef002882b9683240b8b0c857ac0c60b50211695c3f1619`
- Input inventory SHA256: `4dd1401b72505a4890b8a3c6f318829778382398a9ca1019abf89affcf8eb99c`
- Raw results SHA256: `8aaf63ce9e5d395153794a5f279b8006f1ba70f1fd8a8a10ecaec00763e9be2b`
- Aggregate SHA256: `37a5d37a90b572643c00bac6d45229ad5041f3b2ce95e756ddc55a6fd4e6fd1a`

Completion receipt SHA256: `f2ac4394db54d24578ef69862acfcabed86cd6b1470a0079635bbe01593b74f3`. The replication was run after the original results were known and is an implementation/provenance check, not a new independent accuracy test.
