# Paper claim audit

## Resolution

The four prose corrections below have been applied to `scripts/make_paper.py`.
The README now describes extension of a verified exact repeat. The original
Lakh, Meredith and Lartillot pages were reopened to verify the source statements.
The updated draft `research_local/paper_claims_review_v01.pdf` uses the completed
all-successful reference replay, remains six pages and passes visual inspection
of the changed method and limitation pages. The findings below retain the
pre-correction wording and line locations as an audit record. Later full-build
counts will be refreshed only after their bound audits pass.

## Scope

This read-only audit reviews `scripts/make_paper.py`, the root `README.md`, the
research guide and the preferred evidence available on 2026-10-03. The
requested `docs/research/manuscript.md` does not exist. The generated prose in
`scripts/make_paper.py` is therefore the manuscript source reviewed here.

The primary reference dataset is `research_local/lakh_phrases_v03`. Its bound
audit passes with zero failures over 17,232 source records, 16,995 successful
parses, 237 recorded input errors and 94,950 exported MIDI excerpts. Its
ordinary audit did not repeat candidate generation and selection. The separate
all-successful replay at `research_local/selection_all_reference_v01` passed all
16,995 successful sources with zero failures.

## Corrections before the final paper

### Clarify simultaneous percussion strikes

**Location:** `scripts/make_paper.py:2056-2058` and `:2124-2127`.

“Preserves simultaneous kit strikes” and “preserving simultaneous
instruments” are slightly broader than the implementation. Distinct kit
pitches at one onset are retained, but an exactly duplicated onset and pitch
across tracks is merged deterministically. Matching also ignores strike gate
length and velocity, although exports preserve source velocities.

Suggested wording:

> A separate percussion detector retains distinct simultaneous kit pitches,
> merges exact same-onset and same-pitch duplicates across tracks and compares
> meter-aware onset and kit-pitch patterns without transposition. Gate length
> and velocity do not define drum-pattern identity.

This is a method-description correction. It does not change any measured
result.

### Bound the closed-selector phrase claim

**Location:** `scripts/make_paper.py:2145-2149` and the related root README
description at `README.md:27`.

“This can recover full repeated phrases” generalises from planted exact-repeat
cases to musical phrase boundaries. The controlled evidence shows recovery of
the planted full repeat under the synthetic definition. The unlabelled real
pilot shows selection changes but cannot establish that the longer boundary is
the human-preferred phrase.

Suggested wording:

> In the controlled exact-repeat cases this rule recovered planted longer
> repeats that the original selector omitted. It does not establish human
> phrase boundaries, and periodic passages can extend beyond a listener's
> preferred boundary.

The README can use “can extend a verified exact repeat” instead of “can extend
an exact repeated phrase.”

### State the novelty boundary and cite direct pattern-discovery antecedents

**Location:** method prose at `scripts/make_paper.py:1743-1783` and references
at `:2411-2420`.

The current generator makes no explicit novelty claim, which is appropriate.
It cites a comparative pattern-discovery study and MIREX but omits the direct
SIATEC, COSIATEC, SIATECCompress and multiparametric closed-pattern antecedents
already documented in `docs/research/sources.md`. The name “closed exact
selection” could otherwise be read as a claim about a standard closed-pattern
algorithm.

Suggested wording:

> This is an engineering pipeline with bounded window matching and a
> project-specific exact-extension selector. It is not presented as a new
> general pattern-discovery algorithm. SIATEC-family geometric compression and
> multiparametric closed-pattern mining are related antecedents with different
> representations and selection objectives.

Add Meredith (2013 or 2015) and Lartillot (2014) to the references if space
permits. Keep the algorithm identifier `aligned_closed`; only the prose needs
the project-specific boundary.

### Make the Lakh licence caveat explicit in the paper

**Location:** dataset statement at `scripts/make_paper.py:2071-2074`, rights
statement at `:2405-2407` and reference [1] at `:2413`.

The current rights statement is directionally correct, and the source and
research READMEs are more explicit. The six-page paper should retain the key
fact: the upstream page applies CC BY 4.0 to the distributed dataset while
also reporting inconsistent MIDI attribution. The dataset licence does not by
itself clear the underlying compositions or arrangements.

Suggested wording:

> The upstream Lakh page labels the distributed dataset CC BY 4.0 and notes
> inconsistent attribution in the underlying MIDI files. This local audit does
> not establish redistribution rights for compositions, arrangements or
> phrase excerpts. The candidate release remains unpublished pending a rights
> review.

## Status to refresh, not scientific errors

The final render should pass
`--selection-replay research_local/selection_all_reference_v01`. The currently
inspected `paper_indexed_comparison_v03.inputs.json` is bound to the older
256-source bounded replay. The all-successful replay now provides 16,995 of
16,995 passed sources and zero failures. The generator already renders the
correct distinction between the ordinary artifact audit and this separate
selection replay, so no logic change is required.

The completed `aligned_closed` full build has a summary but no `audit.json` at
this snapshot. It must not appear as an audited full-corpus comparison until
its bound zero-failure audit exists. The `aligned_melody` build is still
running and has no summary or audit. These are changing run statuses, not
scientific claim defects. The full `aligned_indexed` build has a passing
zero-failure ordinary audit and is eligible for the output-count comparison.

`docs/research/manuscript.md` is absent. If a separate manuscript is intended,
it should be generated or declared before final review. At present the exact
paper text lives in `scripts/make_paper.py`.

## Claims already supported and correctly bounded

- The title and abstract call the outputs recurring phrase candidates. They do
  not call them hooks, catchy phrases or earworms.
- Synthetic planted-case metrics are explicitly separated from real-music
  accuracy and listener quality. Real pilots are described as unlabelled.
- The certified drum result is conditioned on an independent symbolic oracle.
  The paper distinguishes 120/180 direct prototype edges from the posthoc
  60/60 family-coverage result and does not call either real-song precision.
- The local 17,232-path corpus is described as a manifest-defined snapshot,
  not a verified upstream archive or a count of unique works.
- Full-build comparison counts are labelled output and selection telemetry,
  not accuracy, and optional algorithms are not promoted as defaults.
- Page 6 correctly says that the ordinary reference audit did not replay
  candidate generation for every successful source. The supplementary replay
  text reports bounded versus all-successful scope separately.
- The root README separates the MIT software licence from rights in source
  music and says that the commands do not publish a dataset.

No current evidence supports a claim of perceptual phrase quality, catchiness,
memorability, real-corpus precision or a cleared public MIDI release.
