## 2026-10-06: source label audit and work search hints

Added a per source audit that preserves original labels, joins selected PDMX rows by full MIDI path and records title quality, creator roles and unresolved rights gaps. Named artist fields can provide additional search hints without becoming verified composers. Generic attribution, suspected encoding damage and identifier only titles remain visible for review.

Work lookup now compares creator word order, initials, accents and apostrophes as candidate evidence. Search and phrase results include the source audit. Changed labels cannot silently replace reviewed identities or rights observations. Audit inputs and outputs remain content bound, and expansion data stays local.

Exact MIDI byte copies can supply explicitly unverified creator hints. Conflicting labels remain unresolved. Added gap filters, MusicBrainz alias lookup and bounded service backoff. No identity or reuse permission is inferred from duplicate hashes.
