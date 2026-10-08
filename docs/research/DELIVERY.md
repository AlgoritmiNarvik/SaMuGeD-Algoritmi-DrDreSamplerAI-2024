# Published release

[Dataset](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases) · [Loop player](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms) · [Research note PDF](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/paper/samuged_recurring_phrases.pdf)

## Dataset contents

| Selection | Melodic phrases | Drum patterns | Total |
| --- | ---: | ---: | ---: |
| Closed, primary release | 50,566 | 44,511 | 95,077 |

The fixed window reference selection (50,439 melodic phrases, 44,511 drum patterns, 94,950 in total) is the baseline of the research note. It stays on the hub as the reference archive and the `data/reference_*` Parquet folders for reproducibility, but it is no longer listed as a dataset configuration. Both selections use the same percussion detector. Source accounting covers 17,232 MIDI paths, 16,995 successful parses and 237 recorded parse failures.

Both releases passed source and MIDI artifact audits. Reference selection replay covers all successful sources. Closed selection replay covers a stratified 256 source sample. The [consumer guide](consumer_guide.md) explains archive verification, metadata and split handling. [Method documentation](README.md) and the [artifact index](artifact_index.md) describe the evidence and experimental variants.

## Listening collection

The player contains 630 rendered cycles. Tool's collection covers 28 songs, 69 riffs, 36 drum patterns and 59 paired versions. Separate web MIDI supplements appear only in the interface. They are excluded from the published Lakh dataset. See the [Tool case study](tool_motifs.md) and [publication guide](../publication/README.md).

Audio is rendered at 48 kHz in stereo with FluidSynth and authentic FluidR3 GM. Lossless FLAC preserves the original PCM samples. WAV downloads are generated in the browser. Source drums are selected by default where available, with separate melody and drum controls.

## Evidence limits

The dataset records symbolic recurrence. There are no listener labels for these phrases. Repetition does not establish catchiness or recognition. Filename identities, search limits, duplicate arrangements and incomplete composition attribution remain documented limitations. The experimental melody prior variant is excluded from the release.

## Public repository scope

The repository contains source code, tests, method documentation, experiment summaries and required assets. The two original English project PDFs are retained as historical project material. Personal status reports, session logs, temporary previews and generated presentations stay in ignored local directories. The scientific PDF is distributed with the dataset.
