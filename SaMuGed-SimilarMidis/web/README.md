# SaMuGed web application

This is the archived Flask interface for the SimilarMidis feature similarity workflow. It is retained for historical use and does not implement the current audited recurrence extractor.

The current research guide is [one level up in docs/research](../../docs/research/README.md). The public releases are the [recurring phrases dataset](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases) and the [earworms Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms).

## Requirements

For Docker, install Docker and Docker Compose.

For a direct run, use Python 3.9 or later, FluidSynth with its development libraries and the Python packages in `requirements.txt`.

## Run with Docker

From the repository root:

```bash
cd SaMuGed-SimilarMidis
docker-compose up -d
```

Open http://localhost:5000.

## Run without Docker

On Ubuntu or Debian, the historical system setup was:

```bash
sudo apt-get update
sudo apt-get install -y fluidsynth libfluidsynth-dev
```

From the repository root, activate the legacy Python environment and start Flask:

```bash
cd SaMuGed-SimilarMidis
pip install -r requirements.txt
PYTHONPATH=. flask --app web/app.py run
```

Open http://localhost:5000.

## Historical dataset

Place the MIDI dataset at:

```
SaMuGed-SimilarMidis/datasets/Lakh_MIDI_Clean_Patterns_v1/
```

The [historical dataset scripts](../../testing_tools/test_scripts/asle_scripts/README.md) describe the earlier pattern creation workflow. They do not define the current recurrence dataset.

## Soundfont

The legacy application expects:

```
SaMuGed-SimilarMidis/soundfonts/FluidR3_GM.sf2
```

This filename is historical. The file embeds MS_General v0.1. Publication rendering uses a separately obtained authentic FluidR3 soundfont and records that font SHA256 in the publication rendering receipt.

## Historical controls

The web interface supports MIDI upload, feature weight controls, similarity search, piano roll display and browser playback. These controls describe the archived SimilarMidis workflow.

See the [main archival guide](../README.md), the [historical notebook](../docs/Clustering_repeated_motifs_v040_clean.ipynb) and the [progress log](../docs/PROGRESS.md) for context.
