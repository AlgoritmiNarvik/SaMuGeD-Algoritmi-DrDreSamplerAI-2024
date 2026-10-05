## 2026-10-05: add catalog filters and result export

Added bounded read-only catalog search and category inspection commands. Filters cover title or artist text, corpus, phrase kind, encoded instrument family, source annotations, beat duration, recurrence counts, parser warnings and recorded search limits. Results distinguish corpus license, score declarations and rights evidence. Sorting uses recurrence, duration, density, detector score or title. Genre strings remain original source labels.

JSON and CSV export refuse existing files. CSV exports escape spreadsheet formulas while the catalog and JSON retain the original labels. Queries use bound parameters and fixed sort expressions, with result bounds and a query time budget. Tested literal wildcard searches, injection-shaped labels, read-only access, numeric bounds, rights uncertainty and export preservation.

Verified the commands against the local audited PDMX checkpoint, including a 50 phrase classical recurrence query. Full PDMX extraction and its completion step continue in pinned runtimes. The full MAESTRO corpus also started locally on one worker, using existing MIDI assets. No expanded corpus is published by these commands.
