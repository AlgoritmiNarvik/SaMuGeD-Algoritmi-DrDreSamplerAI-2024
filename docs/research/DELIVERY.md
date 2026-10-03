# Research status and publication

This page separates the current publication from the research pause recorded on 2026-10-03. The pause checkpoint remains an archival record of the stopped computations, saved hashes and continuation commands. The public dataset and demo below were published on 3 October 2026.

The dataset is [Hugging Face: `AlmazErmilov/samuged-recurring-phrases`](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases). The demo is [Hugging Face Space: `AlmazErmilov/samuged-earworm-loops`](https://huggingface.co/spaces/AlmazErmilov/samuged-earworm-loops). The demo uses real source loop cycles and a separate song-level evidence view for familiar-hook selection. These views provide algorithmic evidence and contain no listener labels.

The bounded top-50 analytics remain an algorithmic recurrence result. Listener ratings were excluded from the current scope and are not a release gate. The local recurrence atlas and its ignored generated files remain documented in [top50_analytics.md](top50_analytics.md) for the local checkout.

## Published release

The public archives retain the original musical payloads and update the presentation metadata. Primary archive SHA256 is `52157d9f94a754eb3987a735591ecfead2646f12783ee0c8c7b0a5f235fcf1cb`. Reference archive SHA256 is `f4c896b2c0d58cf52eb95ae650e3ddedc005e0259e0d666995481ae24dd4809c`. Both public archives passed portable verification. The public PDF was regenerated with 132 matching input hashes. [Read the PDF](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/paper/samuged_recurring_phrases.pdf).

Dataset commit is `257d12889d44f3ecfcb8a6db73cf89d6b2b8d477`. Space commit is `a63f0e01dbc15cfb1de9deebd28b9d29abafb6bb`. The [publication guide](../publication/README.md) explains preparation and rendering.

## Historical local packages

The conservative audited package is `reference_v04` under `research_local/releases/reference_v04` in the full checkout. Its local dataset card states the intended use and limits, while its local consumer guide documents manifest joins, coordinates, splits and search-limit fields.

The local `reference_v04.tar.gz` archive is 181,957,781 bytes with SHA256 `76bab9daf6ad75cc952bc361ee6f2b1badf6de106c52f9b9574d11a31de676a2`. Its saved portable verification passed all 95,009 archive members. The separately extracted copy also passed recipient-side verification. These files are local archival artifacts until a public release is confirmed.

The reference release accounts for 17,232 input paths. There are 16,995 successfully parsed sources, 237 recorded parse errors, 50,439 melodic phrase candidates and 44,511 percussion candidates. All 94,950 phrase rows have MIDI excerpts. The ordinary audit verifies manifests, provenance, source reconstruction and exported MIDI semantics. The local all-source selection replay separately re-extracted all 16,995 successful sources with zero discrepancies.

The primary release is the completed `aligned_closed` corpus at `research_local/lakh_aligned_closed_v01`. Its full artifact audit and all 112,309 schema rows pass. Its 256-source selection replay also passes with zero failures, including all 28 metadata-recovered sources and balanced groups of 114 search-limited and 114 unlimited sources. Its local `closed_v01` archive passes archive and extracted-recipient verification. The archive is 205,245,269 bytes with SHA256 `3c2fe6777a3155292baa6b35641a603681f4f32cb3cf97328838844eca5b0804`. It contains 95,077 phrase rows: 50,566 melodic and 44,511 percussion. The dataset card and verification report remain local artifacts until publication is confirmed.

The archived six page paper PDF is the reviewed pause snapshot, SHA256 `10ef7decc9ac551c51efd1c080744a58517ab0c054e2e0629ecba24dd4649eb6`. It includes the reference corpus, the audited indexed and closed comparisons and the complete reference selection replay. All 132 input paths and hashes match the adjacent input receipt, SHA256 `aa0b4f24e3a436c57a8be3f63c6862b82ecb45d88c0dbc3cc3037dc9d14febd5`. The unvalidated melody corpus is outside this paper's evidence boundary. This remains a local scientific draft without human phrase-quality labels.

## Algorithm choice

`reference` remains the command-line default and the delivered corpus method. It extracts an onset skyline independently from each melodic part, searches fixed note-count windows and verifies exact, transposed or bounded approximate recurrence. Its full corpus has both a passed artifact audit and an all-successful selection replay. This is the conservative choice for reproducible local use.

`aligned_indexed` is the optional variable-length matcher. It permits bounded insertions and deletions while retaining monotone source-note alignments, nonoverlap checks and explicit resource limits. In the frozen planted evaluation it improved occurrence F1 by 0.153941 over reference, with a 95% case-bootstrap interval of 0.096845 to 0.212337. It was slower and reached more search limits on the fixed real pilot. Three real reference matches were missed by the index even though they passed the final verifier. A bounded seed-rescue experiment recovered two exact targets without synthetic aggregate losses, but changed unlabelled real outputs and increased saturation, so it was not added to the production method.

`aligned_closed` applies a narrow selection correction over aligned candidates. It replaces a shorter selection only with a containing, source-verified, edit-free recurrence under fixed support, geometry and score rules. On 500 newly seeded synthetic cases it raised recovered positive cases from 404/423 to 420/423 and occurrence F1 from 0.831091 to 0.894309. It did not improve the reused six-song Theme Transformer or five-work JKU diagnostics. The full corpus audit, schema check and a stratified 256-source selection replay pass. This method is an improved candidate variant with documented tradeoffs and is not promoted over `reference`.

`aligned_melody` adds a small structural part-role prior without changing the recurrence score. It improved POP909 `MELODY` track-role agreement in a separate heldout role study, but track role is not phrase quality. Its reused JKU diagnostic was slightly lower on polyphonic establishment F1. The full build completed with 95,077 phrase rows. Manifests reconcile, but its full artifact audit, schema validation and selection replay have not started, so it is not a validated dataset delivery.

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
| Full `aligned_indexed` corpus | Build, schema, ordinary audit and all-successful selection replay passed | All 16,995 successful sources replayed with zero discrepancies; no release archive yet |
| Full `aligned_closed` corpus and archive | Build, schema, artifact audit, 256-source replay, archive and extracted checks passed | Replay is bounded, not all-successful |
| Full `aligned_melody` corpus | Build complete, manifest accounting checked | 95,077 rows; full artifact audit, schema validation and replay not started |
| Paper | Updated six-page pause draft and receipt available | All 132 inputs verified; excludes the unvalidated melody corpus |
| Report and continuation | 25-slide presentation and PDF, short written report and pause checkpoint | Automatic continuation paused, no active research jobs |
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

The archive has no enclosing top-level directory. Do not extract it over an existing release. Read the local `CONSUMER_GUIDE.md` inside `research_local/releases/reference_v04` before treating ticks as seconds, using split labels or filtering capped sources.

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

The local full paired review packet in `research_local/paired_review_full_closed_v01` compares the top melodic candidate from `reference` and `aligned_closed` for 64 distinct source groups. Selection did not depend on whether the two alternatives differed. It contains 62 informative pairs and two identical rendered pairs. Side placement is balanced and hidden in the interface. The adjacent `blind_mapping.json` makes this reversible software blinding, so reviewers should not open it until ratings are locked. This packet is an optional inspection aid and has no listener labels.

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

Inspect the generated PDF and its `.inputs.json` receipt before considering it a replacement for the current local draft. Do not add the unfinished melody corpus until its build, audit and declared replay are complete.

## Publication boundary

The publication plan is algorithmic. No human phrase-quality, hook, catchiness or memorability labels exist, and listener ratings are not required for this release. POP909, Theme Transformer and JKU are evaluation-only inputs. The public package includes results and citations, not those external datasets.

The local Lakh snapshot is byte-bound by its 17,232-row source manifest, but its original upstream archive checksum and acquisition receipt are unavailable. The repository evidence does not settle rights for source compositions, MIDI arrangements or derived excerpts. The public documentation must retain the CC BY 4.0 attribution, the requested Lakh page and thesis citations and the statement that no independent clearance claim is made. See [publication_inputs.md](publication_inputs.md) for the detailed historical evidence boundary.

The dataset and demo were published on 3 October 2026. The research pause and its unfinished variant checks remain archival facts and do not imply that listener ratings are a current publication requirement.

For deeper provenance, see the [artifact index](artifact_index.md), [work log](WORK_LOG.md), [closed selector study](closed_patterns.md), [external selector diagnostic](selection_external.md) and [publication input audit](publication_inputs.md).
