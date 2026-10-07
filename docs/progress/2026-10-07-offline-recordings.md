## 2026-10-07: offline recording candidates from the MusicBrainz full export

Added two sidecar layers that resolve the Lakh recording queue without the one request per second API. `musicbrainz_fullexport` verifies `mbdump.tar.bz2` against the published checksum list before reading it, records the signature status and streams nine Postgres COPY tables in one pass. It keeps the recordings whose normalized titles occur among the Lakh queue rows, prunes credits, work relations, works and creator relations in SQL to what those recordings reach and counts recording namesakes across the whole database. `work_identity_offline_recordings` applies the API recording rule (normalized title, full credit agreement by tokens or initials, performance works, agreeing writers) to every Lakh row and records a reason for every source without a candidate.

Neither layer writes to the work index or the API index, promotes a candidate to a verified identity or treats a work relation as rights clearance. Matching recordings are capped at 50 per source and works at 20 per recording, and every cap is flagged and counted.

A peek at the first lines of the 2026-10-07 export showed schema sequence 31 and a `link_type` layout with the entity types before the name, so the name is read from the seventh column. The other eight tables match the expected column counts.

Validation: 17 new tests on a small bzip2 fixture cover verification, member order, escapes, pruning, namesake counts, every status and reason, both caps, export and an unchanged work index. The real build has not been run yet.
