# Pause checkpoint

Work paused at 2026-10-03 13:58:34 CEST (11:58:34 UTC) at the user's explicit request. This supersedes the earlier ten-hour continuation window. Automatic continuation `samuged-local-research-continuation` is `PAUSED`. No research computation or downstream watcher remains active. The two in-flight computations completed naturally before this checkpoint, preserving their results.

The branch is `feature/recurring-phrase-dataset`. Research code before this documentation closeout is `69f5a7d1ef1baa7cdb271de0c17d4f1379524fab`. The commit containing this document records the final documentation boundary. `git pull --ff-only` succeeded before the research branch was created from `200c4a2`. All subsequent commits are local. No push, pull request, merge, dataset publication or collaborator message occurred.

## Delivered materials

The [25-slide report](../../output/presentations/samuged_status_2026-10-03.pptx) is editable PowerPoint. A [PDF copy](../../output/pdf/samuged_status_2026-10-03.pdf) supports direct reading. [The written report](STATUS_REPORT_RU.md) preserves the narrative and evidence references in Git. The separate [six-page scientific draft](../../output/pdf/samuged_recurring_phrases.pdf) uses 132 verified input files and its adjacent input receipt. See [DELIVERY.md](DELIVERY.md) for consumer instructions and [artifact_index.md](artifact_index.md) for experiment evidence.

| Dataset | Build and artifact audit | Selection replay | Portable archive |
| --- | --- | --- | --- |
| Reference | Complete, 94,950 excerpts, all schemas pass | All 16,995 successful sources pass | `reference_v04`, archive and extracted checks pass |
| Indexed | Complete, 95,079 excerpts, all schemas pass | All 16,995 successful sources pass | Not packaged |
| Closed | Complete, 95,077 excerpts, all schemas pass | Stratified 256-source sample passes | `closed_v01`, archive and extracted checks pass |
| Melody prior | Build complete, 95,077 excerpts claimed by reconciled manifests | Not started | Not packaged, artifact audit and schema validation not started |

Every build accounts for 17,232 source paths, 16,995 successful parses and 237 recorded parse errors. Melody has 50,566 melodic and 44,511 percussion rows. Its source and phrase manifests reconcile, but this accounting is not an audit of exported MIDI or detector correctness. Reference remains the CLI default. The improved variants have controlled benefits, higher runtime and mixed external results.

## Process boundary

Completed naturally: melody build PID `53829`, indexed replay PID `77375` and its wrapper PID `54057`. Their PIDs are absent and the melody build lock is absent.

Stopped before they could launch more work: melody validation waiter PID `54143`, indexed packaging waiter PID `43250`, paper waiter PID `44456` and the agent's melody diagnostics watcher. The old preview servers on ports 8871, 8873 and 8874 were stopped. Lightweight loopback previews on ports 8872, 8875 and 8876 remain available. Port 8875 is the user's open drum review page; port 8876 serves the 64-pair reference versus closed review. These preview servers do not run research jobs.

No automation should be reactivated until the user requests continuation. Do not restart completed corpus builds or the full indexed replay merely because earlier work-log entries call them active.

## Reproducibility boundary

The indexed replay is stored in the historically named `research_local/selection_sample_indexed_v02` directory, but its actual mode is `all_successful`. Its frozen receipt and exact coverage check prove 16,995 successful source rows with no replay discrepancies. The extra binding check independently matches the replay's bound dataset files to the current files. It does not execute detection again.

The melody extraction runtime is `research_local/corpus_runner_melody_v01`; all 29 recorded files match its `RUNNER_SNAPSHOT.json`. The validation runtime is `research_local/validation_runner_v02`; all 35 recorded files match. Use these retained snapshots for the unfinished checks. The initial private melody pause inventory v01 incorrectly resolved snapshot-relative paths against the current checkout and reported three false mismatches. The corrected v02 and direct root check resolve paths against the frozen runner directory; no frozen file mismatch remains.

The paper covers the reference corpus, audited indexed and closed comparisons and the full reference selection replay. It does not incorporate the unvalidated melody corpus or claim human phrase quality. The complete test suite last ran with 566 passing tests, before these documentation and presentation changes. No detector code changed during pause closeout.

## Manual continuation

Start by reading this checkpoint, checking `git status --short`, checking live processes and verifying the relevant saved hashes. Use the local venv. Keep the automatic continuation paused unless explicitly requested.

The first unfinished validation is:

```bash
source .venv/bin/activate
bash research_local/run_full_validation_v02.sh melody
```

