# Artifact index

This index records the local evidence boundary observed on 2026-10-03. It separates the recovered reference corpus, completed receipt backed experiments, diagnostic studies and unfinished builds. Hashes below were recomputed from the files in this checkout. The index is an overview and does not replace the detailed study notes or the machine readable receipts.

## Preferred corpus and release

The preferred local corpus is [`research_local/lakh_phrases_v03`](../../research_local/lakh_phrases_v03). Its independent audit is [`audit.json`](../../research_local/lakh_phrases_v03/audit.json), SHA256 `e89f8275936e2813f577ba42eaf092c930a8a7170bc7777fecd04dbac4e37ecf`, and reports `passed: true`, 17,232 discovered sources, 16,995 verified sources, 237 recorded parse errors and 94,950 exported MIDI phrase rows. The phrase counts are 50,439 melodic and 44,511 percussion. The source and phrase manifest hashes are `062691ad29739cd58bdfb8c55258d63d72868d3ee3e4c30badeceaa917c8c76f` and `f7a1ccff7483bb70a07c0c3f04b7cd6d5090942b524272eac942d0ee3739160e`.

The preferred local release package is [`research_local/releases/reference_v04`](../../research_local/releases/reference_v04). Its archive is [`reference_v04.tar.gz`](../../research_local/releases/reference_v04.tar.gz), 181,957,781 bytes, SHA256 `76bab9daf6ad75cc952bc361ee6f2b1badf6de106c52f9b9574d11a31de676a2`. The [portable verification report](../../research_local/releases/reference_v04.portable_verification_v01.json), SHA256 `161cd27f46e96c9472e91eed4fbc66533d5ac86ca696dc58d88c5c9e90abbeee`, passes all 95,009 archive members, including 94,950 MIDI and 58 metadata payloads plus the checksum list. It includes a consumer guide, duplicate screening and the completed selection replay for every successful source. This is a local unpublished candidate package. It does not establish redistribution rights or human quality labels. The earlier `reference_v03` package remains unchanged as a historical snapshot.

The full archive was also extracted into a new directory and verified in recipient mode.
[`reference_v04.extracted_verification_v01.json`](../../research_local/releases/reference_v04.extracted_verification_v01.json),
SHA256 `bb0494a51193ea4e55c40be5e914061031a5382b083d86bab0d83d60ffc7460b`,
passes all 94,950 MIDI payloads and metadata with scope `metadata_and_extracted_midi`.

## Duplicate and split sensitivity

For the recovered reference corpus, the preferred supplementary duplicate view is [`research_local/duplicates_recovered_v01.json`](../../research_local/duplicates_recovered_v01.json), SHA256 `2077800af8e1df96609aece44a9f217f3ac29e24ba40ded124dbe1c55e7cc299`. It uses one recorded method key with zero cache reuse, fingerprints 16,995 parsed sources and records 6,164 symbolic near duplicate candidates, including 77 cross split candidates. It is heuristic evidence, not composition identity or complete corpus separation.

The corresponding portable split view is [`research_local/screened_splits_reference_v03`](../../research_local/screened_splits_reference_v03). `verify_screening(research_local/lakh_phrases_v03, research_local/screened_splits_reference_v03)` passed at audit time. The copied duplicate report has SHA256 `2077800af8e1df96609aece44a9f217f3ac29e24ba40ded124dbe1c55e7cc299`; the view connects 6,168 strong edges, quarantines 44 source groups containing 766 sources and retains zero cross split candidate edges. Original manifests and baseline split labels remain unchanged. Consumers must join phrase IDs to the supplementary `screened_split` mapping explicitly.

[`research_local/duplicates_full_v03.json`](../../research_local/duplicates_full_v03.json), SHA256 `149e3fdc9d89746d742b204c4a2d24882c0859b6bcb0b5f03cdaa1d9c2945635`, and [`research_local/screened_splits_reference_v01`](../../research_local/screened_splits_reference_v01) are retained as the strict manifest lineage. They use the earlier strict source and phrase manifests (`fa4c3010...` and `31b586ca...`) and should be described as a historical strict sensitivity view when the recovered v03 corpus is the subject.

