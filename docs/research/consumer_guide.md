# Consumer guide

This guide covers two separate uses of SaMuGeD. A code checkout provides the extraction package and the research scripts. An installed wheel provides the `samuged` extraction command and Python modules, but it does not install repository scripts such as `scripts/package_dataset.py`, `scripts/verify_release.py`, `scripts/validate_schema.py` or `scripts/make_review.py`.

## Choose an execution mode

For research from the source tree, start in the repository root. The module commands below resolve the checked out `samuged` package and the research scripts remain available.

```sh
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-research.lock
python -m samuged.cli build --source SOURCE_MIDI_DIR --output NEW_DATASET_DIR --limit 128
```

For an installed tool, install a supplied wheel into a clean environment and use its console entrypoint. Replace the wheel name with the file actually supplied.

```sh
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install samuged_phrases-0.2.0-py3-none-any.whl
samuged build --source SOURCE_MIDI_DIR --output NEW_DATASET_DIR --limit 128
python -m samuged.audit --source SOURCE_MIDI_DIR --output NEW_DATASET_DIR
```

The installed package evidence covers wheel installation, extraction and full re-extraction auditing on eight synthetic fixtures under `reference`, `aligned_closed` and `aligned_melody`. It does not test real corpus quality. Use a code checkout for the research scripts.

## Verify before extraction

A full portable check needs three inputs: the metadata directory, its `.tar.gz` archive and the archive's sibling `.tar.gz.json` receipt. The verifier reads the tar stream without extracting it. It checks exact member sets and hashes, manifest and audit bindings, MIDI payload hashes and included screening or replay evidence.

Run it from the repository root. The report path must be new, outside the metadata directory and different from the archive and receipt paths.

```sh
source .venv/bin/activate
python scripts/verify_release.py \
  --release /path/to/reference_v03 \
  --archive /path/to/reference_v03.tar.gz \
  --output /path/to/reference_v03.portable-verification.json
```

The archive has no enclosing top level directory. Extract it only into a new empty directory after verification. The `&&` prevents `tar` from running if `mkdir` fails because the target already exists.

```sh
mkdir /path/to/RELEASE-extracted && \
  tar -xzf /path/to/RELEASE.tar.gz -C /path/to/RELEASE-extracted
```

If only the archive was supplied, first compare its SHA256 with a value obtained through a trusted channel when one is available. Extract it into a new directory as shown above, then verify the complete extracted tree:

```sh
python scripts/verify_release.py \
  --release /path/to/RELEASE-extracted \
  --extracted \
  --output /path/to/RELEASE-extracted.verification.json
```

Extracted mode checks the archive's embedded `SHA256SUMS` against every metadata and MIDI payload, checks each MIDI file against the phrase manifest and validates the audit, replay and screening bindings. It cannot verify the compressed archive hash or its sibling receipt after extraction. These checks do not authenticate the publisher or repeat extraction from the absent full song sources. `--archive` and `--extracted` cannot be combined.

## Read the manifests

The following standard library example streams the JSONL files. Binary line iteration treats LF as the record boundary and preserves Unicode controls inside JSON strings. It selects one explicit kind, joins the phrase to its source record by `source_id` and reports the source level limits. It also performs the optional screened split join without loading the full manifests into memory.

