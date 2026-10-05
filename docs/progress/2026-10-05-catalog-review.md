## 2026-10-05: catalog coverage and duplicate review

Added a read only report for metadata coverage, extraction flags and duplicate candidates across corpus builds. Byte equality and normalized arrangement equality are reported separately. Conflicting recorded evaluation splits are flagged without assigning new splits or removing sources.

Reports retain corpus conditions and the catalog hash. Examples are bounded and missing hashes do not form candidate groups. Counts describe source records rather than unique songs. Approximate similarity and perceptual quality remain separate evaluation tasks.

Validated cross corpus grouping, missing metadata, recorded split conflicts, immutable catalog contents and bounded samples. Full PDMX and MAESTRO extraction continues locally. No expansion data has been published.
