## 2026-10-06: source copyright evidence and work license fields

Added a hash bound scan of original MIDI copyright meta events and separate composition license, rights holder and evidence fields. Unknown rights remain unknown. Every source is accounted for, including unreadable or changed files. Copyright text is not interpreted as composition clearance and lyrics are excluded.

Added source search filters for work license evidence status, copyright notice presence and indexed copyright text. Search exports include original notices and external candidate links. Existing source catalogs remain readable without a rights scan.

Tests cover exact notice provenance, hash mismatch, parse failure, full index coverage and the separation of notice text from composition license claims. Local evidence and personal outputs remain outside GitHub.
