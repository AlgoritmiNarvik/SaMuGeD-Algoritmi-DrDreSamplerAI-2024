# Full corpus comparison evidence in the paper

`scripts/make_paper.py` accepts up to three repeatable
`--comparison-dataset PATH` arguments. Each path must be a completed full corpus
build with a passing zero failure audit. The option is empty by default, so
existing paper commands and receipts remain valid.

A comparison command can add audited variants as follows:

```bash
source .venv/bin/activate
python scripts/make_paper.py \
  --dataset research_local/lakh_phrases_v03 \
  --comparison-dataset research_local/lakh_aligned_indexed_v01 \
  --comparison-dataset research_local/lakh_aligned_closed_v01 \
  --comparison-dataset research_local/lakh_aligned_melody_v01 \
  ... \
  --output research_local/paper_full_comparison_draft.pdf
```

The primary and comparison algorithms must be distinct. The validator requires
all builds to cover the same exact source IDs, paths, byte hashes and terminal
statuses. The global invalid key recovery setting and every source repair
receipt must also agree. This prevents a parser policy or corpus change from
being presented as an algorithm comparison.

For each build, the generator scans every nonempty JSONL row in
`sources.jsonl` and `phrases.jsonl`. It independently recomputes source status
and outcome counts, melodic and percussion candidate counts, sources with each
kind of output and melodic and percussion limit counts. These values must match
the bound summary. Blank final lines and CRLF input do not affect the recount.
The manifests are hashed before and after the scan.

The paper table reports melodic and percussion outputs, successfully parsed
files, no match files, melodic search and shortlist limits and percussion
limits. Differences are output and selection telemetry. They do not measure
accuracy or justify promoting an optional algorithm as the default.

The optional `aligned_melody` method uses indexed aligned generation, a fixed
structural part prior and closed exact selection. The prior combines onset
monophony with weight 0.65 and voice independence with weight 0.35. Its
selection score is:

`recurrence score + 0.08 * (part prior - 0.5)`

The original recurrence score remains unchanged. The adjusted score is retained
separately as selection evidence. This prior was selected for POP909 MELODY
part agreement and is not evidence of phrase quality on Lakh MIDI.

The PDF input receipt records every comparison audit, build configuration,
summary, source manifest and phrase manifest. It also records each algorithm,
run key, four audit bindings, independently recomputed counts and hashes of the
source identity and metadata repair records. The generator rechecks all primary
and comparison bindings after PDF rendering and again after input hashes are
collected, before writing the receipt.

No comparison draft is generated until the intended full variant has its own
passing audit. The root paper workflow controls review and promotion of the
final PDF.
