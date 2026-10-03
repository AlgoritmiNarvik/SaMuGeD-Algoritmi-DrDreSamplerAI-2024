# Counter vote iteration experiment

## Question

The aligned indexed detector constructs candidate group votes with a nested Python generator passed to `Counter`. This experiment tests an exact implementation alternative using `itertools.chain.from_iterable(postings)`. It changes no heuristic, resource limit, verifier or ranking rule.

The alternative must return identical complete detector results, including phrases and every telemetry field, on all 500 existing development cases and the fixed 128 file real pilot. Timing is assessed separately after warmup on 16 deterministic real files, eight with prior seed saturation and eight without it, using three alternating order repetitions.

## Reproduction

Run from the repository root after activating the environment:

```bash
source .venv/bin/activate
nice -n 10 python scripts/compare_vote_iteration.py \
  --source "/Volumes/C/Algoritmi/Lakh MIDI Clean" \
  --manifest research_local/pilot_melody_v01/sources.jsonl \
  --output research_local/vote_iteration_v01
python scripts/verify_experiment.py \
  --experiment research_local/vote_iteration_v01/experiment
pytest -q tests/test_vote_iteration.py
```

The runner creates an exact copied candidate module under the output directory before freezing the experiment. The start receipt snapshots both the baseline and candidate modules plus their explicit runtime import closure. Detector execution loads the candidate from that immutable snapshot.

## Results

### Correctness

The complete serialized detector result was identical for both implementations on all 500 development cases and all 128 real pilot files. This includes every selected phrase field and every `part_stats` telemetry field. There were zero phrase, telemetry or complete result mismatches.

The copied baseline module has SHA256 `afca9f7c8bf8e231d7b544cd0cb98f8c6e93e301ca1dea5939b0bae042b0eab6`. The frozen candidate has SHA256 `1cd68d711deab45113cb73ddf101e3ac69db7fcda4ccee4d5dd8cc814f9c1048`. Restoring the import and vote expression in the candidate reproduces the baseline source exactly.

### Timing

The timing cohort ran one untimed warmup pass followed by three measured repetitions. Each repetition contained eight previously saturated files and eight unlimited files. Variant order alternated by file and repetition.

| Measurement across 48 paired calls | Generator baseline | `chain.from_iterable` |
| --- | ---: | ---: |
| Total detector time | 159.776 s | 157.780 s |
| Mean per call | 3.329 s | 3.287 s |
| Median per call | 2.708 s | 2.653 s |
| Faster paired calls | 14 | 34 |

The total time ratio was 0.9875, an observed 1.25% reduction. The median paired ratio was 0.9893. The candidate total was lower in all three repetitions, with ratios of 0.9827, 0.9925 and 0.9875. The saturated subset ratio was 0.9831 and the unlimited subset ratio was 0.9945.

The direct vote construction microbenchmark used three deterministic posting shapes and seven alternating repetitions per shape. Its total ratio was 0.5512, a 44.9% reduction for the isolated expression. The much smaller detector result shows that vote iteration accounts for a limited part of total runtime.

Two full four worker corpus builds were active when the start receipt was frozen. This study used reduced process priority but did not isolate CPU, memory bandwidth or filesystem load. The repeated paired design reduces order bias but does not turn the 1.25% observation into a production speed guarantee. The same 16 files were also used in the untimed warmup, so their file data may have remained in the operating system cache for both variants.

### Memory

One `tracemalloc` pass per implementation used the first frozen saturated timing file, `DJ_Jazzy_Jeff/Summer_Time.mid`. Both implementations reached the same traced Python allocation peak of 133,440,523 bytes and returned the same result hash. This is a single Python allocation measurement, not process resident memory.

## Decision

The alternative is semantics preserving on the measured cohorts, but its end to end effect was about 1%. That is not material enough to change the default from this nonisolated experiment. The candidate remains an experimental source copy. A promotion would need either clearer whole detector evidence in an isolated benchmark or a larger optimization that reduces the number of posting entries visited rather than only their iteration overhead.

Integrity identifiers:

- start receipt SHA256: `6f99535356fd8e1ab334c8d4b7b6fe63b1000fc3bcaa1732e23c87e2cc5941f2`
- source snapshot SHA256: `a37895890161917850e5439414d9e5a2fa46650fff098e4a1a1402f9d3d93faf`
- case cohort SHA256: `26d6ed0636b21e6a7d435609a9c2f7ca26b299df7c55b1526ba22bea3e722b10`
- raw results SHA256: `a338f865bbbc29f03cf5ffb07f18530500e2edfe53a51c79bfd967ee6dc48ca3`
- aggregate SHA256: `ef05e141640834af6a7e8c76a141d0c7c19ad459737ccd5dfbe849c82e193f1a`

An independent root check verified all 128 source hashes and fully replayed the two most saturated selected real sources against the frozen baseline and candidate. Complete output and telemetry hashes agreed with the study. The check is `research_local/vote_iteration_root_replay_v01.json`. Later runner-only changes make correctness failures exit nonzero and preserve Unicode separators in JSONL records; they do not alter either frozen detector or the completed experiment artifacts.
