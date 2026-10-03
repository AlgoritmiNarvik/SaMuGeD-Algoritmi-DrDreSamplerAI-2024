# Publication input checklist

## Citation corrections applied

The paper generator and `sources.md` now include Raffel's requested thesis,
the formal Theme Transformer paper, the POP909 ISMIR paper and the Collins
JKU-PDD dataset attribution. The source statements were checked against the
publisher pages. The table and findings below preserve the pre-correction
audit state. The missing acquisition/version and rights evidence remain
unresolved; adding citations does not supply them.

## Scope

This checklist audits citation, identity receipts and declared use for the four
external datasets used by the current research. It reviews the root README,
`docs/research/sources.md`, the reference v03 dataset card and local receipts.
It does not decide whether any musical content may be published.

The release card concerns the Lakh-derived candidate dataset. POP909, Theme
Transformer and JKU are evaluation inputs and are not described as release
payloads. They still need complete attribution in a paper that reports their
results.

## Checklist

| Input | Source citation | Version or byte identity | Download receipt | Use scope | Publication documentation status |
| --- | --- | --- | --- | --- | --- |
| Lakh MIDI Clean | Partial | Local snapshot ready; upstream archive identity unavailable | Missing original archive receipt | Primary extraction corpus | Add the requested thesis citation and retain the rights decision gate |
| POP909 role cohort | Ready | Ready at commit `d83e6edb…` with 180 per-file hashes | Ready | 60 development and 120 heldout part-role cases | Keep the full Wang et al. citation with the pinned repository evidence |
| Theme Transformer annotations | Partial | Six archive hashes are ready; no immutable publisher version is recorded | Ready for the six downloaded archives | Six-song note-domain theme diagnostic with three annotators | Add the Shih et al. paper citation; archive terms and publication use need human review |
| JKU Patterns Development Database | Partial | `JKUPDD-noAudio-Aug2013` archive hash is ready | Ready except download time | Five-work classical development diagnostic and published metric check | Add the Collins dataset attribution; no licence record was found locally |

“Ready” means the local evidence supports reproducible attribution or byte
identity. It is not a rights or publication approval.

## Lakh MIDI Clean

