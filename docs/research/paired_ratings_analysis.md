# Paired ratings analysis

`scripts/analyze_paired_ratings.py` validates local exports from the offline paired review packet and writes a receipt bound descriptive report. It does not assign missing labels, estimate which algorithm is better or turn repeated ratings from the same packet into independent samples.

## Validation boundary

The command accepts a packet directory and one or more JSON exports. Before it reveals left and right identities, it checks all of the following:

* `review.html`, `packet_receipt.json`, `input_manifest.json` and `blind_mapping.json` are present.
* The receipt hashes for the HTML, manifest and mapping match their bytes.
* The embedded packet hash, receipt hash binding, manifest binding and mapping binding agree.
* Every review ID occurs exactly once in the packet and mapping.
* Each A and B candidate binding has the exact orientation declared by `side_order`.
* The selected source path, hash and metadata repair receipts agree between the input manifest and blind mapping.
* Every export contains exactly one row per packet pair and passes `make_paired_review.validate_ratings`.
* Every nonempty rated export has a distinct, nonempty annotator ID. An all null export may keep its annotator ID null.

The four packet artifacts and every ratings export are copied byte for byte into `input_snapshot/`. The start receipt freezes their hashes, packet cases, configuration and executable source closure. The completion receipt binds the copied inputs, `raw_results.json`, `aggregate.json` and `input_snapshot.json`. The command checks the original input bytes again before completion. It never modifies the HTML or exported ratings files.

This is an internal packet binding check. The analyzer checks that generator code hashes in `input_manifest.json` are well formed and internally consistent, but it does not independently obtain those historical generator files and compare their bytes with the declarations. It also does not reload source MIDI files or reconstruct the notes rendered into the packet. Valid older packets can therefore be analyzed after the working repository changes. The analyzer's own executable source closure is a separate artifact: `prepare_experiment` snapshots the exact analyzer and imported local code used for each analysis run. `aggregate.json.validation_scope` records these boundaries directly.

## Report definitions

An A or B preference is converted to `left` or `right` only through the receipt bound `side_order`. `tie` and `uncertain` retain their meanings. A null preference remains `missing`, including in `raw_results.json`.

Counts are reported for each export and annotator. The same five outcomes are reported separately for byte identical rendered pairs and informative rendered pairs. A choice on an identical rendered pair is retained as an observed interface response, but it is not evidence that one algorithm produced a preferred rendering.

For every pair of exports, raw agreement and Cohen's kappa use only rows rated by both annotators. Results are shown for all pairs, informative pairs and identical rendered pairs. Kappa is null with fewer than two jointly rated rows or when expected agreement is one. These statistics describe agreement within this packet. They do not measure corpus quality or perceptual quality.

## Command

```bash
source .venv/bin/activate
python scripts/analyze_paired_ratings.py \
  --packet research_local/paired_review_pilot_v03 \
  --ratings /path/to/annotator-1.json /path/to/annotator-2.json \
  --output research_local/paired_ratings_study_v01
```

Use a new output directory for every analysis. Add `--machine-ui-test` only for an explicitly machine generated or interface smoke export. Such a run remains separate from human evidence.

## All null smoke results

`research_local/paired_ratings_empty_v01` exercises the real `paired_review_pilot_v03` packet with one machine generated export containing twelve null preferences and null notes. It is explicitly marked `machine_ui_test: true` and has status `no_ratings`. It contains no human labels.

The packet hash is `87f6003143ef5922ccdb3e7a1a813195284a671c2ea2dbf670cb513724f94e9a`. The packet contains twelve melodic pairs, seven byte identical rendered pairs and five informative rendered pairs. All twelve outcomes are missing. No pairwise agreement row exists because the smoke run has one export.

The start receipt SHA256 is `e4dd94099a66b6b5a0715e2e504e599062732cd4b97f804cdf2d82749c355bc5`. The completed aggregate SHA256 is `eb73c3331c7cd00165d248c552e3b6fb93a27a08c9ce4b1b4f42b1afb19f0680`, and the raw results SHA256 is `4cb7c4daae1b7745f92a9ed0768092f7c5aa8d2a44608df39fcd7613d17039fb`.

This smoke result verifies packet and export validation, unblinding boundaries, null preservation and receipt completion. It does not establish that the browser export control works and does not contain a listening judgment.

`research_local/paired_ratings_empty_v02` is the preferred smoke artifact. It repeats the same all null machine test with the explicit `validation_scope` fields described above. Its start receipt SHA256 is `8e54e1bed92b2a86aa86cfd7b78123c86f47c3c2ea32441feaa8d56642804b0b`, aggregate SHA256 is `5e58c3e0274f36da26f0ae56f373dff4913c4185303eaa057d5841d0441b4365` and raw results SHA256 is `3cadd7a07a1252e5f63ede7ea4b59cc91343c40c691a946ecb3b0cb7e883ef84`. Version 1 remains frozen for provenance and is not modified.