## Completed evaluation receipts

Each entry below passed `samuged.experiment.verify_completed_experiment` in this checkout. The experiment receipt is the frozen start receipt. The completion receipt binds the saved results to it. Source snapshot and aggregate hashes are included so a reviewer can identify the exact executable and result bytes.

- `evaluation_reference_v04`: [`research_local/evaluation_reference_v04`](../../research_local/evaluation_reference_v04), experiment receipt `547dfed54378c435568f4ffe87427a8a1a67a008bd624d24c3cffead44a69536`, completion receipt `6e24ec926816aab1c5e726020e12d68117fd40b674687f3381eb36ca9590d350`, source snapshot `2173beedf195532e2b92c398fd47d911990214b85127990d78d084809caa0571`, aggregate `0279c49aa6226dd5b468c65467d5cdb75a98714c7fa538586085b9ba9842f41a`. This is a 1,000 case planted symbolic recurrence evaluation.
- `drum_evaluation_reference_v03`: [`research_local/drum_evaluation_reference_v03`](../../research_local/drum_evaluation_reference_v03), experiment receipt `b18458e7695a021ebc4fa60be0cd7391728b89541b85063fb8bd56529618a974`, completion receipt `953a1334b89452e27a2b7d3117f81d7321ebb07074b2fe246c6bf7e176cc9821`, source snapshot `487ed21720235da2fc33e2e9238d3b943ea0a40d9807ad609b737161192e74b5`, aggregate `e4d3e74f26c6dd7631a45201b0bcda13c02d40356b65f6466832b68601725a38`. This is a 1,000 case planted drum evaluation.
- `drum_stress_v03`: [`research_local/drum_stress_v03`](../../research_local/drum_stress_v03), experiment receipt `0ded8d095a9dbed3dc69f9d74a42310da2352c179fce1d1ed27a34c7132ecba9`, completion receipt `e87097c1f6877a122c2b24e3f46435b3cfab95a16fde0fc6ad8852a5acf968aa`, source snapshot `3411b237cb75e4d248ad04fe8c4990d5f6510af3bd6abbf5c9441959c3ff0f37`, aggregate `53b0ddd5cf84f992282bcab7d41a9d29a2f8088bb0901b5d74e04dc9b44114eb`. It contains 480 synthetic stress cases and is a boundary diagnostic.
- `jku_reference_v03`: [`research_local/jku_reference_v03`](../../research_local/jku_reference_v03), experiment receipt `4b48a06acaf1ca2b399e532e181eb8fbe2f7813873bab3539012f863e8ae28db`, completion receipt `8d4f5e74f658b80423b48b1c7fb7754cca3a76436d3fd7fc6ba007cb0341cffc`, source snapshot `6c0782eeafaf7a728448e0ae4f1dbc4bfe27aab702f4f974339cfa696b7ba03f`, aggregate `372640ec78580e725b0d0aca2998b109d391332db35acbb38691011030a780cb`. It covers five classical development works and verifies the published example tables; it is not a popular music accuracy benchmark.
- `aligned_frozen_v02`: [`research_local/aligned_frozen_v02`](../../research_local/aligned_frozen_v02), experiment receipt `dfb5f1e958dc68dfa6c9425e6ea18989e5fbde187d7c6c37f53aa153be17c303`, completion receipt `5396f4a6fdaeb48cb5bda0f8ee0504009dacd3322d8194c8129e8c57baf7ad55`, source snapshot `52dc89866926b66efecea7c576dc68ad72d5012689c73850dca73849522c2f43`, aggregate `4a0df800808e3e8edefa287e94b2decf57a66e222302f5755aaca6e3a17ed0fb`. It compares the indexed alignment variant on the frozen synthetic design and a bounded real pilot.
- `drum_oracle_v02`: [`research_local/drum_oracle_v02`](../../research_local/drum_oracle_v02), experiment receipt `896300214e5bf5602559d2456865eac1847894e9826f8a5b482c77c45eae0814`, completion receipt `42fb1e8c02eb33d3b106b8bcfb24c4129bc58aa08ece00a3a9ffc6193e2c3413`, source snapshot `879706f1749df154a69847691921e5c6174742a20cef2ad9776281556beac81e`, aggregate `3c000815a6bfd2a4722a9769f3d9910f70a051c088ba8df2b4be63fc30a836a4`. The preferred compact summary is [`results/drum_oracle_v02.json`](results/drum_oracle_v02.json), SHA256 `20aa2936f159f13a39a589ab7145abfe8295530dc712bede69092a1227c33fd3`. It is an independent symbolic pair admissibility diagnostic, without human labels or negative truth.
- `theme_evaluation_v02`: [`research_local/theme_evaluation_v02`](../../research_local/theme_evaluation_v02), experiment receipt `d55ae8d29338cec4172f3c617f3a10cf10f32b822819204f5778cb2c5c5e5361`, completion receipt `f225e3d57784f11ea9010dbefdf0015f508c59cfb3a93b763578778afaf89329`, source snapshot `67675145e919955a0dc55182592b0aaec2ff5e9099cd501a4092d0ea7ef286d2`, aggregate `57306121f8e17f7916c7035b06a5bb57784718f71e2ef7086b2c3abc988e8cd4`. The preferred compact summary is [`results/theme_evaluation_v02.json`](results/theme_evaluation_v02.json), SHA256 `c4055a01b44efce288412f90c43ac8409bfbcadf8834cdfd961cb6349078b251`. It is a six song exact note domain diagnostic over 18 annotation views, not the authors' beat domain metric or a corpus quality estimate.
- `closed_patterns_v01_replication`: [`research_local/closed_patterns_v01_replication`](../../research_local/closed_patterns_v01_replication), experiment receipt `b87adb7499a2aedc6649e3c60730c7f6aa168ea7ca68b3f72028de677fe1b6df`, completion receipt `98f46af700384176ae2406e5db360be61e404ea10773e57e99fd84e82e992aed`, source snapshot `30455e7d684f48822ccab5d8b848ed3fb97f00b4aea2bb696b77b5192f20300a`, aggregate `04393a86e0127203a15b8bc5ed52d11b358c3ab48d0835b41d43d4ff9bcee50e`. It is a fresh synthetic replication and unlabelled pilot comparison for an optional detector variant.

