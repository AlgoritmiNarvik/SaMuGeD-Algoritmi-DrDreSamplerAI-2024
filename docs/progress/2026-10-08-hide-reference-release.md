# 2026-10-08 hide the fixed window reference from the dataset configurations

The fixed window reference selection (`reference_v04`) is the baseline the research note compares the closed detector against. On the hub it appeared as two of nine dataset configurations and as a second row in the headline table, so a reader saw two similar Lakh releases without a clear reason to pick one. Its percussion rows are identical to the closed release because both use the same drum detector.

The card no longer declares `reference_melodic` and `reference_percussion` as configurations, so the viewer shows only the closed release, the corpus expansion and the metadata configurations. The headline table lists the closed release and the expansion. One paragraph keeps the baseline for reproducibility, with its counts, the reference archive link and the Parquet folder names. The root README and the delivery note say the same.

Nothing is deleted on the hub. The reference archive and the `data/reference_*` Parquet files stay in place, so the links in the research note PDF keep working. The size category stays `1M<n<10M`, because the declared configurations still hold 1,182,795 rows.
