## 2026-10-05: prepare audited corpus snapshots and metadata filters

Added local preparation of PDMX snapshots from batches that passed full source and MIDI replay. Preparation checks audit bindings, source hashes and MIDI hashes before joining the screened score metadata. Source and phrase identifiers remain unchanged. Exported MIDI files are included through hard links. Detailed alignments remain bound to their original audited batches.

The searchable metadata retains composer, original genre, group and tag strings, license declarations with evidence, tempo events, meter events and encoded instrument parts. Duplicate groups use matching bytes or normalized arrangement fingerprints as candidate evidence. Sources are not removed and folder-derived identity keys remain only in extraction provenance. Training splits are unassigned pending a global policy. Incomplete snapshots require an explicit option and retain an incomplete status.

Validated a local checkpoint covering 6,750 audited sources and 16,342 melodic phrases. Its derived catalog occupies about 40 MiB. The full 189,704 source extraction continues in a pinned runtime. These changes do not replace the public dataset or Space. Snapshot preparation and catalog construction do not publish data or establish composition rights.