Other receipt backed diagnostics include [`metamorphic_v01`](../../research_local/metamorphic_v01), [`shortlist_sensitivity_v01`](../../research_local/shortlist_sensitivity_v01) and [`drum_cache_changes_v01`](../../research_local/drum_cache_changes_v01). Their completion receipts verify successfully. They are sensitivity or implementation audits and do not replace the reference detector or provide human quality evidence.

The supplementary [selection replay](selection_sample_audit.md) at [`selection_all_reference_v01`](../../research_local/selection_all_reference_v01) re-extracts all 16,995 successful reference sources with zero failures. Its completion receipt SHA256 is `3e606ae6fcf60fd979df9a6e238514f54887e5d0631ebed6102fb66b84cbf830`. The ordinary audit separately verifies all source and MIDI artifacts and reproduces the 237 recorded input errors. The earlier 256-source sample remains preserved at `selection_sample_reference_v02`.

## External inputs

The six song Theme Transformer input audit is [`research_local/theme_annotation_input_audit.json`](../../research_local/theme_annotation_input_audit.json), SHA256 `6ef0eb464551816b640e46f96af4adec783cced625cf36b0a822cb7b8721da8e`, with download receipt SHA256 `d19f5d8814f15e0177c6a16b989dcb9a6cdd9d012e279a9526d2217d8b970868`. The completed note domain evaluation above uses these inputs and explicitly keeps the timing distinction from the official POP909 melody files.

The prepared role cohort is [`research_local/external/pop909_role_v01`](../../research_local/external/pop909_role_v01). Its selection manifest has SHA256 `298475990757d9e8574e121f58dff14aaf35d5696963e6baa143de917db4d956`, its source manifest has SHA256 `076bbad7b4cecb1a274c5bb5148e5b34b44ecf222b2964902541dce2d9992f67` and its download receipt has SHA256 `66d8900ae247eaec76dc6a6c164fa7fdfb8dc01c0052cb150398dc24a77e083e`. The cohort contains 180 strict parsed sources, 60 development and 120 heldout IDs, selected under `samuged-pop909-role-v1` from official commit `d83e6edba6872a704f5d3b8b32f5cb540088dae6`; it excludes `065`, `284`, `310`, `422`, `449` and `464`. `MELODY`, `BRIDGE` and `PIANO` are source track metadata used for role analysis, not human labels.

