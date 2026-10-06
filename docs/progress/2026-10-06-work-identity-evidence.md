## 2026-10-06: work identity candidates and phrase inheritance

Added a local work identity index with complete source queue coverage, bounded MusicBrainz lookups, a persistent core metadata cache and append only identity review decisions. Lookup failures stop the current pilot and can be resumed. A process lock prevents overlapping runs.

Phrase evidence joins current source reviews and existing corpus terms without treating an accepted identity as permission to redistribute MIDI, publish audio or reuse music. Original metadata and extraction results remain unchanged. Input hashes are checked before phrase review results are returned.

The MLC remains access required. Ownership data is not imported without enrollment and verified terms. Pilot findings are local and do not establish matching accuracy or rights clearance.
