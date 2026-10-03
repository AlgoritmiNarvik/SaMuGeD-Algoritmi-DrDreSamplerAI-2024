# Local delivery

This page is the entry point for the local SaMuGeD delivery as observed on 2026-10-03 at 13:07 CEST. It separates finished artifacts from work that was still running. Nothing described here has been pushed or published.

## Start here

The preferred dataset is the [reference v04 release](../../research_local/releases/reference_v04). Its [dataset card](../../research_local/releases/reference_v04/DATASET_CARD.md) states the intended use and limits, while the [consumer guide](../../research_local/releases/reference_v04/CONSUMER_GUIDE.md) documents manifest joins, coordinates, splits and search-limit fields.

The portable archive is [reference_v04.tar.gz](../../research_local/releases/reference_v04.tar.gz). It is 181,957,781 bytes with SHA256 `76bab9daf6ad75cc952bc361ee6f2b1badf6de106c52f9b9574d11a31de676a2`. The saved [portable verification](../../research_local/releases/reference_v04.portable_verification_v01.json) passed all 95,009 archive members. The separately [extracted copy](../../research_local/releases/reference_v04_extracted) also passed [recipient-side verification](../../research_local/releases/reference_v04.extracted_verification_v01.json).

The release accounts for 17,232 input paths. There are 16,995 successfully parsed sources, 237 recorded parse errors, 50,439 melodic phrase candidates and 44,511 percussion candidates. All 94,950 phrase rows have MIDI excerpts. The ordinary audit verifies manifests, provenance, source reconstruction and exported MIDI semantics. The included [all-source selection replay](../../research_local/selection_all_reference_v01) separately re-extracted all 16,995 successful sources with zero discrepancies.

The completed [aligned closed corpus](../../research_local/lakh_aligned_closed_v01) is the easiest place to inspect the enhanced candidate variant now. Its full artifact audit and all 112,309 schema rows pass. Its [256 source selection replay](../../research_local/selection_sample_closed_v02) also passes with zero failures, including every one of the 28 metadata-recovered sources and balanced groups of 114 search-limited and 114 unlimited sources. Its [portable archive](../../research_local/releases/closed_v01.tar.gz) passes archive and extracted-recipient verification. The archive is 205,245,269 bytes with SHA256 `3c2fe6777a3155292baa6b35641a603681f4f32cb3cf97328838844eca5b0804`. See its [dataset card](../../research_local/releases/closed_v01/DATASET_CARD.md) and [verification report](../../research_local/releases/closed_v01.portable_verification_v01.json).

The current [six-page paper PDF](../../output/pdf/samuged_recurring_phrases.pdf) is a reviewed draft snapshot, SHA256 `53fb7151bb3903a3d9a6b17191432c27fbe9d702c3707fe0470e6c625c09285b`. It is not the final replacement because later full-corpus variants are still being checked. Its exact evidence boundary is recorded in the adjacent [input receipt](../../output/pdf/samuged_recurring_phrases.inputs.json).

## Algorithm choice

`reference` remains the command-line default and the delivered corpus method. It extracts an onset skyline independently from each melodic part, searches fixed note-count windows and verifies exact, transposed or bounded approximate recurrence. Its full corpus has both a passed artifact audit and an all-successful selection replay. This is the conservative choice for reproducible local use.

`aligned_indexed` is the optional variable-length matcher. It permits bounded insertions and deletions while retaining monotone source-note alignments, nonoverlap checks and explicit resource limits. In the frozen planted evaluation it improved occurrence F1 by 0.153941 over reference, with a 95% case-bootstrap interval of 0.096845 to 0.212337. It was slower and reached more search limits on the fixed real pilot. Three real reference matches were missed by the index even though they passed the final verifier. A bounded seed-rescue experiment recovered two exact targets without synthetic aggregate losses, but changed unlabelled real outputs and increased saturation, so it was not added to the production method.

`aligned_closed` applies a narrow selection correction over aligned candidates. It replaces a shorter selection only with a containing, source-verified, edit-free recurrence under fixed support, geometry and score rules. On 500 newly seeded synthetic cases it raised recovered positive cases from 404/423 to 420/423 and occurrence F1 from 0.831091 to 0.894309. It did not improve the reused six-song Theme Transformer or five-work JKU diagnostics. The full corpus audit, schema check and a stratified 256-source selection replay pass. This method is an improved candidate variant with documented tradeoffs and is not promoted over `reference`.

