# SaMuGeD recurring phrases

SaMuGeD extracts recurring melodic phrases and separate percussion patterns from MIDI. Each candidate includes a source hash, exact tick coordinates, verified occurrences, score components and a playable MIDI excerpt. The research pipeline runs locally and leaves source files unchanged.

The current work uses the local Lakh MIDI Clean collection. The output is a collection of **recurring symbolic candidates**. Recurrence does not establish that a phrase is catchy, memorable or an earworm. Those properties need separate listener evidence.

## Run locally

```sh
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-research.lock
pytest -q
python -m samuged.cli build \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_reference_run \
  --workers 4 --percussion --recover-invalid-keys
python -m samuged.audit \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_reference_run --require-full
```

Start with `--limit 128` and a separate output directory for a deterministic pilot. Omit `--require-full` when auditing a pilot. Recovery is optional and affects only structurally validated invalid key metadata in memory; every repair is recorded.

`--algorithm aligned_indexed` enables note insertion and deletion alignment. It improves some controlled tests but is slower and has mixed external results. The fixed-length `reference` algorithm remains the default. Both use the same independent percussion branch.

`--algorithm aligned_closed` adds a tested selection rule that can extend a verified exact repeat while preserving at least three occurrences. It uses the indexed alignment detector and records each replacement. The [closed-pattern study](docs/research/closed_patterns.md) separates its synthetic improvement from unlabelled changes in real songs.

`--algorithm aligned_melody` also gives a small preference to parts with monophonic note structure. The fixed optional rule improved agreement with the official melody part on a heldout POP909 cohort. It does not estimate hook quality. The [part-ranking study](docs/research/part_ranking.md) records the development decision, independent checks and Lakh pilot changes.

## Research and artifacts

- [Local delivery](docs/research/DELIVERY.md): ready archives, improved algorithm variants, listening packet and paper status.
- [Research guide](docs/research/README.md): methods, schemas, reproducible commands and interpretation limits.
- [Artifact index](docs/research/artifact_index.md): exact local dataset, release and experiment receipts.
- [Work log](docs/research/WORK_LOG.md): measured results and the state of local full builds.
- [Primary sources](docs/research/sources.md): dataset identity, previous methods and external evaluation evidence.
- [Duplicate screening](docs/research/duplicate_screening.md): grouped splits and the supplementary exclusion view.
- [Drum evaluation](docs/research/drum_specificity.md): separate percussion tests and an independent pair oracle.
- [Certified drum controls](docs/research/certified_drum_controls.md): separate negative controls, positive families and replay checks.
- [External theme diagnostic](docs/research/theme_evaluation.md): comparison with three human annotations of six popular songs.
- [External selector comparison](docs/research/selection_external.md): closed selection and the melody prior on reused annotated inputs.
- [Annotation protocol](docs/research/annotation_protocol.md): blinded local review with empty human rating fields.
- [Paired listening review](docs/research/paired_review.md): anonymous A/B comparisons with source verified playback.
- [Rating analysis](docs/research/paired_ratings_analysis.md): checked exports, null preservation and agreement summaries.
- [Recurrence examples](docs/research/recurrence_examples.md): source timelines and piano rolls for melody and drums.
- [Installed package check](docs/research/installed_package_check.md): isolated wheel installation and CLI validation.
- [Portable release verification](docs/research/release_verification.md): metadata, archive and included replay checks without the source corpus.
- [Consumer guide](docs/research/consumer_guide.md): installation scope, safe archive handling and manifest coordinate semantics.
- [Historical project notes](docs/legacy_project_notes.md): earlier applications, setup and plans.

Bulk MIDI, experiment outputs and local release archives are excluded from Git. The software licence is in [LICENSE](LICENSE). Source music and its derivatives have separate rights considerations documented in the research guide. No public dataset release is made by these commands.
