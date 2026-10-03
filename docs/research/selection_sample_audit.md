# Selection replay

The full ordinary dataset audit checks every recorded source, occurrence geometry and MIDI export. Complete algorithm selection replay is more expensive and has a different scope. This additional audit re-extracts either every successful source or a frozen, deliberately stratified sample. It never changes the original dataset audit.

The completed full reference replay is `research_local/selection_all_reference_v01`.
All 16,995 successful sources passed with no discrepancies, including the 28
metadata-recovered sources. The 237 parse errors remain separately accounted
for by the ordinary audit. Wall time was 4,378.880 seconds and summed worker
time 8,746.157 seconds under concurrent workloads. The completion receipt has
SHA256 `3e606ae6fcf60fd979df9a6e238514f54887e5d0631ebed6102fb66b84cbf830`.
An independent coverage check at
`research_local/selection_all_reference_root_check_v01.json` reconstructs the
successful source ID set and all canonical source record hashes. The complete
replay is included in the local `reference_v04` release.

```sh
source .venv/bin/activate
python scripts/audit_selection_sample.py \
  --dataset research_local/lakh_phrases_v03 \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_selection_sample \
  --count 256 --workers 4 --seed 20261003
python scripts/verify_experiment.py --experiment research_local/my_selection_sample
```

To replay every successful source in a completed full build, use the explicit
all-successful mode. Do not combine it with `--count`:

```sh
python scripts/audit_selection_sample.py \
  --dataset research_local/lakh_aligned_indexed_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/selection_sample_all_successful_v01 \
  --all-successful --workers 6 --seed 20261003
```

This mode derives its cohort from every manifest row with `status: ok`, an
outcome of `matched` or `no_match` and a source SHA256. It records the total
manifest source count, successful source count, error source count and
`selection_covers_all_successful_sources: true`. Error rows are excluded from the replay cohort and counted separately.
Malformed successful rows fail the scope gate. The
result therefore does not claim that parse errors were re-extracted.

The gate requires a passed full audit bound to the current source manifest, phrase manifest, build configuration and summary. It verifies the source inventory, detector module bytes against the build provenance and Python/runtime compatibility. Only the selected sources are hashed and re-extracted again. Unselected source bytes are not reverified by this supplementary check.

Selection orders successful records by SHA256 of the audit version, seed, source SHA256 and source ID. Metadata-recovered sources are taken first. The remaining slots balance sources with and without a melodic or percussion search limit. This is a targeted implementation audit, not a representative accuracy sample. A new seed changes the order; the recorded cohort, strata and exact detector evidence are frozen before replay.

Each selected source is parsed under the recorded metadata policy, repair receipts and warnings are compared, and all detector outputs and telemetry are replayed. Closed traces and optional part ranking receive their existing additional checks. Source hashes are rechecked after each replay, with dataset manifests and core provenance rechecked before completion. Worker processes run independently; worker time and wall time are reported separately.

The all-successful mode submits the same frozen cohort to the worker pool and
uses completion-order collection for bounded progress messages every 100
completed sources. Final raw rows are sorted by source hash and source ID, so
worker scheduling does not change the receipt or aggregate ordering.

The earlier bounded reference run is `research_local/selection_sample_reference_v02`. All 256 selected sources passed, comprising all 28 metadata-recovered sources, 114 other search-limited sources and 114 non-limited sources. No failures occurred. Wall time was 37.734 seconds and summed worker time 147.143 seconds under concurrent corpus workloads. The frozen selection-record hash is `46a1d9a356d642234c9499afb96c2f3f5bad8ddab09f20dfc7a3242596f4b1b3`, receipt hash `782341430f4b163f2c994aa61706f89bdf3e9fb8c24e971b9ce2b8ddc9d4baed` and source snapshot hash `706682c884757146a0c7cfd42455d9a9055465610b69b81dbcfbb191f23666bb`.

The earlier 16-source smoke at `research_local/selection_sample_audit_v01` used a preceding script snapshot and selected only recovered sources. Both receipts remain unchanged. Passing a sample does not mean the entire source corpus has been re-extracted, does not validate an untested implementation change and does not supply human musical quality labels.

## Including a completed replay in a release

Packaging accepts a completed replay explicitly and copies its portable receipt,
source snapshot and declared result artifacts into a separate evidence directory:

```sh
python scripts/package_dataset.py \
  --dataset research_local/lakh_phrases_v03 \
  --output research_local/releases/reference_with_replay \
  --selection-replay research_local/selection_sample_reference_v02
```

The package command rechecks the experiment completion receipt, executable
source snapshot, result hashes, dataset source and phrase manifest hashes,
build configuration, summary, audit hash and run key. It also checks that every
selected source ID, source hash and manifest-record hash is present exactly
once and that every raw case passed. A copied replay is verified again after it
is placed at `evidence/selection_replay/`; symlinks and files outside the
declared experiment set are rejected.

The primary artifact audit remains separately represented by
`release.json.audit_scope.primary_audit_passed` and its existing
`audit_sha256`. Replay counts and the completion receipt hash are supplementary
fields under `audit_scope.selection_replay`. The all-successful flag is true
only when the selected IDs equal every `status: ok` source in the manifest and
the recorded successful and error totals agree. A bounded replay remains a
sample even when all of its cases pass. No packaging option modifies the
dataset's `audit.json` or promotes a sample to a full selection replay.

## Completed closed sample

The full `aligned_closed` corpus has a separate completed replay at
`research_local/selection_sample_closed_v02`. All 256 selected sources pass,
including all 28 metadata-recovered sources, 114 other search-limited sources
and 114 unlimited sources. Wall time is 248.877 seconds and summed worker time
is 987.177 seconds under concurrent jobs. The completion receipt SHA256 is
`86555f8e7b1e58870796b511ac639108ad26a9ab800d709a0b78ff58241a004b`.
The replay is included in the verified local `closed_v01` archive. It does not
claim full-corpus candidate-generation replay.