`aligned_melody` adds a small structural part-role prior without changing the recurrence score. It improved POP909 `MELODY` track-role agreement in a separate heldout role study, but track role is not phrase quality. Its reused JKU diagnostic was slightly lower on polyphonic establishment F1. The full build was still running at this checkpoint, so it is not a delivered full-corpus result.

These methods retrieve repeated symbolic structure. None predicts catchiness, listener salience, hooks or involuntary musical imagery.

The implementations are [reference extraction](../../samuged/phrases.py), [indexed alignment](../../samuged/aligned_indexed.py), [closed selection](../../samuged/closed_patterns.py), [optional part ranking](../../samuged/part_ranking.py) and [percussion extraction](../../samuged/drums.py). The saved corpus configuration remains the authority for the exact parameters used in each build.

## Separate percussion dataset

Pass `--percussion` to create percussion candidates alongside melody. Percussion is a separate detector and a separate `kind: "percussion"` dataset view. It does not use melodic skyline selection or pitch transposition. It preserves simultaneous kit strikes and distinct MIDI drum pitches, merges exact duplicate strikes across drum tracks and searches meter-aware one, two and four bar windows. Exact and bounded tolerant matching are followed by nonoverlap and diversity selection. A source can correctly produce no percussion candidate.

The reference release contains 44,511 percussion rows from 15,268 sources with percussion output. Melodic selector variants do not change percussion detection. The indexed and closed full builds each contain the same 44,511 percussion rows, although global ranks can shift when the number of melodic rows changes. The drum evaluations are symbolic tests of recorded matching rules. They do not establish perceptual quality.

## Status at the checkpoint

| Item | Status | Evidence boundary |
| --- | --- | --- |
| Reference v04 archive | Complete and portable verification passed | 95,009 archive members, including 94,950 MIDI excerpts |
| Extracted reference v04 | Complete and recipient verification passed | Metadata, checksums and 94,950 extracted MIDI excerpts |
| Reference selection replay | Complete and passed | All 16,995 successful sources, zero discrepancies |
| Full `aligned_indexed` corpus | Build, schema and ordinary audit passed | All-successful selection replay still running |
| Full `aligned_closed` corpus and archive | Build, schema, artifact audit, 256-source replay, archive and extracted checks passed | Replay is bounded, not all-successful |
| Full `aligned_melody` corpus | Build still running | No completed full-corpus audit or replay yet |
| Paper | Current six-page draft is available | Final replacement and its new receipt remain pending |
| Human review | 64-pair packet is generated, independently reconstructed and browser checked | A/B play and stop work; an actual null export used the visible fallback; no human ratings |

An ordinary dataset audit and a selection replay answer different questions. The audit checks saved manifests, source reconstruction, provenance and MIDI exports. A selection replay reruns candidate generation and final selection for its declared cohort. Do not describe an unfinished replay as passed.

## Verify and use the delivered release

Run commands from the repository root. Python commands use the local virtual environment.

```bash
source .venv/bin/activate

shasum -a 256 research_local/releases/reference_v04.tar.gz

python scripts/verify_release.py \
  --release research_local/releases/reference_v04 \
  --archive research_local/releases/reference_v04.tar.gz \
  --output research_local/releases/reference_v04.delivery-verification.json
```

The verifier requires a new output path. To test recipient extraction again, use a new empty directory:

```bash
mkdir research_local/releases/reference_v04_delivery_copy && \
  tar -xzf research_local/releases/reference_v04.tar.gz \
    -C research_local/releases/reference_v04_delivery_copy

python scripts/verify_release.py \
  --release research_local/releases/reference_v04_delivery_copy \
  --extracted \
  --output research_local/releases/reference_v04_delivery_copy.verification.json
```

The archive has no enclosing top-level directory. Do not extract it over an existing release. Read [CONSUMER_GUIDE.md](../../research_local/releases/reference_v04/CONSUMER_GUIDE.md) before treating ticks as seconds, using split labels or filtering capped sources.

