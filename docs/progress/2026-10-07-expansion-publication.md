## 2026-10-07: corpus expansion publication builder

The public dataset can now grow with the PDMX and MAESTRO phrases and a per source metadata layer. `samuged/work_identity_merge.py` writes the planned v06 export, one row per source that merges the API, dump works and dump recordings candidates by work id with assessment tiers. `samuged/expansion_publication.py` builds `pdmx_melodic`, `maestro_melodic`, `source_terms`, `provenance_hints` and `work_identity` as sharded Parquet with a receipt, an inventory and a `verify` command. Nothing is uploaded by these commands.

The phrase schema moved to `samuged/publication_schema.py` and is shared with the Lakh builder, so all phrase configurations concatenate without casting. Phrases are bound to the combined catalog through the catalog key of build id and source id, and artist and title come from upstream metadata. Metadata configurations carry `source_id` as the exact join key, because `source_sha256` repeats across byte identical PDMX sources.

The dataset card gains the five configurations, a licenses table, a rights evidence section and PDMX and MAESTRO citations. `scripts/publish_huggingface.py` has a `--dataset-only` mode that adds or replaces files without deleting others. Full runs over the real data remain for the lead after review.
