# Human phrase annotation protocol

This protocol describes a small offline review of recurring phrase candidates. The packet is a convenience sample with kind balancing and at most one candidate per source, original `split_group` and canonical `family_id`. It is not a corpus quality estimate and it does not turn detector output into human validation. Existing detector ratings are not human ratings.

## Prepare a packet

Use the repository environment and fixed manifest snapshot:

```sh
source .venv/bin/activate
python scripts/make_review.py \
  --source 'datasets/Lakh MIDI Clean' \
  --dataset research_local/lakh_phrases_v03 \
  --output research_local/my_review.html \
  --count 60 \
  --seed samuged-review-v1
```

Keep the generated HTML, its `packet_config` and the source and phrase manifest SHA256 values together. Use the same packet and seed for independent raters. The packet records the sampling constraints and fallback rule for small manifests that omit `split_group` or `family_id`.

Source loading is strict by default. If a source manifest row carries a `metadata_repairs` receipt, packet generation explicitly opts into the recorded metadata recovery and compares the resulting receipt byte-for-byte before showing the candidate. Ratings retain that receipt as provenance.

## Review one candidate

Enter a stable annotator ID before exporting. Review the prototype and up to two other distinct occurrences using the piano rolls. A family with only two occurrences shows two excerpts in total. Playback is browser synthesis from symbolic notes and follows the source MIDI tempo map. It is not source audio, so timbre, production, mix and expressive performance are unavailable. Do not use the revealed path or detector score to decide the blind fields. Reveal them only after recording the initial judgement if provenance inspection is needed.

Record these fields for every candidate:

1. **Recurrence:** choose `yes` when all displayed excerpts are recognizably the same musical phrase under the displayed representation. Choose `no` when they are different material. Choose `uncertain` when the evidence is insufficient or the relationship depends on an ambiguous transformation.
2. **Boundary quality:** choose `good` when the displayed start and end capture the phrase cleanly in all shown occurrences, `partial` when a boundary is usable but cuts into or includes nearby material and `poor` when the proposed window is materially wrong. Do not use this field to judge whether the phrase is memorable.
3. **Musical role:** choose `melody`, `accompaniment`, `percussion` or `uncertain`. For a melodic candidate, accompaniment includes a repeated chord top or figure that does not function as the main line. Use `uncertain` when the symbolic excerpt does not support a role decision.
4. **Perceptual salience:** choose `high` when the phrase is prominent and easy to follow in the provided representation, `medium` when it is noticeable but not dominant, `low` when it is structurally present but easy to miss and `uncertain` when the synthesis or context prevents a decision. Salience is a perceptual annotation and is separate from recurrence and the detector score.
5. **Notes:** record a short reason for `no` or `uncertain` judgements and any boundary or role issue. Avoid copying source lyrics or other copyrighted content into the notes.

Export the local ratings JSON after reviewing all cards. It includes `review_id`, candidate and source identifiers, `source_sha256`, `source_path`, `split_group`, `family_id`, the four judgement fields and free notes. The provenance fields identify the reviewed candidate and its sampling constraints; they do not establish composition identity or rights.

## Optional independent raters

Two raters should use separate copies of the same packet and should not compare judgements before both exports are complete. Join rows by `review_id`, verify that the packet and manifest hashes match and retain missing judgements as missing. Report the number of paired rows and the raw agreement count for each field. For a chance-corrected summary, report Cohen's kappa separately for recurrence, boundary, role and salience when the paired sample is large enough to make it interpretable. Do not silently adjudicate disagreements. If an adjudicator is added, preserve the two original ratings and label the adjudicated field separately.

Report the convenience-sample counts by kind and the number of candidates excluded by the source, split-group or family constraints. Do not extrapolate these counts, agreement values or salience ratings to the full Lakh collection. A later corpus-quality study needs a preregistered sampling frame, a larger stratified sample, independent annotation training and an explicit treatment of duplicate or related arrangements.

The protocol supports claims about agreement with the displayed symbolic candidates only. It does not support claims that recurrence is catchiness, hook status, memorability or involuntary musical imagery.

## Analyze local exports

After one or more raters have exported their JSON files, validate and summarize them offline with:

```sh
source .venv/bin/activate
python scripts/analyze_ratings.py \
  --packet research_local/my_review.html \
  --ratings ratings-alice.json ratings-bob.json \
  --output research_local/ratings_analysis_v01
```

The output directory must be new or empty. The analyzer extracts the embedded `review-data` packet and requires the packet version, sampling configuration, candidate IDs, source hashes and paths, `split_group`, `family_id` and any exact `metadata_repairs` receipt to match every nonempty export. It requires a distinct nonempty `annotator_id` for every export, rejects duplicate, missing or unknown review rows and accepts only the documented enum values. A null judgement is retained as missing. An empty export, or an export whose rows are all still null, is recorded with status `no_ratings`; it is not evidence of an annotation result.

The report gives counts by kind, dimension and annotator. For each pair of annotators it reports the number of jointly rated rows, exact agreement and Cohen's kappa per dimension. Nulls are excluded from that dimension's paired calculation and `uncertain` remains an ordinary category. Kappa is null when there are no jointly rated rows or its chance-correction denominator is zero. The report stores exact packet and export bytes as declared completion artifacts in an input snapshot and links the snapshot, raw and aggregate results to a start and completion receipt with source and runtime provenance.

This is a convenience-sample analysis for agreement about the displayed symbolic candidates. It does not extrapolate to corpus quality, create labels, establish catchiness or accept a detector. Human ratings must be produced independently and retained as the original exports; synthetic fixtures in the test suite exercise the validator only.
