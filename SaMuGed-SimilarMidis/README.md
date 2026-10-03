# SaMuGed Similar MIDI finder

This directory contains the legacy SimilarMidis application. It searches saved MIDI patterns by numerical feature similarity. The project is kept as an archive of the earlier workflow.

## Status

SimilarMidis is not the current recurrence extractor. Its feature vectors, nearest neighbour results and historical pattern dataset should not be presented as the audited recurrence rankings.

The current research guide is [docs/research/README.md](../docs/research/README.md), with the [top 50 analytics guide](../docs/research/top50_analytics.md) as a focused reference. The public releases are the [recurring phrases dataset](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases) and the [earworm loops Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworm-loops).

## Historical features

The archived application includes MIDI feature extraction for pitch, rhythm and tempo, adjustable weights for similarity search, a desktop GUI with piano roll display and MIDI playback, a Flask web interface and Docker Compose files.

These are historical features. They do not describe the current recurrence research release.

## Historical method

The [Clustering repeated motifs notebook](docs/Clustering_repeated_motifs_v040_clean.ipynb) documents the earlier method. It extracts eight values for each MIDI pattern: tempo, pitch mean and standard deviation, note duration mean and standard deviation, mean interval between note onsets and its standard deviation, and syncopation ratio. The application standardizes these vectors, searches them with FAISS and can apply user selected feature weights.

This method measures feature similarity between saved MIDI patterns. It is not the current recurrence extractor and does not define the public recurrence tables.

Historical records are kept in the [progress log](docs/PROGRESS.md) and the [dataset creation scripts](../testing_tools/test_scripts/asle_scripts/README.md).

## Installation

Create an environment and install the legacy desktop dependencies:

```bash
git clone https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSamplerAI-2024
cd SaMuGeD-Algoritmi-DrDreSamplerAI-2024/SaMuGed-SimilarMidis
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the desktop application with:

```bash
python app.py
```

## Web application

From the repository root, the Docker workflow is:

```bash
cd SaMuGed-SimilarMidis
docker-compose up -d
```

Open http://localhost:5000 after the container starts.

For a local Flask run, start from the repository root with the legacy environment active:

```bash
pip install flask gunicorn matplotlib
cd SaMuGed-SimilarMidis
PYTHONPATH=. flask --app web/app.py run
```

## Historical dataset

Place the MIDI files under:

```
SaMuGed-SimilarMidis/datasets/Lakh_MIDI_Clean_Patterns_v1/
```

The historical workflow used the Lakh MIDI Clean Patterns v1 collection from Asle Øren. The retained [source archive link](https://universitetetitromso.sharepoint.com/:u:/s/O365-AIMusicExpo2024/ETsYg7LmqI5LtZEQOsQR0FsB8mK_bY02lymu1OI_9lb7oA?e=5RFmuH) may require a UiT account. Without this directory, the legacy application cannot search the dataset.

## Soundfont note

The legacy path is `soundfonts/FluidR3_GM.sf2`. The filename is historical. The checked file embeds MS_General v0.1, so its name does not establish that it is an authentic FluidR3 source. The legacy file has SHA256 `2aacd036d7058d40a371846ef2f5dc5f130d648ab3837fe2626591ba49a71254`.

The publication renderer uses a separately obtained authentic FluidR3 soundfont. Its SHA256 is recorded with the publication rendering receipt. The legacy file and the publication renderer font must not be treated as byte-identical.
