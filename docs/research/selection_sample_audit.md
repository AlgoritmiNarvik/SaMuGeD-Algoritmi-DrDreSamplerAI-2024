# Selection replay sample

The full ordinary dataset audit checks every recorded source, occurrence geometry and MIDI export. Complete algorithm selection replay is more expensive and has a different scope. This additional audit re-extracts a frozen, deliberately stratified sample. It never changes the original dataset audit.

```sh
source .venv/bin/activate
python scripts/audit_selection_sample.py \
  --dataset research_local/lakh_phrases_v03 \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_selection_sample \
  --count 256 --workers 4 --seed 20261003
python scripts/verify_experiment.py --experiment research_local/my_selection_sample
```

The gate requires a passed full audit bound to the current source manifest, phrase manifest, build configuration and summary. It verifies the source inventory, detector module bytes against the build provenance and Python/runtime compatibility. Only the selected sources are hashed and re-extracted again. Unselected source bytes are not reverified by this supplementary check.

Selection orders successful records by SHA256 of the audit version, seed, source SHA256 and source ID. Metadata-recovered sources are taken first. The remaining slots balance sources with and without a melodic or percussion search limit. This is a targeted implementation audit, not a representative accuracy sample. A new seed changes the order; the recorded cohort, strata and exact detector evidence are frozen before replay.

Each selected source is parsed under the recorded metadata policy, repair receipts and warnings are compared, and all detector outputs and telemetry are replayed. Closed traces and optional part ranking receive their existing additional checks. Source hashes are rechecked after each replay, with dataset manifests and core provenance rechecked before completion. Worker processes run independently; worker time and wall time are reported separately.

The preferred reference run is `research_local/selection_sample_reference_v02`. All 256 selected sources passed, comprising all 28 metadata-recovered sources, 114 other search-limited sources and 114 non-limited sources. No failures occurred. Wall time was 37.734 seconds and summed worker time 147.143 seconds under concurrent corpus workloads. The frozen selection-record hash is `46a1d9a356d642234c9499afb96c2f3f5bad8ddab09f20dfc7a3242596f4b1b3`, receipt hash `782341430f4b163f2c994aa61706f89bdf3e9fb8c24e971b9ce2b8ddc9d4baed` and source snapshot hash `706682c884757146a0c7cfd42455d9a9055465610b69b81dbcfbb191f23666bb`.

The earlier 16-source smoke at `research_local/selection_sample_audit_v01` used a preceding script snapshot and selected only recovered sources. Both receipts remain unchanged. Passing a sample does not mean the entire source corpus has been re-extracted, does not validate an untested implementation change and does not supply human musical quality labels.