## Run a new extraction

Use a new output directory. The first command reproduces the conservative algorithm choice. Invalid key-signature recovery is explicit and records repair receipts rather than changing note data.

```bash
source .venv/bin/activate

python -m samuged.cli build \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_reference_run \
  --algorithm reference \
  --workers 4 \
  --percussion \
  --recover-invalid-keys

python -m samuged.audit \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_reference_run \
  --require-full \
  --reextract

python scripts/validate_schema.py \
  --dataset research_local/my_reference_run
```

For the optional closed aligned method, change only the output and algorithm:

```bash
python -m samuged.cli build \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/my_closed_run \
  --algorithm aligned_closed \
  --workers 4 \
  --percussion \
  --recover-invalid-keys
```

Run the same audit and schema commands against `research_local/my_closed_run`. Full re-extraction is intentionally expensive. Lower worker counts when other corpus jobs are active.

## Inspect and listen to the 64-pair packet

The [full paired review packet](../../research_local/paired_review_full_closed_v01) compares the top melodic candidate from `reference` and `aligned_closed` for 64 distinct source groups. Selection did not depend on whether the two alternatives differed. It contains 62 informative pairs and two identical rendered pairs. Side placement is balanced and hidden in the interface. The adjacent `blind_mapping.json` makes this reversible software blinding, so reviewers should not open it until ratings are locked.

Serve the self-contained packet locally:

```bash
source .venv/bin/activate
python -m http.server 8765 --bind 127.0.0.1 \
  --directory research_local/paired_review_full_closed_v01
```

Open `http://127.0.0.1:8765/review.html` in a browser. Use A and B playback, record a preference or uncertainty and export the ratings JSON from the page. Playback is synthesized from source-derived note snippets and the source tempo map. It is not source audio and does not reproduce the original instruments. Only one playback runs at a time. The exported file stays on the local machine.

The recorded root browser check rendered the full packet and exercised A, B and stop. The normal download event timed out in the automated session, while the visible fallback produced a valid actual all-null export. This is a browser control check, not a human rating.

After collecting one or more nonempty exports with distinct annotator IDs, validate and summarize them into a new directory:

```bash
python scripts/analyze_paired_ratings.py \
  --packet research_local/paired_review_full_closed_v01 \
  --ratings /path/to/annotator-1.json /path/to/annotator-2.json \
  --output research_local/paired_ratings_human_v01
```

Do not use `--machine-ui-test` for human ratings. The existing all-null smoke export is a software fixture and is not listening evidence.

## Render a new paper draft

The wrapper below uses the preferred completed evaluation inputs. The two comparison datasets have passed ordinary audits, but their replay scopes remain as listed above. This command creates a new draft and input receipt. It does not replace the current PDF automatically.

```bash
source .venv/bin/activate

bash research_local/render_paper_v02.sh \
  research_local/samuged_delivery_draft.pdf \
  --selection-replay research_local/selection_all_reference_v01 \
  --comparison-dataset research_local/lakh_aligned_indexed_v01 \
  --comparison-dataset research_local/lakh_aligned_closed_v01
```

Inspect the generated PDF and its `.inputs.json` receipt before considering it a replacement for [the current draft](../../output/pdf/samuged_recurring_phrases.pdf). Do not add the unfinished melody corpus until its build, audit and declared replay are complete.

## Publication gaps

This is a local unpublished candidate. The local Lakh snapshot is byte-bound by its 17,232-row source manifest, but its original upstream archive checksum and acquisition receipt are unavailable. The repository evidence does not settle rights for source compositions, MIDI arrangements, derived excerpts or external annotation files. POP909, Theme Transformer and JKU inputs have source citations and local byte receipts with the version and licence limits listed in [publication_inputs.md](publication_inputs.md), but human review must still decide what may be redistributed. No human phrase-quality, hook, catchiness or memorability labels exist. Resolve those rights, attribution and human-validation gaps, finish the pending variant checks and generate a newly bound final paper before any public release.

For deeper provenance, see the [artifact index](artifact_index.md), [work log](WORK_LOG.md), [closed selector study](closed_patterns.md), [external selector diagnostic](selection_external.md) and [publication input audit](publication_inputs.md).
