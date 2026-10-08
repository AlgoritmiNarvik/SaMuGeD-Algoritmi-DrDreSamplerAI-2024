---
license:
- cc-by-4.0
- cc-by-nc-sa-4.0
language:
- en
tags:
- music
- midi
- symbolic-music
- repetition
- percussion
- public-domain
- metadata
- copyright
pretty_name: SaMuGeD Earworms recurring phrases (main dataset)
size_categories:
- 1M<n<10M
configs:
  - config_name: lakh_melodic
    default: true
    data_files:
      - split: all
        path: data/closed_melodic/*.parquet
  - config_name: lakh_percussion
    data_files:
      - split: all
        path: data/closed_percussion/*.parquet
  - config_name: pdmx_melodic
    data_files:
      - split: all
        path: data/pdmx_melodic/*.parquet
  - config_name: maestro_melodic
    data_files:
      - split: all
        path: data/maestro_melodic/*.parquet
  - config_name: source_terms
    data_files:
      - split: all
        path: data/source_terms/*.parquet
  - config_name: provenance_hints
    data_files:
      - split: all
        path: data/provenance_hints/*.parquet
  - config_name: work_identity
    data_files:
      - split: all
        path: data/work_identity/*.parquet
---

# SaMuGeD Earworms recurring phrases

Main dataset of the SaMuGeD Earworms release (Ostinato / Catchy musical hooks). Source verified recurring MIDI phrases with separate drum patterns.

The release has three parts. This repository holds the phrases, splits, MIDI bytes, archives and the research note. The [Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms) is the listening demo. The [listening audio repository](https://huggingface.co/datasets/AlmazErmilov/samuged-earworms-audio) only stores the rendered loops the Space player streams and is not needed to use this dataset.

[![Dataset](https://img.shields.io/badge/Hugging_Face-dataset-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases)
[![Listen](https://img.shields.io/badge/Hugging_Face-listen-ACA0E9?logo=huggingface&logoColor=000)](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms)
[![Research note](https://img.shields.io/badge/Research_note-PDF-626779)](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/paper/samuged_recurring_phrases.pdf)
[![Tests](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024/actions/workflows/research-tests.yml/badge.svg)](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024/actions/workflows/research-tests.yml)
[![Code](https://img.shields.io/badge/GitHub-code-626779?logo=github)](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSampler-2024)

## Dataset

| Release | Melodic | Percussion | Total |
| --- | ---: | ---: | ---: |
| Lakh phrases (primary) | 50,566 | 44,511 | 95,077 |
| PDMX expansion (`pdmx_melodic`) | 459,659 | | 459,659 |
| MAESTRO expansion (`maestro_melodic`) | 3,423 | | 3,423 |

| Source metadata | Lakh | MAESTRO | PDMX | Total |
| --- | ---: | ---: | ---: | ---: |
| Rows in `source_terms`, `provenance_hints` and `work_identity` | 17,232 | 1,276 | 189,704 | 208,212 |

The corpus expansion applies the same closed detector to PDMX and MAESTRO. `pdmx_melodic` holds 459,659 melodic phrases from 178,888 of the 189,704 PDMX scores and `maestro_melodic` holds 3,423 melodic phrases from 1,201 of the 1,276 MAESTRO performances. The remaining sources produced no phrase that passed the detector. Both use the phrase schema of the Lakh configurations. Artist and title come from the upstream score or performance metadata, not from file paths. Their `split` is `unassigned`, because no combined evaluation split has been made for the expanded corpora. Every PDMX batch and the MAESTRO run passed a full independent replay audit.

Rows contain note arrays, verified occurrence coordinates, source hashes and MIDI bytes. The processed Lakh MIDI Clean snapshot has 17,232 source paths, 16,995 successful parses and 237 recorded failures. The release passed complete artifact audits, with closed selection replay on a stratified 256 source sample.

```python
from datasets import load_dataset
phrases = load_dataset("AlmazErmilov/samuged-recurring-phrases", "lakh_melodic", split="all")
with open("phrase.mid", "wb") as output:
    output.write(phrases[0]["midi_bytes"])
```

`lakh_melodic` and `lakh_percussion` hold the Lakh phrases of the primary closed selection detector. Their Parquet files live in the `data/closed_melodic` and `data/closed_percussion` folders, named after the selection rule like the primary archive.

Filter the original `split` column before training. `overlap_excluded` and `duplicate_excluded` are not training or test rows. The [primary archive](archives/closed.tar.gz) includes manifests, provenance, split views, MIDI and checksums. Extract into an empty directory. Read the [consumer guide](CONSUMER_GUIDE.md).

The fixed window baseline that the research note compares against is kept for reproducibility only. It has 94,950 phrases, 50,439 melodic and 44,511 percussion, with selection replay on all successful sources. It stays available as the [reference archive](archives/reference.tar.gz) and as the Parquet folders `data/reference_melodic` and `data/reference_percussion`, but it is not a dataset configuration and the viewer does not show it.

## Source metadata and rights evidence

Three configurations hold one row for each of the 208,212 sources of Lakh, MAESTRO and PDMX. They share the columns `source_key`, `source_id`, `source_sha256` and `dataset_id`.

| Configuration | Content |
| --- | --- |
| `source_terms` | Corpus license, per score license declaration, MIDI copyright notices, declared research, sharing and commercial terms, usage conditions and their evidence |
| `provenance_hints` | Claim class, search route and hints read from existing labels, such as collection codes, dates and attribution markers |
| `work_identity` | MusicBrainz work candidates from the API lookup and three offline dump indexes (works by title, recordings by title and artist, classical works by composer and catalogue number), merged by work, with writers, ISWCs and an assessment tier |

These labels are evidence, not clearance. A corpus license or a per score declaration describes what the source states, not who owns the composition. A missing copyright notice does not mean the music is free of copyright. MusicBrainz candidates come from title and name agreement. They are unverified, they are never promoted to an accepted identity and some sources have several. Nothing in these configurations establishes composition, arrangement or performance rights. `identity_status` is `candidate_unverified` or `unresolved` and `rights_clearance` is always `not_established`. In `work_identity`, an API status of `pending` is historical. The dump indexes cover those sources instead.

Coverage of the identity layer differs by corpus. Lakh titles and artists are popular music that MusicBrainz lists well. PDMX is mostly traditional tunes transcribed from collections, which MusicBrainz rarely records as works. MAESTRO uses classical titles, which are matched through the composer and the catalogue number written in the title (opus, BWV, K., D., Hob. and similar systems). A Lakh artist written as a bare surname agrees with a single artist credit that contains it, recorded as the weaker `surname_subset` agreement. MusicBrainz lists many classical works more than once, so duplicate entries for one composer and catalogue number count as one work at the weaker tier, with the lowest work id as the representative.

| Corpus | Sources | At least one work candidate | Single candidate, full agreement | Main reason for the rest |
| --- | ---: | ---: | ---: | --- |
| Lakh | 17,232 | 83.8% | 39.9% | No MusicBrainz work with that title and artist |
| MAESTRO | 1,276 | 80.6% | 44.0% | No catalogue number in the title, or no work of the composer carries that number |
| PDMX | 189,704 | 0.5% | 0.2% | 75% are traditional collection transcriptions, 17.8% match by title only |

Every source has its corpus license and, for PDMX, its per score declaration in `source_terms`. The candidate percentages above say how many sources have a MusicBrainz work proposal, not how many are cleared.

Join phrases to their source metadata on `source_id`, which is unique across the three corpora. Byte identical files occur under several PDMX sources, so `source_sha256` can match more than one metadata row.

```python
from datasets import load_dataset
repo = "AlmazErmilov/samuged-recurring-phrases"
phrases = load_dataset(repo, "pdmx_melodic", split="all").remove_columns("midi_bytes").to_pandas()
terms = load_dataset(repo, "source_terms", split="all").to_pandas()
joined = phrases.merge(terms[["source_id", "source_sha256", "score_license_declaration", "overall_clearance_status"]],
                       on=["source_id", "source_sha256"], how="left", validate="many_to_one")
```

## Listening and rankings

The [Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworms) is a curated listening demo, not the full dataset. Browse the dataset viewer above for more MIDI phrases. Additional web MIDI examples by Tool are demo supplements outside this dataset.

Three top 50 collections cover repeated motifs, popular songs and drums. The Space adds a personal Tool listening collection, including separate web MIDI supplements. These supplements are not included in the dataset. Filter by song or part, compare the layers and follow their source note attacks. A separate ten song selection uses published recognition or earworm occurrence evidence. Five [CSV rankings](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/tree/main/analytics) are included. The original analytic popularity cohort uses an exact historical sales list match. The live Space applies a separate listening curation.

Playback loops until stopped. Download 48 kHz stereo PCM 24 bit WAV, FLAC or loop MIDI. FluidSynth with ColomboGMGS2 17.02 Vanilla renders the listening demo, preserving source notes, tempo and instrument programs. These are not commercial recording excerpts. The complete cycle can extend beyond the detector prototype. [Selection and rendering details](demo/README.md) explain the evidence and source construction.

## Limits and license

**There are no listener labels for these fragments.** Recurrence does not establish catchiness or recognition. Published familiarity evidence applies to songs only. Search limits, part selection, filename identities and duplicate arrangements affect coverage. This is not a perceptually validated benchmark. The experimental melody prior corpus is excluded.

The Lakh collection follows the upstream [Lakh CC BY 4.0 declaration](https://colinraffel.com/projects/lmd/). Cite Colin Raffel's 2016 thesis, *Learning Based Methods for Comparing Sequences, with Applications to Audio to MIDI Alignment and Matching*. Composition and arrangement attribution remains incomplete. No independent rights clearance is claimed. Code is MIT. External evaluation datasets are excluded. SoundFont and interface font licenses are included in the Space. No DOI or peer review is claimed.

## Licenses by configuration

| Configurations | License | Notes |
| --- | --- | --- |
| `lakh_*` and the reference archive | CC BY 4.0 | Lakh MIDI declaration, composition attribution incomplete |
| `pdmx_melodic` | CC BY 4.0 | PDMX corpus license, with per score Public Domain Mark or CC0 declarations kept in `source_terms` |
| `maestro_melodic` | CC BY NC SA 4.0 | MAESTRO license, noncommercial use only and adapted material shared under the same license |
| `source_terms`, `provenance_hints` and `work_identity` | CC BY 4.0 | Fields taken from MusicBrainz are CC0 1.0 |

A Public Domain Mark is a declaration by the uploader, not a CC0 dedication and not a clearance of the underlying work. The MusicBrainz metadata license covers the metadata only, not the music it describes. Cite PDMX and MAESTRO when you use their configurations.

## Authors

| Author | Contact |
| --- | --- |
| Peiyi Wu | [pewu10205@uit.no](mailto:pewu10205@uit.no) |
| Asle Fjæran Øren | [asleoren@gmail.com](mailto:asleoren@gmail.com) |
| Shayan Dadman | [shayan.dadman@uit.no](mailto:shayan.dadman@uit.no) |
| Almaz Ermilov | [almaz.ermilov@uit.no](mailto:almaz.ermilov@uit.no) |

## Citation

Copy the BibTeX below or [download the bibliography](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/CITATION.bib?download=true). [Citation metadata](CITATION.cff) is also available. This is a dataset release, not a peer reviewed article.

```bibtex
@misc{wu2026samuged,
  author = {Wu, Peiyi and Øren, Asle Fjæran and Dadman, Shayan and Ermilov, Almaz},
  title = {{SaMuGeD} Earworms (Ostinato / Catchy musical hooks)},
  year = {2026},
  version = {0.3},
  url = {https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases},
  note = {Research dataset release}
}
```

Cite the upstream corpora for the expansion configurations.

- Phillip Long, Zachary Novack, Taylor Berg-Kirkpatrick and Julian McAuley (2024). *PDMX, a large scale public domain MusicXML dataset for symbolic music processing*. [arXiv 2409.10831](https://arxiv.org/abs/2409.10831), accepted at ICASSP 2025. Dataset on [Zenodo](https://zenodo.org/records/15571083).
- Curtis Hawthorne, Andriy Stasyuk, Adam Roberts, Ian Simon, Cheng-Zhi Anna Huang, Sander Dieleman, Erich Elsen, Jesse Engel and Douglas Eck (2019). *Enabling factorized piano music modeling and generation with the MAESTRO dataset*. ICLR 2019, [arXiv 1810.12247](https://arxiv.org/abs/1810.12247). Dataset on the [Magenta site](https://magenta.tensorflow.org/datasets/maestro).

```bibtex
@inproceedings{long2025pdmx,
  author = {Long, Phillip and Novack, Zachary and Berg-Kirkpatrick, Taylor and McAuley, Julian},
  title = {{PDMX}: A Large-Scale Public Domain {MusicXML} Dataset for Symbolic Music Processing},
  booktitle = {IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)},
  year = {2025},
  url = {https://arxiv.org/abs/2409.10831}
}
@inproceedings{hawthorne2019maestro,
  author = {Hawthorne, Curtis and Stasyuk, Andriy and Roberts, Adam and Simon, Ian and Huang, Cheng-Zhi Anna and Dieleman, Sander and Elsen, Erich and Engel, Jesse and Eck, Douglas},
  title = {Enabling Factorized Piano Music Modeling and Generation with the {MAESTRO} Dataset},
  booktitle = {International Conference on Learning Representations},
  year = {2019},
  url = {https://arxiv.org/abs/1810.12247}
}
```