The official [Lakh MIDI Dataset v0.1 page](https://colinraffel.com/projects/lmd/)
defines the Clean subset, applies CC BY 4.0 to the distributed dataset and asks
users to cite both the page and Colin Raffel's 2016 thesis. The current paper
reference lists the page but not the requested thesis as a separate reference:

> Colin Raffel. *Learning-Based Methods for Comparing Sequences, with
> Applications to Audio-to-MIDI Alignment and Matching*. PhD thesis, 2016.

The local directory has no original archive checksum or acquisition receipt.
Its README contains only the heading “Lakh MIDI Dataset Clean.” A bundled
GPLv3 text does not identify its provenance or which files it was intended to
cover, while the official publisher page states CC BY 4.0. This mismatch
should be treated as unresolved documentation rather than interpreted as a
licence conclusion.

The processed snapshot is nevertheless identified locally by all 17,232
source rows and source manifest SHA256
`062691ad29739cd58bdfb8c55258d63d72868d3ee3e4c30badeceaa917c8c76f`.
The reference v03 audit binds that manifest, the build configuration and
94,950 phrase rows. This establishes the exact local input set used by the
study, not its identity with an upstream Clean archive.

The reference v03 dataset card correctly says that the local release is
unpublished, that original full-song MIDIs are not bundled and that a separate
human rights review remains necessary. Preserve those statements for any
candidate release.

## POP909

The [official POP909 repository](https://github.com/music-x-lab/POP909-Dataset)
asks users to cite:

> Ziyu Wang, Ke Chen, Junyan Jiang, Yiyi Zhang, Maoran Xu, Shuqi Dai, Guxian
> Bin and Gus Xia. “POP909: A Pop-song Dataset for Music Arrangement
> Generation.” Proceedings of ISMIR, 2020.

The 180-song part-role cohort is well identified. Its URLs are pinned to commit
`d83e6edba6872a704f5d3b8b32f5cb540088dae6`, and its source manifest contains
per-file byte counts, SHA256 values, parser metadata and the `MELODY`, `BRIDGE`
and `PIANO` source roles. The download receipt SHA256 is
`66d8900ae247eaec76dc6a6c164fa7fdfb8dc01c0052cb150398dc24a77e083e`.

The scope is also clear: 60 songs selected the structural part prior and 120
were held out for official part-role agreement. These role labels do not label
phrase quality or hooks.

The six POP909 files used to compare Theme Transformer timing have per-file
hashes in a separate receipt, but their recorded URLs point to the mutable
`master` branch. That receipt remains adequate for the bytes already used, but
it is not an immutable upstream version reference. Cite the POP909 paper and
do not imply that this six-file receipt identifies a repository commit.

## Theme Transformer

The official [theme retrieval page](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html)
documents three annotators and six POP909 songs. The official implementation
repository supplies the formal citation:

> Yi-Jen Shih, Shih-Lun Wu, Frank Zalkow, Meinard Müller and Yi-Hsuan Yang.
> “Theme Transformer: Symbolic Music Generation with Theme-Conditioned
> Transformer.” *IEEE Transactions on Multimedia*, 2022.

The six archive URLs, archive SHA256 values, byte counts and members are stored
in `research_local/external/theme_transformer/download_receipts.json`, whose
SHA256 is
`d19f5d8814f15e0177c6a16b989dcb9a6cdd9d012e279a9526d2217d8b970868`.
The input audit binds that receipt and separately binds the six official
POP909 source files. The publisher archives do not expose an immutable release
tag or version in the receipt. Byte identity is reproducible, while publisher
version identity is not.

The use scope is documented correctly. The local evaluation uses the common
annotation note universe, scores three annotators separately and does not claim
to reproduce the authors' beat-domain F1. The six songs are a reused
development diagnostic, not a corpus-wide estimate.

The repository MIT licence visibly covers the implementation repository. The
local evidence does not separately record terms for the downloaded annotation
archives or their underlying songs. A human publication review should decide
what annotation data, musical examples or only aggregate measurements can be
distributed.

## JKU Patterns Development Database

The local archive is explicitly `JKUPDD-noAudio-Aug2013`. Its receipt records
the publisher URL, 35,017,995 bytes and SHA256
`9f5e1e1d225b8b9236c8d565ef643d855770ed30c05adece7b62664e453f9ee5`.
The extracted README identifies Tom Collins, August 2013 and the MIREX
Discovery of Repeated Themes and Sections development purpose. A suitable
dataset attribution is:

> Tom Collins. *JKU Patterns Development Database*. 2013.

The current sources document cites the MIREX task and describes JKU, but it
does not list this dataset attribution separately. The local receipt also has
no download timestamp and neither the receipt nor extracted README states a
licence. The publisher directory confirms the named August 2013 no-audio
archive, but does not add licence terms.

The experimental scope is clear and appropriately narrow: five classical
works are used as a development diagnostic, and the bundled seven example
outputs verify the metric adapter. The results are not described as an
official MIREX submission or popular-music accuracy.

## Actions before manuscript or dataset publication

- Add the Lakh thesis, the full POP909 paper, the Theme Transformer paper and
  the Collins JKU-PDD attribution to the manuscript bibliography.
- Keep the immutable POP909 commit and all local receipt hashes in the
  supplementary provenance table. Label the six older POP909 `master` URLs as
  hash-bound but not commit-bound.
- State that no upstream Clean archive checksum is available for the local
  Lakh directory. Use the source manifest hash as the study snapshot identity.
- Do not use the unexplained local Lakh GPLv3 file as evidence that musical
  redistribution has been cleared.
- Record a human decision for source MIDI, derived excerpts, Theme Transformer
  annotation files and JKU files separately. Code licences do not settle the
  status of musical or annotation content.
- Keep the external datasets out of the Lakh candidate release unless a later
  package explicitly lists them, their receipts and the accepted distribution
  terms.
- Preserve the current statement that no human phrase-quality, hook or earworm
  labels exist for the Lakh collection.

The current evidence is sufficient to reproduce which bytes were analysed for
all four inputs. It is not sufficient to declare a public musical dataset or
its external evaluation files eligible for redistribution.
