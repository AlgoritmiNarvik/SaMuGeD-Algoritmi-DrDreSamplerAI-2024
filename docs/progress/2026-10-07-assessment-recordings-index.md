## 2026-10-07: candidate assessment accepts the offline recordings index

`candidate_assessment` now takes a third optional candidate input, `--recordings-index`, the sidecar written by `work_identity_offline_recordings` with provider `musicbrainz_fullexport`. Lakh is resolved offline from the Postgres full export, so assessment v02 can cross check the API candidates against both dump based providers in one run. The input is attached read only, hashed into `provenance` like the others and checked by `packet`, which also refuses an index that the assessment did not record.

The binding rules are unchanged. Every full export candidate must match the source hash in the API queue and in `metadata.records`, and each provider may come from one index only. Full export evidence has the API recording shape, so title agreement, credit agreement (with initials as the weaker form) and writers are read the same way. Its recording namesake count is not used as a work namesake count; these rows take the count from `--subset` like API rows.

The provider cross check keeps its four values. With three providers it reports agreement when all work sets are equal, a difference when any pair is disjoint and an overlap otherwise. Each assessment now lists the providers that proposed its work, and `summary` counts assessments per provider. The `providers_agree` reason now reads "all providers found the same works".

Validation: five new tests cover three provider agreement, an API set disjoint from the full export set, a disjoint pair among three providers, a full export only source, provenance, binding and origin errors, the packet check and the CLI flag. The real v02 run has not been made yet.
