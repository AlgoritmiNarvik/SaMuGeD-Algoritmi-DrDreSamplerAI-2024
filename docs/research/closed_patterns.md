# Closed exact-pattern selection experiment

## Purpose

The aligned detector can verify a complete adjacent exact repeat and still omit it from the final output. A shorter contained family may rank first because it has stronger internal-gap boundary evidence. The original redundancy rule then treats the shorter and longer intervals as equivalent because it divides overlap by the shorter duration.

`samuged.closed_patterns` is an optional selector over existing aligned or aligned indexed candidate lists. It does not change candidate generation, alignment, limits or detector defaults.

## Frozen rule

The optional selector preserves the original sort order, redundancy rule and boundary-extension behavior. It adds a replacement only when all of these conditions hold:

- The candidate is longer than the selected family and belongs to the same part.
- Both families have the same support of at least three occurrences.
- Every occurrence is source verified with zero edits, no inserted, deleted or substituted notes, full diagonal note matching, zero timing error and zero duration error.
- Each shorter occurrence maps one to one to a containing longer occurrence with a shared start or end tick.
- The longer recurrence score is no more than 0.02 below the shorter score.

The score margin applies at each replacement step. A chain of several replacements can accumulate a larger total score change. The recorded trace preserves every step for independent geometry checks and full selection replay.

The candidate source SHA-256 used for both experiments and the frozen full runner is `fb47d10c52f13eb322dddc8ff9b9a2eefa7f020164a85db4c4e807d4e14b3a1b`.

## Fresh synthetic design

The evaluation used 500 new cases with seeds 30,000,000 through 30,000,499. This namespace is disjoint from the earlier 10,000,000 development and 20,000,000 test namespaces. The 13 existing conditions, detector configs, temporal intersection over union threshold of 0.8 and top 10 scoring were unchanged. Thresholds and source hashes were frozen in the start receipt before detector execution.

Both the aligned and aligned indexed generators were evaluated. Each generator ran once per case. The original and optional selectors reused the same candidate list, which isolates selection behavior from candidate-generation runtime or ordering.

## Fresh synthetic results

Both candidate generators produced the same semantic result. The intervals in this table use the `aligned` bootstrap stream. The `aligned_indexed` stream independently resamples the same cases and has the same point estimates; its occurrence F1 interval is +0.036719 to +0.091781. The paper uses that indexed interval. This small interval difference comes from finite bootstrap resampling, not different predictions.

| Metric | Original | Closed exact extension | Paired difference, closed minus original | 95% case bootstrap interval |
| --- | ---: | ---: | ---: | ---: |
| Recovered positive cases | 404/423 | 420/423 | +16 | +9 to +24 |
| Candidate F1 | 0.841667 | 0.888889 | +0.047222 | +0.028878 to +0.067621 |
| Occurrence F1 | 0.831091 | 0.894309 | +0.063218 | +0.039278 to +0.091634 |
| Top 1 recovery | 0.936170 | 0.952719 | +0.016548 | +0.006865 to +0.030164 |
| Negative output cases | 0/77 | 0/77 | 0 | 0 to 0 |

All 16 added recoveries were in `legacy_contiguous_exact`, which changed from 23/39 to 39/39. No condition lost a recovered case. Selection changed in 36 of 500 cases, so 20 output changes did not alter the case-level recovery decision.

These results support the intended symbolic boundary correction on newly seeded cases. They do not establish a general improvement in musical phrase boundaries.

## Fixed real pilot

The unchanged 128-file pilot has no phrase annotations. Both candidate generators changed the same 19 files with 29 replacement steps. Replacement support ranged from 3 to 18 occurrences, with median 7. Note-count extensions ranged from 1 to 15 notes, with median 2. Occurrence spans grew by factors from 1.030 to 2.286, with median 1.157. Four replacement steps reached the 32-note detector ceiling.

