# SaMuGeD recurring phrases

SaMuGeD extracts recurring melodic phrases and separate percussion patterns from MIDI. Each candidate includes a source hash, exact tick coordinates, verified occurrences, score components and a playable MIDI excerpt. The research pipeline leaves source files unchanged.

The current work uses a Lakh MIDI Clean snapshot. The output is a collection of **recurring symbolic candidates**. Recurrence does not establish that a phrase is catchy, memorable or an earworm. Those properties require separate listener evidence, which is not part of the algorithmic dataset release.

## Dataset and listening demo

The primary release uses `aligned_closed`, with 95,077 phrases, 50,566 melodic and 44,511 percussion. `reference_v04` is the conservative audited comparison package, with 94,950 phrases, 50,439 melodic and 44,511 percussion. Neither release contains listener labels. Download the six page [research note](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/paper/samuged_recurring_phrases.pdf).

The dataset is [Hugging Face: `AlmazErmilov/samuged-recurring-phrases`](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases). The static demo is [Hugging Face Space: `AlmazErmilov/samuged-earworm-loops`](https://huggingface.co/spaces/AlmazErmilov/samuged-earworm-loops). The demo shows real source loop cycles and a separate song level evidence view that supports familiar-hook selection. The Space has four groups of ten rendered loops, WAV, FLAC and MIDI downloads plus the five top 50 views. Playback continues until stopped. The familiar hook group uses published song level recognition or earworm evidence, with three separately extracted leading parts. See [selection evidence](docs/research/familiar_hooks.md).

See [publication and rendering](docs/publication/README.md) for package, SoundFont and upload instructions.

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

- [Research status and publication](docs/research/DELIVERY.md): audited releases, publication targets, improved algorithm variants and the historical pause boundary.
- [Research guide](docs/research/README.md): methods, schemas, reproducible commands and interpretation limits.
- [Local artifact index](docs/research/artifact_index.md): exact dataset, release and experiment receipts from the full checkout.
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

Bulk MIDI, experiment outputs and release archives are excluded from Git. The software licence is in [LICENSE](LICENSE). Source music and its derivatives have separate rights considerations documented in the research guide. The public dataset and demo are available on Hugging Face.
