# Selection replay evidence in the paper

`scripts/make_paper.py` accepts an optional `--selection-replay` directory for the primary dataset. The replay is supplementary evidence about deterministic extraction consistency. It does not change the primary dataset audit and does not apply to optional comparison datasets.

## Validation

The paper generator calls `scripts.package_dataset._selection_replay_binding` rather than maintaining a second semantic validator. A replay is accepted only when it has a valid completion receipt and is bound to the primary dataset's exact run key, detector configuration, audit, source manifest, phrase manifest, build configuration and summary.

The shared validator checks the frozen cohort, every selected source record, raw case coverage, passed status, zero failures and the distinction between `bounded_sample` and `all_successful`. The paper generator then records every portable replay artifact from the shared verifier's exact file set. Each file's path, byte count and SHA256 are stored in the paper input receipt. The complete replay binding and file hashes are checked again after PDF rendering and immediately before the input receipt is written.

Current generator files are not substituted for the replay's frozen source snapshot. The replay carries its own executable source and dependency evidence.

## Page 6 wording

The primary audit scope remains explicit. When `audit.json.reextraction_required` is false, the paper states that the primary audit did not repeat candidate generation and selection for every successful source. When it is true, the paper states that every successful source was re-extracted and its selected output and detector evidence were compared.

A supplementary replay paragraph reports:

* selected source count
* passed count and failure count
* whether the cohort contains every successful source or is bounded
* successful and error source counts from the full manifest

For example, the completed 256 source reference sample would be described as 256 selected and 256 passed from a bounded cohort of 16,995 successful sources, with 237 error sources in the 17,232 source manifest. An all successful replay is described only when the shared validator proves that its selected IDs equal every successful source ID. Neither scope supports a musical quality claim.

## Command

```bash
source .venv/bin/activate
python scripts/make_paper.py \
  --dataset research_local/lakh_phrases_v03 \
  --selection-replay research_local/selection_sample_reference_v02 \
  [the existing evaluation arguments] \
  --output research_local/paper_with_selection_replay.pdf
```

Use a new output path. The root paper workflow remains responsible for final rendering and visual inspection.