| Source | Replacement steps, old notes to new notes with support |
| --- | --- |
| `883/Senza_averti_qui.2.mid` | 26 to 31 (7), 31 to 32 (7) |
| `Andre_Hazes/Het_is_koud_zonder_jou.mid` | 23 to 28 (3), 16 to 18 (3) |
| `Bad_Company/Shooting_Star.mid` | 18 to 19 (16) |
| `Bob_Seger/Blind_Love.mid` | 16 to 18 (8) |
| `Bruce_Hornsby/The_Long_Race.mid` | 21 to 28 (7) |
| `Celentano/Si_e_spento_il_sole.2.mid` | 16 to 17 (5), 17 to 22 (5), 22 to 24 (5) |
| `Creed/Higher.3.mid` | 30 to 32 (8), 21 to 30 (8) |
| `Culture_Beat/Anything.1.mid` | 21 to 22 (7) |
| `Fleetwood_Mac/Sara.mid` | 20 to 29 (7), 29 to 31 (7) |
| `Four_Tops/Cant_Help_Myself.mid` | 18 to 20 (6), 13 to 14 (6) |
| `Gilbert_O_Sullivan/Nothing_Rhymed.mid` | 19 to 23 (6) |
| `Leali/Se_qualcuno_cercasse_di_te.1.mid` | 16 to 20 (7) |
| `Lunapop/50_Special.1.mid` | 31 to 32 (9) |
| `Monty_Python/Always_Look_on_the_Bright_Side_of_Life.mid` | 30 to 32 (8) |
| `Nine_Days/Absolutely_Story_of_a_Girl_.mid` | 17 to 22 (7), 16 to 17 (10) |
| `RICHIE_LIONEL/All_Night_Long.2.mid` | 21 to 26 (4), 26 to 28 (4) |
| `Stone_Temple_Pilots/Dead_Bloated.1.mid` | 15 to 30 (9) |
| `Wolter_Kroes/Laat_me_los.mid` | 17 to 21 (3) |
| `Zucchero/Diamante.2.mid` | 19 to 29 (18), 16 to 17 (7) |

Exact old and new source tick coordinates and support for every step are stored under `real_pilot.<algorithm>.changed_selections` in `research_local/closed_patterns_v01_replication/aggregate.json` and under each real row in `raw_results.json`.

The indexed generator required 392.0 seconds for the 128 files, compared with 432.8 seconds for aligned in the corrected replication. Search limits affected 23 files and the 80-candidate shortlist was truncated in 125 files for each generator. Runtime and selection changes do not measure real phrase accuracy.

## Replication and integrity

The initial run completed with valid bound result artifacts, but its manually declared source list did not include the transitive `samuged.metadata_recovery` import. It is preserved at `research_local/closed_patterns_v01`.

The authoritative replication at `research_local/closed_patterns_v01_replication` used the updated automatic local import closure. Its snapshot contains 13 files, including `samuged/__init__.py` and `samuged/metadata_recovery.py`. Both completion receipts verify. After removing runtime fields and receipt-specific hashes, the aggregate and raw results are exactly equal between runs.

Authoritative artifact hashes:

- `aggregate.json`: `04393a86e0127203a15b8bc5ed52d11b358c3ab48d0835b41d43d4ff9bcee50e`
- `raw_results.json`: `03268d02753b264ac8150e8c732bf96c405ee1c1858ab5b3ba2c9903a8aff395`
- `completion_receipt.json`: `98f46af700384176ae2406e5db360be61e404ea10773e57e99fd84e82e992aed`

Reproduction command:

```bash
source .venv/bin/activate
nice -n 10 python scripts/evaluate_closed_patterns.py \
  --output research_local/closed_patterns_v01_replication
```

The output directory must be new and empty because the experiment receipt is immutable.

## Interpretation

The synthetic result justifies retaining this method as an optional variant for full-corpus validation. It does not justify replacing the reference default. Exact recurrence does not resolve the musical segmentation ambiguity of a periodic passage. The 15-to-30-note real extension and four ceiling-reaching changes show why a maximal symbolic repeat may be longer than a listener-defined phrase.

No result here measures musical quality, listener response or memorability.