```python
import json
from pathlib import Path
import sys

release = Path(sys.argv[1])
wanted_kind = sys.argv[2] if len(sys.argv) > 2 else "melodic"
if wanted_kind not in {"melodic", "percussion"}:
    raise SystemExit("kind must be melodic or percussion")


def jsonl(path):
    with path.open("rb") as stream:
        for raw in stream:
            if raw.strip():
                yield json.loads(raw)


phrase = next(row for row in jsonl(release / "phrases.jsonl")
              if row["kind"] == wanted_kind and row["split"] == "train")
source = next(row for row in jsonl(release / "sources.jsonl")
              if row["source_id"] == phrase["source_id"])

screened_path = release / "views" / "duplicate_screening" / "phrase_splits.jsonl"
screened = None
if screened_path.is_file():
    screened = next(row for row in jsonl(screened_path)
                    if row["phrase_id"] == phrase["phrase_id"])

ppq = phrase["ticks_per_beat"]
prototype = {
    "start_tick": phrase["start_tick"],
    "end_tick": phrase["end_tick"],
    "start_quarter_beats": phrase["start_tick"] / ppq,
    "duration_quarter_beats": (phrase["end_tick"] - phrase["start_tick"]) / ppq,
    "note_index": phrase.get("prototype_note_index"),
}
occurrences = [
    {
        "start_tick": item["start_tick"],
        "end_tick": item["end_tick"],
        "start_quarter_beats": item["start_tick"] / ppq,
        "duration_quarter_beats": (item["end_tick"] - item["start_tick"]) / ppq,
        "note_index": item.get("note_index"),
        "similarity": item["similarity"],
    }
    for item in phrase["occurrences"]
]

result = {
    "phrase_id": phrase["phrase_id"],
    "kind": phrase["kind"],
    "source_id": phrase["source_id"],
    "source_path": phrase["source_path"],
    "split": phrase["split"],
    "screened_split": screened["screened_split"] if screened else None,
    "ticks_per_quarter_note": ppq,
    "prototype": prototype,
    "first_two_occurrences": occurrences[:2],
    "midi_path": str(release / phrase["midi_path"]),
    "source_limits": {
        "melodic_search_limited": source.get("search_limited", False),
        "percussion_search_limited": source.get("drum_stats", {}).get(
            "search_limited", False
        ),
        "candidate_shortlist_truncated": source.get("curation_truncated", False),
    },
    "seconds_from_source_start": None,
    "seconds_note": "requires the original source MIDI tempo map",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
```

Run it with the extracted archive root and an explicit kind:

```sh
python read_release.py /path/to/reference_v03-extracted melodic
python read_release.py /path/to/reference_v03-extracted percussion
```

The original `split` remains in `phrases.jsonl`. When the supplementary duplicate-screening view is present, join `phrase_splits.jsonl` by `phrase_id` and use `screened_split` for that sensitivity analysis. Exclude both `overlap_excluded` and `duplicate_excluded` from train, validation and test data.

## Interpret coordinates and scores

`ticks_per_beat` is MIDI pulses per quarter note. The manifests express beat values in quarter note units, including compound meters. Divide an absolute source tick by PPQ to obtain quarter notes from source tick zero. `onsets_beats` is measured from the prototype interval start. A melodic prototype normally starts with an onset at zero. A bar aligned percussion prototype can start with silence, so its first onset can be greater than zero. `durations_beats` is also in quarter note units.

The phrase level `[start_tick, end_tick)` interval is the prototype in absolute source ticks. Every occurrence interval uses the same absolute source coordinate system and is also half open. For melodic reference records, `prototype_note_index` and occurrence `note_index` refer to the per part skyline note stream. Percussion records have no note index. Aligned records add their own note counts and matched note evidence as declared by the bundled schema. The verified nonoverlapping occurrence list can omit the prototype interval, so use the phrase level coordinates whenever the prototype itself is required.

Seconds depend on tempo and cannot be obtained from ticks and PPQ alone. Absolute seconds from the beginning of the source require the original source MIDI tempo map, which is not bundled in the portable archive. Do not assume 120 BPM.

Each exported `midi_path` contains the prototype only. Export tick zero corresponds to the phrase level source `start_tick`. Notes are clipped to `[start_tick, end_tick)`. The tempo and meter active at the source start are written at export tick zero, and changes strictly inside the interval are shifted by `-start_tick`. The required Mido runtime can therefore report the excerpt duration in seconds relative to export tick zero:

```python
import mido

excerpt = mido.MidiFile("/path/to/reference_v03-extracted/midi/melodic/PHRASE.mid")
print(excerpt.ticks_per_beat)
print(excerpt.length)
```

`recurrence_score` is a ranking heuristic, not a probability or calibrated confidence. Occurrence `similarity` is a matcher specific fit score and is not a probability either. Score components and their weights differ between melodic and percussion branches and can differ between algorithms.

Every source is subject to the configured `top_k` selection budget. `curation_truncated` means at least one melodic part exceeded its saved candidate shortlist before global selection. `search_limited` records melodic search bounds or saturated seed buckets. Percussion limits are under `drum_stats.search_limited`. Treat returned phrases as a bounded selected collection, not an exhaustive list of every recurrence in a song.