That frozen wrapper runs a full melody artifact audit, schema validation, diagnostics and a 256-source selection replay. It deliberately does not rerun extraction. Its replay output must remain absent before this first invocation; after an interrupted invocation inspect receipts rather than blindly rerunning into a nonempty output.

The indexed corpus can be packaged separately after verifying the completed replay:

```bash
source .venv/bin/activate
python scripts/package_dataset.py --dataset research_local/lakh_aligned_indexed_v01 --output research_local/releases/indexed_v01 --archive --screening research_local/screened_splits_indexed_v01 --selection-replay research_local/selection_sample_indexed_v02
python scripts/verify_release.py --release research_local/releases/indexed_v01 --archive research_local/releases/indexed_v01.tar.gz --output research_local/releases/indexed_v01.portable_verification_v01.json
mkdir research_local/releases/indexed_v01_extracted
tar -xzf research_local/releases/indexed_v01.tar.gz -C research_local/releases/indexed_v01_extracted
python scripts/verify_release.py --release research_local/releases/indexed_v01_extracted --extracted --output research_local/releases/indexed_v01.extracted_verification_v01.json
```

Do not use the old automatic packaging wrapper unchanged: its one-shot root-check output already exists at this checkpoint. The package, extraction directory and verification output names above are reserved only while absent.

After melody validation, complete its full comparison, duplicate screening and curation diagnostics, then consider packaging and a newly bound paper. Human phrase assessment and redistribution scope remain publication requirements. The 64-pair packet contains zero human ratings. Reusing disclosed evaluation cohorts does not create fresh heldout evidence.

## Artifact hashes

The complete machine record is [pause_checkpoint_v01.json](../../research_local/pause_checkpoint_v01.json), SHA256 `8291d531d76b1a2e5a752d7ce2c229344cb35c0c61b7d3419ca2e5dc9a3b61a6`. It also records runner snapshot hashes and retained local preview commands. Large datasets and generated reports are ignored local artifacts, so this checkout and volume must be retained along with the local commits.

| Local file | Bytes | SHA256 |
| --- | ---: | --- |
| `research_local/releases/reference_v04.tar.gz` | 181,957,781 | `76bab9daf6ad75cc952bc361ee6f2b1badf6de106c52f9b9574d11a31de676a2` |
| `research_local/releases/closed_v01.tar.gz` | 205,245,269 | `3c2fe6777a3155292baa6b35641a603681f4f32cb3cf97328838844eca5b0804` |
| `research_local/selection_sample_indexed_v02/completion_receipt.json` | 1,318 | `8b2c75f94017767d1b8da6a253b9330712ddea13a53601e4e012b0c2b09a3830` |
| `research_local/selection_all_indexed_root_check_v01.json` | 866 | `49a33589b402a7072b6670af82432ecfb5738d886174ef04ee69048ee72df01e` |
| `research_local/selection_all_indexed_binding_check_v01.json` | 1,219 | `165f1b279b9233ae306cbc5368638f1e410d2ac70156e0361567a966a0ff4ce4` |
| `research_local/lakh_aligned_melody_v01/summary.json` | 1,939 | `74b50ccd1b0bfb2f73270149360c29149145f3200a27f9cfd2d98731a761d1f0` |
| `research_local/lakh_aligned_melody_v01/sources.jsonl` | 671,278,816 | `e7a7bc1888f2522a4f61d0a596d869b374b93f53fa5e32866a46bd8bab04d1e4` |
| `research_local/lakh_aligned_melody_v01/phrases.jsonl` | 415,590,677 | `49c3e10c1768382ee468a4ee31bf5c340fefc38725171f4e93a58d4b825feb2e` |
| `research_local/melody_pause_inventory_v02.json` | 18,428 | `046c1c6189cae2098d275bbeefb6bcc9accce37b2941d08d2f2d1110bc3534f6` |
| `output/pdf/samuged_recurring_phrases.pdf` | 22,235 | `10ef7decc9ac551c51efd1c080744a58517ab0c054e2e0629ecba24dd4649eb6` |
| `output/pdf/samuged_recurring_phrases.inputs.json` | 42,193 | `aa0b4f24e3a436c57a8be3f63c6862b82ecb45d88c0dbc3cc3037dc9d14febd5` |
| `output/presentations/samuged_status_2026-10-03.pptx` | 445,394 | `ac9ae853443844e0e64392bc464746f5c21559d054942b20ec47f2810e783c56` |
| `output/pdf/samuged_status_2026-10-03.pdf` | 863,095 | `07f5858df11fb4facffadc8122075f6b2fcb63b0bdcc434dce98d0c386063afc` |
