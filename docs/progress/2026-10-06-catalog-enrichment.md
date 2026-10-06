## 2026-10-06: indexed source metadata and external candidate links

Added a separate FTS5 source metadata index with corpus and score license evidence, original labels and global file or arrangement candidate groups. The extraction catalog remains unchanged. Evaluation splits stay unassigned and candidates do not establish composition identity or rights clearance.

The local index covers 208,212 sources. A bounded MusicBrainz core metadata pilot queried 20 Lakh records and retained 68 recording candidates. External records retain their own evidence and license and cannot overwrite source identity or rights.

Added tests for transitive grouping, rights separation, transactional imports, ambiguous external recordings, service failure handling and bounded queries. Refreshed corpus documentation and license review date. Personal outputs and data remain local.
