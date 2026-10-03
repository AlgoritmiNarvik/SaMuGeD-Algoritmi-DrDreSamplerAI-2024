# Paired listening review

`scripts/make_paired_review.py` creates a local HTML packet for a paired
listening comparison between two already audited dataset directories. It is
designed for a human preference study. It does not create labels, infer
ratings or make a corpus quality estimate.

The command requires a source MIDI root and two dataset directories:

```bash
source .venv/bin/activate
python scripts/make_paired_review.py \
  --left-dataset research_local/pilot_closed_v01 \
  --right-dataset research_local/pilot_melody_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --output research_local/paired_review_pilot_v03 \
  --count 12 --kind melodic --seed paired-pilot-v1
```

The output directory must be new or empty. It contains `review.html`,
`input_manifest.json`, `blind_mapping.json` and `packet_receipt.json`. The
HTML has no network requests or third party JavaScript. A reviewer sees only a
pair ID and anonymous A or B alternatives, with piano rolls, prototype notes
and up to two distinct recorded occurrences. Playback is a simple Web Audio
synthesis of symbolic notes. Note onset and duration seconds are calculated
from the source MIDI tempo map. Melodic notes use sine oscillators. Percussion
notes retain their source kit pitch IDs and simultaneous strikes in the piano
roll. Playback uses deterministic noise with a pitch dependent filter, which
helps distinguish kit IDs but does not reproduce General MIDI drum samples.
There is no source context excerpt because the existing safe excerpt helper
only exposes source identity and detector fields.

The packet validates each dataset's existing `audit.json` before sampling. The
audit must be a zero failure pass and its source manifest, phrase manifest,
summary and build configuration hashes must match the current files. A scope
with `full_source_coverage_required: true` is recorded as `full`; the pilot
audits used here are explicitly recorded as `pilot`. Selected source bytes,
paths, repair receipts, variant algorithms and reversible A/B mappings are
stored in the separate provenance files, so this is a reversible software
blind rather than physical blinding. The HTML contains opaque candidate IDs so
ratings remain bound to A and B, but it does not contain source paths, variant
names or the reversible mapping. Keep `blind_mapping.json` away from reviewers
until ratings are locked. The input manifest binds the paired packet generator
and the local MIDI, skyline, drum and metadata recovery code used to reconstruct
the excerpts.

Sampling joins common source IDs whose source hashes, paths, split groups and
metadata repair receipts agree. It requires one eligible phrase of the chosen
kind on each side and selects the top row by lowest `rank_in_file`, then by
highest recurrence score and phrase ID. The seeded source hash order is applied
before sampling and at most one source is selected per split group. Side order
is independently derived from the seed and source hash and is balanced to
within one pair. Changed outputs are not preselected. The mapping reports how
many selected pairs have identical rendered evidence, defined as the kind,
source-derived snippets and tempo map. Hidden detector scores do not affect
that identity test.

The browser export contract is:

```json
{
  "schema_version": "samuged-paired-review-ratings-v1",
  "annotator_id": null,
  "packet_sha256": "<hash of packet body without packet_sha256>",
  "ratings": [
    {
      "review_id": "P001",
      "preference": null,
      "notes": null,
      "candidate_ids": {"A": "<phrase id>", "B": "<phrase id>"}
    }
  ]
}
```

`preference` is one of `A`, `B`, `tie` or `uncertain`, or remains null when
the pair was not rated. Notes remain null when blank. `validate_ratings` checks
the packet hash, exact pair coverage, candidate bindings, duplicate IDs and
the preference enum. It does not fill missing fields or treat an unrated packet
as evidence.

## Pilot packet

The current generated local pilot packet is
`research_local/paired_review_pilot_v03`. It contains 12 melodic pairs from
the common 128 source pilot cohort, six `AB` and six `BA` side assignments. The
two source manifests have identical source bytes for the selected IDs. Seven
pairs have identical rendered evidence and five differ. Only those five pairs
can distinguish the variants in this packet. Both input audits passed with zero
failures and are recorded as pilot scope. An independent reconstruction check
matched all 24 rendered alternatives to the selected source MIDI notes and
coordinates.

The packet hash is
`87f6003143ef5922ccdb3e7a1a813195284a671c2ea2dbf670cb513724f94e9a`.
The output artifact hashes are:

* `review.html`: `c3fa82a959a0fb61b9c35eaf2d52e581642122d908fc82abbd9a6b9f34fd1c1d`
* `blind_mapping.json`: `dfe1698b8e6002fe1ce005a0d2a742cfa59d389cf0ef1119a6f8a07925417266`
* `input_manifest.json`: `36a7abe7a5357c81b44d599760496d5307c9b85abf523e91e250bb4e3a1390ae`
* `packet_receipt.json`: `70ba4ff5be23ee3b6e0f91aad22d3ad2f3b03e839a2e5dd4d554ca4175a44e7c`

The left pilot is `aligned_closed` and the right pilot is `aligned_melody`.
This packet is suitable for browser review of the pilot only. It does not
support claims about the full corpus, detector quality or musical preference
without actual human ratings and a separately specified analysis.

The preserved `research_local/paired_review_pilot_v01` packet must not be used
for review. Its browser script assigned `className` on SVG elements, which
throws in the tested browser before cards render. Version 2 replaces those
assignments with SVG attributes. The version 1 provenance remains unchanged as
evidence of the superseded packet.

Root browser verification rendered all 12 pairs, exercised play and stop controls and exported 12 rows with every preference and note still null. Version 3 also corrects signed integer conversion in the deterministic percussion noise generator. Its 48,000-sample numeric check stays within [-1, 1], has mean 0.00186 and preserves repeatability with distinct pitch seeds. The embedded melodic packet body is byte-equivalent to version 2; both preceding directories remain unchanged.
