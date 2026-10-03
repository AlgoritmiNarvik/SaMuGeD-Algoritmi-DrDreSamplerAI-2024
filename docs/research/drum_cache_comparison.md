# Drum cache changed case comparison

This local audit checks the changed rows from `research_local/drum_cache_full_v02` against the strict v02 source manifest. It compares saved baseline and candidate phrase records and independently checks every saved prototype to occurrence edge with `samuged.drum_oracle`. It does not rerun either detector and makes no claim about musical quality or promotion.

The reproducible receipt and detailed result are in `research_local/drum_cache_changes_v01/`. The audit froze the completed cache, the strict manifest and the 16 referenced source MIDI files before checking them. The output has a start receipt, source snapshot, raw results, aggregate results and completion receipt. The cache itself was required to pass its existing completion receipt before this audit started.

## Frozen inputs and method

- Completed differential cache: `research_local/drum_cache_full_v02/`
- Strict source manifest: `research_local/lakh_phrases_v02/sources.jsonl`, SHA256 `fa4c3010b8b17fdd8fbd58c87257281c01abf4a7325f94481fd9b5dfd3380823`
- Saved baseline implementation SHA256: `d1c3f1382417334d4fdd9ead7df9b5885f39c85dcbe9fc4d6b256a552098c9fa`
- Saved candidate implementation SHA256: `81c22d65293e3b817bfa79083eb873e73f1deaa48db1769719911b33dff44fed`
- Parsed cache rows: 16,967, with 265 strict parse errors recorded by the original run
- Changed parsed source rows: 16
- Independent oracle: `drum-pair-oracle-v1`
- Oracle windows: 1, 2 and 4 complete meter bars, minimum 8 hits and 2 pitches
- Direct edge gate: distinct prototype and occurrence windows, same bar and meter geometry, no overlap and at most the oracle's one tenth hit edit allowance using maximum cardinality pitch onset matching
- Canonical check: source derived pitches, relative onset fractions, durations, velocities, family hash, geometry, drum metadata and occurrence coordinates

Every changed file was search limited in both saved methods. This matters because the differential output describes bounded detector searches, not an unrestricted search equivalence.

## Aggregate findings

The audit validated 48 baseline phrases and 48 candidate phrases. All 361 direct prototype to occurrence edges passed the independent oracle, with no source coordinate, meter, gate or canonical array failures.

The candidate changed the selected family set in every changed file. Across file level selections, 23 baseline candidates disappeared and 23 candidate families were newly selected. Occurrence support gained 132 endpoint instances and lost 97. Four files changed top rank. The 25 families retained by both methods had identical recurrence scores; score differences therefore occur in replacement families and are selection diagnostics rather than evidence of better musical quality.

## File level differences

Family IDs are shown by their first eight hexadecimal characters. `n` is occurrence support and `r` is one based selection rank. Scores are the saved detector recurrence scores. The edge counts are independently validated direct prototype edges.

| source file | top rank changed | baseline families no longer selected | candidate families newly selected | direct edges |
| --- | --- | --- | --- | ---: |
| `AC_DC/For_Those_About_To_Rock_We_Salute_You_.mid` | no | `71998783` r3 n6 0.79443516 | `f50bbf54` r2 n7 0.79464010 | 17 -> 18 |
| `Dire_Straits/Sultans_of_Swing.12.mid` | yes | `805419bb` r3 n6 0.80876650 | `d559cb2d` r1 n4 0.82709395 | 14 -> 12 |
| `Genesis/One_for_the_Vine.1.mid` | no | `11fba632` r2 n8 0.73847092, `f7d56109` r3 n3 0.73778462 | `6db6c1f3` r3 n2 0.75636679, `cf4fa71b` r2 n2 0.75796427 | 13 -> 6 |
| `Metallica/One.1.mid` | yes | `437a0a95` r1 n6 0.69955595, `a18a2248` r2 n3 0.68637426, `f4704086` r3 n4 0.67230970 | `739e5b47` r3 n2 0.71313654, `7490feda` r2 n2 0.71413206, `91797a35` r1 n2 0.71770405 | 10 -> 3 |
| `Puff_Daddy/Its_All_About_the_Benjamins_remix_.mid` | yes | `429effdd` r1 n7 0.86090271, `b8b89c7b` r3 n4 0.84816424, `cf7fd3eb` r2 n4 0.85013918 | `3201f55c` r2 n15 0.91362631, `757e0f75` r3 n15 0.91362631, `89c5b31b` r1 n15 0.91362631 | 12 -> 42 |
| `Rush/The_Camera_Eye.1.mid` | no | `87e8c4b1` r3 n6 0.66621406 | `cbd1404f` r2 n12 0.68690690 | 15 -> 21 |
| `Rush/The_Camera_Eye.2.mid` | no | `87e8c4b1` r3 n6 0.66621405 | `cbd1404f` r2 n12 0.68690689 | 15 -> 21 |
| `Simply_Red/Something_Got_Me_Started.1.mid` | yes | `49985842` r1 n2 0.67293131, `c878d376` r2 n2 0.67272999, `cb2ae5c5` r3 n2 0.66864206 | `e51b4e5b` r1 n2 0.73777069, `ec88cc3c` r2 n2 0.73776971, `f59ad27a` r3 n2 0.73711242 | 3 -> 3 |
| `Steely_Dan/Josie.1.mid` | no | `9e1844a2` r3 n3 0.62565529 | `b27f16c4` r3 n2 0.62711833 | 6 -> 5 |
| `Steely_Dan/Josie.2.mid` | no | `9e1844a2` r3 n3 0.62565530 | `b27f16c4` r3 n2 0.62711835 | 6 -> 5 |
| `Steely_Dan/Josie.3.mid` | no | `9e1844a2` r3 n3 0.62566309 | `b27f16c4` r3 n2 0.62713910 | 6 -> 5 |
| `Steely_Dan/Josie.mid` | no | `9e1844a2` r3 n3 0.62565530 | `b27f16c4` r3 n2 0.62711835 | 6 -> 5 |
| `Yes/Heart_of_the_Sunrise.1.mid` | no | `b58ed54d` r3 n4 0.74100413 | `c1435c59` r2 n7 0.80997012 | 10 -> 13 |
| `Yes/Heart_of_the_Sunrise.2.mid` | no | `b58ed54d` r3 n4 0.74100413 | `c1435c59` r2 n7 0.80997012 | 10 -> 13 |
| `Yes/Heart_of_the_Sunrise.3.mid` | no | `b58ed54d` r3 n4 0.74100413 | `c1435c59` r2 n7 0.80997012 | 10 -> 13 |
| `Yes/Heart_of_the_Sunrise.mid` | no | `b58ed54d` r3 n4 0.74100413 | `c1435c59` r2 n7 0.80997012 | 10 -> 13 |

The candidate's new families can have more or fewer supported occurrences than the baseline family they replace. The largest increase is the Puff Daddy row, where each selected candidate family has 15 occurrences and the independently checked direct edge count rises from 12 to 42. The Genesis and Metallica rows reduce direct edge counts while still passing the source oracle. These are selection changes under the saved bounded search.

## Limits

The audit covers only the 16 files whose saved baseline and candidate phrase lists differ. It does not re-evaluate the 16,951 unchanged parsed rows. All changed rows were search limited, so this is not evidence that the candidate and baseline agree or differ under unlimited search. The independent oracle checks symbolic coordinates, canonical source arrays and admissibility gates. It does not judge salience, musical role, perceptual usefulness or human relevance. The 265 strict parse errors remain outside changed edge verification and are not silently recovered.
