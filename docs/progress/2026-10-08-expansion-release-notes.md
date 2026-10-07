## 2026-10-08: corpus expansion published to the main dataset

The corpus expansion is live in `AlmazErmilov/samuged-recurring-phrases` (hub commit `173c2d81`). The upload added 30 files and about 249 MB in add or replace mode. The four Lakh configurations, both archives, the paper and the citation files were not touched. The card and the consumer guide were replaced in the same commit, so the viewer lists all nine configurations at once.

The published numbers are 459,659 PDMX phrases from 178,888 of the 189,704 scores and 3,423 MAESTRO phrases from 1,201 of the 1,276 performances, plus 208,212 rows in each of `source_terms`, `provenance_hints` and `work_identity`. The metadata rests on candidate assessment v02, which for the first time cross checks three providers (API, dump works, dump recordings) and covers 14,618 sources, and on the merged work identity export v06. Every row keeps `rights_clearance` at `not_established`. All 919 tests pass on main.

This entry corrects the card and the expansion guide where they said the phrases came from every score or performance. The remaining sources produced no phrase that passed the detector. The size category of the card moves to `1M<n<10M`, because the configurations together hold about 1.28 million rows.
