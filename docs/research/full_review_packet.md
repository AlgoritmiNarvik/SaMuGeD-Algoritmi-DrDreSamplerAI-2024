# Full corpus paired review packet

## Purpose and scope

`research_local/paired_review_full_closed_v01` is a local 64 pair melodic review packet. The left input is the full audited `reference` dataset in `research_local/lakh_phrases_v03`. The right input is the full audited `aligned_closed` dataset in `research_local/lakh_aligned_closed_v01`.

The packet is a reversible software blind. Reviewers see A and B while `blind_mapping.json` retains the algorithm mapping. Keep that mapping away from reviewers until ratings are locked. No human ratings exist in this packet or its software smoke output. The packet provides no evidence of perceptual quality, preference or algorithm superiority.

## Frozen inputs and selection

Both inputs cover 17,232 source rows and require full source coverage. The reference audit passed with zero failures and binds 94,950 phrase MIDI rows. Its audit SHA256 is `e89f8275936e2813f577ba42eaf092c930a8a7170bc7777fecd04dbac4e37ecf`. The aligned closed audit passed with zero failures and binds 95,077 phrase MIDI rows. Its audit SHA256 is `34a4391532674b4981924cc2a4065df06e7b3ba6b012189164dac6f05746dd29`.

The packet command was:

```bash
source .venv/bin/activate
nice -n 10 python scripts/make_paired_review.py \
  --left-dataset research_local/lakh_phrases_v03 \
  --right-dataset research_local/lakh_aligned_closed_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/paired_review_full_closed_v01 \
  --count 64 \
  --kind melodic \
  --seed samuged-full-closed-review-v1
```

An independent streaming selection check found 16,869 sources with an eligible melodic top candidate in both variants. It reproduced the first 64 sources in the seeded order while allowing only one source per `split_group`. The selected set contains 64 distinct groups. No output was sampled based on whether the alternatives differed. Two rendered pairs are identical and remain in the packet, leaving 62 informative pairs. Side placement is balanced with 32 `AB` and 32 `BA` mappings.

The packet SHA256 is `678e90984db62b3169ab14a3fdda95b0fcf88173913c9b885f3fd0e1cc4633cd`. The selected source sequence SHA256 is `0b3918fb66c9856ba8e3ccf6eb30874f5646304997d36a2e92e1ed13f4dc33b4`.

## Independent reconstruction

`independent_verifier.py` does not call the packet generator's candidate or snippet helpers. It streams the two manifests, reproduces the seeded selection, loads each selected source MIDI and rebuilds both melodic alternatives from the declared part and skyline note stream. It checks source hashes, metadata repair receipts, exact prototype and occurrence note indices, interval endpoints, tempo maps and beat and second snippet values.

All 128 alternatives matched their rendered candidate recipe hashes. There were zero source hash mismatches and zero coordinate, tempo or snippet mismatches. The combined reconstructed recipe set SHA256 is `74720098dc5234b478f8fefb2e9459a3ac91afc9fd3f33792b7bd09264ead16f`.

The verifier SHA256 is `588deaa8f66095972220cb79f4e7611b6c7bb1b74bea1a24e20a46d811e4e5f0`. Its result is `independent_verification.json`, SHA256 `34b502afbdddff6a3c9980a381525e54325f9ae12ad71fd8318e12e6fb230d78`. `verification_summary.json`, SHA256 `583bd6cb0dfb14ad7c396d01d44596918930199452bf2a34869f555ac66d1c08`, records the audit bindings, code checks, sampling checks and software smoke result.

## Packet artifacts

The generator records its source closure in `input_manifest.json`. Its declared `scripts/make_paired_review.py` SHA256 is `de0d96d7c77b5b7f9ba0524d1799aad5511f2fa8b91a15b6dba544b8a6f599c1`, and every declared code hash matched the current file during verification.

- `review.html`: `1493e7230c3831f72c7354188cb3fc04c17235d372f75db498c39b266eaf0215`
- `blind_mapping.json`: `55fe92ab0ae7ae126d89aaffc749406bf9f1edcd92d8a228d4711f8ee31bdc02`
- `input_manifest.json`: `a00792266708c1f3b14f469916e21ee9f45222611b94cc85e15336406e01066f`
- `packet_receipt.json`: `18bce77191af7a02dab11a5d207b0e2442440889753cdf83e3216f991b6b14d7`

The root reviewer rendered the packet in the local in-app browser, checked both P001 playback controls and the stop state, and saved the actual 64-row export with all preferences and notes null. The download event did not arrive before the tool timeout, so the visible export fallback was saved instead. No browser error or warning logs were returned. The actual browser export passed the rating analyzer with `no_ratings`. These are software checks, not listening judgments. Evidence is `research_local/paired_review_full_closed_browser_check_v01.json`, with a screenshot at `research_local/paired_review_full_closed_browser_top_v01.png`.

The root reviewer also reran the saved independent reconstruction driver. Its output at `research_local/paired_review_full_closed_root_reconstruction_v01.json` equals the original report, including all 128 alternatives and the recipe set hash.

## Null software smoke

`research_local/paired_review_full_closed_v01_null_smoke/ratings-null.json` contains exactly 64 rows with null preference and null notes. It is a software fixture, not a human annotation. `scripts/analyze_paired_ratings.py --machine-ui-test` returned `no_ratings`, one machine test export and zero human ratings. Its completion receipt passed `verify_completed_experiment`.

- Null ratings SHA256: `a94f9d2fb3bfb032e433aa03ada66a28c41f57ad5c1ebcc229af4daf5788da92`
- Aggregate SHA256: `41b0dff5eaa1bad13d4f73b25520b6b5f573b9c521c7f690cdfd3db8d111fdd8`
- Raw results SHA256: `8bb41b0f8bb48dcb6ca5686986dec93ab0a59f9ad1751bddb59b084b64e9226a`
- Completion receipt SHA256: `67f8d2c06d50856c319c8a32bd973ae0f5c93d538663264abf1e5ad3f628deb5`

Human review must use a new exported ratings file. Do not treat the null fixture or browser control checks as listening judgments.
