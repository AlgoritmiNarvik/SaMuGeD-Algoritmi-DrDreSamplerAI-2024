---
license: cc-by-4.0
language:
- en
tags:
- music
- midi
- symbolic-music
- repetition
- percussion
pretty_name: SaMuGeD Earworms (Ostinato / Catchy musical hooks)
size_categories:
- 10K<n<100K
configs:
  - config_name: closed_melodic
    default: true
    data_files:
      - split: all
        path: data/closed_melodic/*.parquet
  - config_name: closed_percussion
    data_files:
      - split: all
        path: data/closed_percussion/*.parquet
  - config_name: reference_melodic
    data_files:
      - split: all
        path: data/reference_melodic/*.parquet
  - config_name: reference_percussion
    data_files:
      - split: all
        path: data/reference_percussion/*.parquet
---

# SaMuGeD Earworms (Ostinato / Catchy musical hooks)

Source verified recurring MIDI phrases with separate drum patterns.

[![Dataset](https://img.shields.io/badge/Hugging_Face-dataset-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases)
[![Listen](https://img.shields.io/badge/Hugging_Face-listen-ACA0E9?logo=huggingface&logoColor=000)](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms)
[![Research note](https://img.shields.io/badge/Research_note-PDF-626779)](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/paper/samuged_recurring_phrases.pdf)
[![Tests](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024/actions/workflows/research-tests.yml/badge.svg)](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024/actions/workflows/research-tests.yml)
[![Code](https://img.shields.io/badge/GitHub-code-626779?logo=github)](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024)

## Dataset

| Release | Melodic | Percussion | Total |
| --- | ---: | ---: | ---: |
| Closed selection (primary) | 50,566 | 44,511 | 95,077 |
| Fixed window reference | 50,439 | 44,511 | 94,950 |

Rows contain note arrays, verified occurrence coordinates, source hashes and MIDI bytes. The processed Lakh MIDI Clean snapshot has 17,232 source paths, 16,995 successful parses and 237 recorded failures. Both releases passed complete artifact audits. Reference selection replay covers all successful sources, closed replay covers a stratified 256 source sample.

```python
from datasets import load_dataset
phrases = load_dataset("AlmazErmilov/samuged-recurring-phrases", "closed_melodic", split="all")
with open("phrase.mid", "wb") as output:
    output.write(phrases[0]["midi_bytes"])
```

`closed_*` is the primary selection and `reference_*` is the fixed window baseline. Each has melodic and percussion subsets. The percussion patterns use the same detector in both versions.

Filter the original `split` column before training. `overlap_excluded` and `duplicate_excluded` are not training or test rows. [Primary archive](archives/closed.tar.gz) and [reference archive](archives/reference.tar.gz) include manifests, provenance, split views, MIDI and checksums. Extract into an empty directory. Read the [consumer guide](CONSUMER_GUIDE.md).

## Listening and rankings

The [Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms) is a curated listening demo, not the full dataset. Browse the dataset viewer above for more MIDI phrases. Additional web MIDI examples by Tool are demo supplements outside this dataset.

Three top 50 collections cover repeated motifs, popular songs and drums. The Space adds a personal Tool listening collection, including separate web MIDI supplements. These supplements are not included in the dataset. Filter by song or part, compare the layers and follow their source note attacks. A separate ten song selection uses published recognition or earworm occurrence evidence. Five [CSV rankings](analytics/) are included. The original analytic popularity cohort uses an exact historical sales list match. The live Space applies a separate listening curation.

Playback loops until stopped. Download 48 kHz stereo PCM 24 bit WAV, FLAC or loop MIDI. FluidSynth with ColomboGMGS2 17.02 Vanilla renders the listening demo, preserving source notes, tempo and instrument programs. These are not commercial recording excerpts. The complete cycle can extend beyond the detector prototype. [Selection and rendering details](demo/README.md) explain the evidence and source construction.

## Limits and license

**There are no listener labels for these fragments.** Recurrence does not establish catchiness or recognition. Published familiarity evidence applies to songs only. Search limits, part selection, filename identities and duplicate arrangements affect coverage. This is not a perceptually validated benchmark. The experimental melody prior corpus is excluded.

The collection follows the upstream [Lakh CC BY 4.0 declaration](https://colinraffel.com/projects/lmd/). Cite Colin Raffel's 2016 thesis, *Learning Based Methods for Comparing Sequences, with Applications to Audio to MIDI Alignment and Matching*. Composition and arrangement attribution remains incomplete. No independent rights clearance is claimed. Code is MIT. External evaluation datasets are excluded. SoundFont and interface font licenses are included in the Space. No DOI or peer review is claimed.

## Authors

| Author | Contact |
| --- | --- |
| Peiyi Wu | [pewu10205@uit.no](mailto:pewu10205@uit.no) |
| Asle Fjæran Øren | [asleoren@gmail.com](mailto:asleoren@gmail.com) |
| Shayan Dadman | [shayan.dadman@uit.no](mailto:shayan.dadman@uit.no) |
| Almaz Ermilov | [almaz.ermilov@uit.no](mailto:almaz.ermilov@uit.no) |

## Citation

Copy the BibTeX below or [download the bibliography](CITATION.bib). [Citation metadata](CITATION.cff) is also available. This is a dataset release, not a peer reviewed article.

```bibtex
@misc{wu2026samuged,
  author = {Wu, Peiyi and Øren, Asle Fjæran and Dadman, Shayan and Ermilov, Almaz},
  title = {{SaMuGeD} Earworms (Ostinato / Catchy musical hooks)},
  year = {2026},
  version = {0.1},
  url = {https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases},
  note = {Research dataset release}
}
```
