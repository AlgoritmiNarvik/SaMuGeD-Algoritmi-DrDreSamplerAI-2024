## 2026-10-03: recurring phrase research pipeline

Added an independent local MIDI research pipeline for melodic recurrence and percussion patterns. Source timing, tempo and meter changes are preserved, RIFF MIDI wrappers are supported and exported clips have explicit source provenance. Existing desktop, web and Windows work remains outside this change.

Added deterministic synthetic experiments, unchanged legacy comparisons, corpus accounting, grouped splits, output integrity audits and an offline review packet. Recurrence rankings are described as engineering heuristics; human memorability and real-corpus phrase quality are not established.

The completed reference run accounts for all 17,232 local source files and exports 50,439 melodic and 44,511 percussion candidates. Independent source and MIDI checks pass all 94,950 exports, and all 112,182 manifest rows pass schemas. A reproducible local archive includes separate family views, a dataset card and the supplementary duplicate screening view. The concise PDF uses verified experiment receipts and remains a local research draft.

Optional note alignment and closed exact selection improve controlled motif recovery while retaining documented tradeoffs. Full aligned variants are still being calculated from immutable runtime snapshots. An offline review packet and ratings analyzer support later independent human assessment; no human labels have been collected. Measured results and pending work are maintained in docs/research/WORK_LOG.md. No remote publication or push is authorized.