## Current paper draft

The current local paper output is [`output/pdf/samuged_recurring_phrases.pdf`](../../output/pdf/samuged_recurring_phrases.pdf), six pages, SHA256 `10ef7decc9ac551c51efd1c080744a58517ab0c054e2e0629ecba24dd4649eb6`. Its input receipt is [`samuged_recurring_phrases.inputs.json`](../../output/pdf/samuged_recurring_phrases.inputs.json), SHA256 `aa0b4f24e3a436c57a8be3f63c6862b82ecb45d88c0dbc3cc3037dc9d14febd5`; all 132 paths and hashes matched during pause closeout. The generator SHA256 is `536bf43707424043394a7a8cfafc2cdf9d77aee8c50b981960e448b9c0a893c3`. All six pages were rendered and visually checked. The paper binds the reference corpus, audited indexed and closed comparisons and complete reference selection replay. It excludes the unvalidated full melody corpus and remains a local scientific draft. Human validation is pending. The previous promoted PDF and receipt remain preserved under `research_local/samuged_recurring_phrases.pre_pause_checkpoint_v01.*`.

## Additional completed evidence

The optional part-role study is [`part_ranking_v01`](../../research_local/part_ranking_v01), with independent audit [`part_ranking_audit_v01`](../../research_local/part_ranking_audit_v01). The fixed prior improves top-one MELODY-part agreement from 76 to 110 of 120 heldout official POP909 files. These are track-role labels, not phrase-quality labels. Its [study notes](part_ranking.md) report the frozen development choice, partial candidate replay scope and Lakh pilot.

The certified percussion experiment is [`certified_drums_v01`](../../research_local/certified_drums_v01). Preferred strict replay is [`certified_drums_strict_root_v01`](../../research_local/certified_drums_strict_root_v01), audit SHA256 `a53316d6353e85ef9539f3eaf5d9fb6706d05d08414322efa1e42054ea80a801`. All 360 cases pass source, oracle and detector replay checks. Both modes return no outputs on 120 heldout certified negatives and recover at least one target edge in all 60 heldout positive cases. Direct target-edge coverage is 120/180, so case recovery is not complete occurrence recovery. The [notes](certified_drum_controls.md) distinguish this conditioned symbolic test from natural-music specificity.

The [`selection_external_v01`](../../research_local/selection_external_v01) comparison covers 16 inputs under three selectors. Root replicated all 48 saved outputs at [`selection_external_root_v01`](../../research_local/selection_external_root_v01). Theme note F1 is unchanged, and the part prior slightly lowers JKU polyphonic establishment F1. These are reused development diagnostics, reported in [selection_external.md](selection_external.md). The paper reconstructs the metrics against verified external inputs.

The [`seed_bucket_sensitivity_v01`](../../research_local/seed_bucket_sensitivity_v01) study compares bounds 192 and 768 on 500 development cases and 46 fixed real files. One real output changes. The [measured optional setting](seed_bucket_sensitivity.md) does not replace the default. Root replay is [`seed_bucket_changed_source_root_v01.json`](../../research_local/seed_bucket_changed_source_root_v01.json).

The preferred installed-package check is [`packaging_smoke_v05`](../../research_local/packaging_smoke_v05), source commit `500df27473e84f90d245085021286221843129c7`. It binds all 236 payloads including the exact driver. Eight fixture sources pass extraction and complete selection replay for reference, closed and optional melody algorithms outside the checkout. See [installed_package_check.md](installed_package_check.md).

The [recurrence figures](recurrence_examples.md) bind deterministic melodic and percussion examples to exact source notes and tempo maps. The [paired listening packet](paired_review.md) provides a checked local A/B interface. Both are unlabelled inspection aids.

