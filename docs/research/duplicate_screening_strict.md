## Duplicate screening analysis

This note records the historical strict-parser v03 duplicate audit and its supplementary split sensitivity view, both bound to the earlier `lakh_phrases_v02` manifests. The recovered `lakh_phrases_v03` corpus instead uses `duplicates_recovered_v01.json` and `screened_splits_reference_v03`, described in [the artifact index](artifact_index.md). All historical hashes below remain unchanged. The screening artifacts preserve the original source and phrase manifests.

### Verified v03 audit

The historical strict report is `research_local/duplicates_full_v03.json`. It fingerprints all 17,232 manifest inputs under one recorded method key. There were zero cache hits. The 16,967 successful fingerprints were `ok` and 265 inputs were parse errors with no fingerprint. The report and its small metadata receipt are:

| Artifact | SHA256 |
|---|---|
| `research_local/duplicates_full_v03.json` | `149e3fdc9d89746d742b204c4a2d24882c0859b6bcb0b5f03cdaa1d9c2945635` |
| `docs/research/results/duplicates_reference_v03.json` | `83a4900881c1d1252c831b8e1b3cc78e88fe76e3ba0539ec89571e8eaeacdd91` |
| method key | `400abafc32565c632785dd7ccc8cdc7ab2c29654e0917ae6e0cb28b592a7c66b` |
| report script | `a29de6974cb23a8fc8b1a35f4618fdd27839ac947018f925c58b9f554303bb81` |

The run generated 7,644,656 pair events and verified 1,026,114 pairs. No pair generation, pair verification or candidate report global limit was reached. The report contains 6,153 symbolic near duplicate candidates, 77 of which cross baseline splits. It also contains four additional exact arrangement candidates that are included by the screening predicate. Exact bytes were zero.

The v03 screening view uses all 6,157 strong edges, not only the 77 cross split edges from the earlier analysis. Of these edges, 6,080 connect sources in the same original split and 77 cross splits. The cross split breakdown is 44 train and test, 29 train and validation and 4 validation and test. The four arrangement-only edges are retained even though they are not symbolic near duplicate edges.

### Manual evidence for the 77 cross split edges

The 77 cross split endpoint identities in v03 match the 77 identities in the earlier v02-derived analysis exactly when compared by endpoint source hashes. The split labels, path fields, Jaccard, containment and shared-shingle values also match. The existing manual title evidence therefore remains applicable: 47 edges have the same normalized title, 11 are probable title aliases, one is a possible alias and 18 have different titles.

Every edge shares at least 169 qualified shingles. Seventy have Jaccard at least 0.60, 74 have containment at least 0.80 and 24 have identical qualified shingle sets. None has identical bytes, an identical full arrangement fingerprint, the same artist key or the same song key. These are screening signals, not song identity labels.

The different-title cases remain useful review evidence. The Diana component contains three files with 12 parts and 5,116 notes each. `Paula_Abdul/Rush_Rush.mid` and `Rush/Cygnus_X-1.mid` each have 9 parts and 3,558 notes. The Culture Beat and Dr. Alban files have 14,221 and 14,225 notes with identical qualified shingle sets. The Peter Gabriel and Quick Pick files share a distinctive kalimba label and each has 4,770 notes. The `Jean_Michel_Jarre/Oxygene,_Part_4.1.mid` and `Vangelis/Movement_2.mid` edge has containment 0.9978 and Jaccard 0.4479, which could indicate an embedded source, medley or false positive.

### Supplementary screened view

`research_local/screened_splits_reference_v01/` applies the policy `train` before `validation` before `test` to whole original `split_group` values connected by all 6,157 strong edges. It marks later groups as `duplicate_excluded` and leaves the original source and phrase manifests unchanged.

| Source screened split | Rows |
|---|---:|
| train | 13,966 |
| validation | 1,352 |
| test | 1,148 |
| duplicate_excluded | 766 |

The view quarantines 44 source groups. It newly excludes 1,739 validation phrase rows and 2,126 test phrase rows. A further 350 phrase rows in the quarantined groups were already family excluded. The resulting phrase view is:

| Phrase screened split | Rows |
|---|---:|
| train | 77,327 |
| validation | 7,037 |
| test | 6,104 |
| overlap_excluded | 478 |
| duplicate_excluded | 3,865 |

The previous cross-only conservative view excluded 43 groups and 673 sources. The additional 93 sources are in screening component `021fc2b3f915a89f536acbfd`, all from the validation split, with paths under the Barbra Streisand and Bee Gees families. This difference comes from using same-split strong edges to connect the full baseline groups before applying the split priority.

This view creates a material distribution shift in validation and test. Report it alongside the baseline metrics and preserve the original split fields. It is a leakage-sensitive derived view, not a corpus quality estimate and not a silent baseline edit.

### Reproduce the screened view

The actual command is:

```sh
source .venv/bin/activate
python scripts/screen_splits.py \
  --dataset research_local/lakh_phrases_v02 \
  --duplicate-report research_local/duplicates_full_v03.json \
  --output research_local/screened_splits_reference_v01
```

The command requires a new or empty output directory. It checks the source and phrase manifest hashes, the duplicate report manifest hash, the one-method fingerprint receipt and the global limit flags before writing `source_splits.jsonl`, `phrase_splits.jsonl`, `candidate_edges.jsonl` and `summary.json`.

Consumers must join the derived phrase view by `phrase_id` and use `screened_split` explicitly. For example:

```python
screened = {
    row["phrase_id"]: row["screened_split"]
    for row in read_jsonl("research_local/screened_splits_reference_v01/phrase_splits.jsonl")
}
for phrase in read_jsonl("research_local/lakh_phrases_v02/phrases.jsonl"):
    derived_split = screened[phrase["phrase_id"]]
```

The baseline `sources.jsonl` and `phrases.jsonl` remain the source of original split labels. A packaging or evaluation job should retain both values and show which one it used.

### Historical v02 note

The earlier proposal used `research_local/duplicates_full_v02.json` (`c5f3fc13a75d678a0b5d63930d61c0b7987139e8fa2e92129538ece88b7499ab`) and the derived analysis `research_local/duplicate_screening_analysis_v01.json` (`157d49243c79223b1ff3e8bf4d614b25fe097487f4529f7419023ebb2c971efb`). That note is superseded for current counts. Its cache provenance mixed two method keys, while v03 records one key for all 17,232 inputs and zero cache hits. The v03 report and receipts are the reproducibility boundary for this view.

### Coverage limits

The fingerprint uses transposition-invariant interval and median-normalized rhythm shingles. It ignores shingle order and frequency, instrumentation, harmony and most duration information. High containment can therefore represent a shared part or excerpt. The method is heuristic and does not prove composition identity or complete corpus coverage. The 265 parse errors were not searched for duplicate evidence.

The complete v03 report, provenance snapshot, fingerprint receipt and screened artifacts are large. Small metadata-only receipts with exact hashes are in:

- `docs/research/results/duplicates_reference_v03.json`
- `docs/research/results/screened_splits_reference_v01.json`

The metadata receipt hashes are `duplicates_reference_v03.json` `83a4900881c1d1252c831b8e1b3cc78e88fe76e3ba0539ec89571e8eaeacdd91` and `screened_splits_reference_v01.json` `4b06991b92085db4881be805f3f0f1c0c54a4c6e2111a2c25a2d24b3a9f8276d`.

The screened summary hash is `53c5c3dcf2c2f803dfd69269aca127c5fc30cba9c6827ef1665eee9ada475200`. Its artifact hashes are recorded in the receipt and are also `source_splits.jsonl` `ab5e2395667e46f646351d95e58c3264c928d117a466a939d9334eb1607fb38a`, `phrase_splits.jsonl` `fa1528c7eff52791ea811dfa04e33dba3b3b4a90debe9043f0a4a3507bcb469a` and `candidate_edges.jsonl` `d5406eb580bc27d283e66e560a72977381f039f82bf643aecb378a694b968fe5`.
