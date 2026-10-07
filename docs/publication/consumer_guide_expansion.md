## Corpus expansion configurations

This section belongs at the end of the published `CONSUMER_GUIDE.md`. It describes the five configurations added by the corpus expansion.

### Phrase configurations

`pdmx_melodic` (459,659 rows from 189,704 PDMX scores) and `maestro_melodic` (3,423 rows from 1,276 MAESTRO performances) use exactly the schema of `closed_melodic`. Ticks, occurrence coordinates, note arrays and `midi_bytes` have the same meaning. Three columns differ in origin.

| Column | Expansion meaning |
| --- | --- |
| `artist`, `title` | Upstream score or performance metadata from the combined catalog, not the file path. MAESTRO rows often have no artist, the composer is in `source_terms.composer` |
| `split` | Always `unassigned`. No evaluation split exists for the expanded corpora. Batch split labels from extraction are bookkeeping only |
| `split_group` | The catalog split group, or the catalog source key when none is assigned |

Every PDMX batch and the MAESTRO run passed a full independent replay audit. The builder checked each `midi_bytes` value against `midi_sha256` and each phrase against its catalog source path, source hash and phrase row.

### Source metadata configurations

`source_terms`, `provenance_hints` and `work_identity` each hold one row for every one of the 208,212 catalog sources (Lakh 17,232, MAESTRO 1,276, PDMX 189,704). `source_key` is unique in each configuration and the three key sets are identical.

| Join | Use |
| --- | --- |
| `source_id` | Phrase row to metadata row. Unique across the three corpora |
| `source_key` | Metadata row to metadata row. Catalog key of a source within its corpus build |
| `source_sha256` | Original file bytes. Not unique, byte identical files occur under several PDMX sources |
| `dataset_id` | `lakh`, `pdmx` or `maestro` |

Lists and objects are stored as JSON text in columns ending in `_json`. Decode them with `json.loads`.

### Status columns

| Column | Values and meaning |
| --- | --- |
| `source_terms.research_terms_status`, `redistribution_terms_status`, `commercial_terms_status` | `conditional_declared` when the declared source terms permit the use under conditions, `restricted_declared` when they restrict it, `unresolved` when terms or score evidence are missing or conflicting |
| `source_terms.overall_clearance_status` | Always `not_established` |
| `source_terms.copyright_notice_status` | `present_unverified`, `absent` or `unavailable`. The notice scope is not established |
| `provenance_hints.claim_class`, `search_route` | What existing labels suggest about the source and which identity search fits it. Hints, not findings |
| `work_identity.api_status` | MusicBrainz API lookup status: `candidate`, `no_candidate`, `missing_labels` or `pending` |
| `work_identity.dump_works_status` | Offline work lookup: `candidate`, `no_candidate`, `no_namesake`, `title_only_candidates` or `missing_labels` |
| `work_identity.dump_recordings_status`, `dump_recordings_reason` | Offline recording lookup for Lakh rows, null for PDMX and MAESTRO |
| `work_identity.best_tier` | Assessment tier of the source: `conflict`, `single_work_full_agreement`, `single_work_weaker_agreement` or `multiple_works`, null when no candidate was assessed |
| `work_identity.identity_status` | `candidate_unverified` when at least one candidate exists, otherwise `unresolved` |

`pending` API rows are historical. The API lookup stopped before reaching them and the two offline dump indexes cover those sources instead. Read the dump statuses for those rows.

Each entry of `candidates_json` names one MusicBrainz work with its title, ISWCs, the providers that found it (`musicbrainz` for the API, `musicbrainz_json_dump` for dump works, `musicbrainz_fullexport` for dump recordings), writers, its assessment tier and the strongest title and creator agreement recorded. A candidate is a title and name agreement. It is not a verified identity and it says nothing about who owns the work.

### What the metadata does not establish

Labels are evidence, not clearance. A corpus license, a per score Public Domain Mark or CC0 declaration, an absent copyright notice or a MusicBrainz candidate does not establish rights in the composition, arrangement or performance. Every row keeps `rights_clearance` at `not_established`. MAESTRO material is CC BY NC SA 4.0 and excludes commercial use. MusicBrainz fields are CC0 1.0, which covers the metadata only.

`evidence/expansion_build_receipt.json` records input hashes, row counts and licenses for each configuration. `evidence/expansion_inventory.json` lists the bytes and SHA-256 of every expansion file.