## Completed aligned builds and pending checks

The full `aligned_closed` corpus at
[`lakh_aligned_closed_v01`](../../research_local/lakh_aligned_closed_v01)
contains 50,566 melodic and 44,511 percussion rows. Its ordinary full audit
passes all 95,077 MIDI excerpts and 16,995 successfully parsed sources with
zero failures; all 112,309 manifest rows pass schemas. The separate
[`selection_sample_closed_v02`](../../research_local/selection_sample_closed_v02)
replay passes 256 sources, including all 28 recovered sources, 114 other
search-limited sources and 114 unlimited sources. Its completion receipt
SHA256 is `86555f8e7b1e58870796b511ac639108ad26a9ab800d709a0b78ff58241a004b`.
This remains a sample replay, not a full selection rerun.

The enhanced candidate package is
[`closed_v01.tar.gz`](../../research_local/releases/closed_v01.tar.gz),
205,245,269 bytes, SHA256
`3c2fe6777a3155292baa6b35641a603681f4f32cb3cf97328838844eca5b0804`.
Its [portable archive verification](../../research_local/releases/closed_v01.portable_verification_v01.json)
passes 95,145 members, including 95,077 MIDI excerpts and 67 metadata payloads
plus the checksum list. Report SHA256 is
`cbcf2179dc569e9600c781521018e983a20687c7516aadbfe856ad113fddd5fb`.
Its [extracted recipient verification](../../research_local/releases/closed_v01.extracted_verification_v01.json)
also passes every payload, report SHA256
`e000fd9f5d035f49e4fb43d602c3081ad1abd461d0e22086a059f1c1560b144c`.
The [full comparison note](closed_full_comparison.md) records the changes
relative to indexed alignment and the separately verified split view.

The full `aligned_indexed` extraction finished all 17,232 inputs with 95,079
exported rows, comprising 50,568 melodic and 44,511 percussion rows. Its first
audit stopped because a valid U+0085 character inside one part name exposed
use of line-boundary-aware `splitlines()` for JSONL. The Unicode-safe full
artifact audit now passes all source and MIDI rows with zero failures, and
all 112,311 schema rows pass. Its all-successful selection replay completed
at [`selection_sample_indexed_v02`](../../research_local/selection_sample_indexed_v02):
all 16,995 successful sources passed with zero discrepancies. Completion receipt
SHA256 is `8b2c75f94017767d1b8da6a253b9330712ddea13a53601e4e012b0c2b09a3830`.
The historical directory name does not change the actual `all_successful` mode.
Root verified exact coverage and canonical source records, then separately
matched all five bound dataset files including the complete source manifest.
Its release package has not been built.

The `aligned_melody` full build also completed naturally before the pause.
Its source and phrase manifests reconcile 17,232 inputs and 95,077 phrases
(50,566 melodic and 44,511 percussion). Their SHA256 values are
`e7a7bc1888f2522a4f61d0a596d869b374b93f53fa5e32866a46bd8bab04d1e4`
and `49c3e10c1768382ee468a4ee31bf5c340fefc38725171f4e93a58d4b825feb2e`.
Its full artifact audit, schema validation, replay and release have not started.
The corrected [build inventory](../../research_local/melody_pause_inventory_v02.json)
checks all 29 files against the actual frozen runner directory. The first private
inventory's mismatch claim was a wrong-base-path error, not changed frozen code.

The user requested a pause. Automatic continuation is `PAUSED`, downstream
waiters are stopped and no research computation remains active. The
[pause checkpoint](PAUSE_CHECKPOINT.md) records the final boundary and commands.
The [presentation](../../output/presentations/samuged_status_2026-10-03.pptx)
and its [PDF copy](../../output/pdf/samuged_status_2026-10-03.pdf) give the status
in Russian, including metric denominators and unfinished publication work.

## Claim limits

Receipt verification proves that the saved bytes match their recorded experiment boundary. It does not prove detector correctness outside the frozen case cohorts. The dataset contains heuristic recurrence candidates, parse errors and search or curation limits. The external studies are bounded diagnostics. No artifact in this index supplies human phrase acceptance, catchiness, salience or memorability labels.
