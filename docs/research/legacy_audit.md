# Legacy recurring phrase extraction audit

## Scope and snapshot

This is a read only audit of the recurring phrase extraction work present at commit `200c4a2`. It covers the scripts that created the local `two_pointers_repeats_only` dataset, later experimental detectors, the similarity search notebook, the local source and generated MIDI collections and Git history. It does not assess or modify the desktop or web applications.

The repository history identifies the actual dataset builder unambiguously. `testing_tools/test_scripts/asle_scripts/test.py:5` imports `pattern_detection_old.py` with the comment that it created the last dataset. Commit `817a442` changed the import back to that old implementation for this reason. The later `pattern_detection.py` is useful evidence about intended repairs but is not the generator of the existing dataset.

The only remote topic branch, `origin/windows-install-script`, contains Windows packaging and application changes. It retains the same detector experiments and adds no evaluated recurring phrase method. The useful algorithm work is already reachable from `origin/main` and repository history.

## Findings in the dataset builder

### Meter and timing are not represented correctly

`pattern_detection_old.py:114-124` calculates a bar as `ticks_per_beat * numerator`, omitting the denominator. When no time signature is present it returns a fixed 384 ticks, independent of the file's ticks per beat. If the first time signature begins after the requested time, `ticks` is used before assignment.

The following in memory checks were run in the project virtual environment:

```text
ticks_per_beat=480, no time signature: returned 384, expected 1920 for 4/4
ticks_per_beat=480, 6/8: returned 2880, expected 1440
ticks_per_beat=480, first 4/4 event at tick 100: UnboundLocalError at tick 0
```

The silence splitter iterates over every tick and scans all remaining notes (`pattern_detection_old.py:69-89`). This is much more expensive than traversing sorted note boundaries and makes runtime depend on score resolution and total duration rather than note count.

### The match predicate does not establish phrase recurrence

`pattern_detection_old.py:100-111` compares absolute pitch and note duration only. It does not compare onset intervals, rests or metrical position. Two same pitch notes with the same duration compare equal even when their onsets are 10,000 ticks apart. A transposed version of the same interval and rhythm sequence compares unequal.

The state machine starts a candidate when two matching anchor notes are separated by at least its flawed bar length (`pattern_detection_old.py:169-178`). The condition constrains anchor separation, not the duration of the candidate phrase. It then depends on an exact event index sequence and an exact onset equality at the proposed repetition boundary (`pattern_detection_old.py:180-200`). This combination can accept unrelated same pitch and duration runs while missing transposed phrases, rhythmic equivalents and many polyphonic repetitions.

Drum instruments are dropped unconditionally (`pattern_detection_old.py:46-48`). That is a valid scope choice for a melodic dataset but must be recorded as dataset policy rather than treated as a detector result.

### Deduplication is incorrect

The intra segment comparison breaks when a pitch differs but still marks the second pattern as a duplicate (`pattern_detection_old.py:229-249`). Equal length is therefore enough for removal in many cases. The inter segment comparison uses `k`, an index in a previous segment's pattern list, against the deletion mask for the current segment and suppresses resulting index errors (`pattern_detection_old.py:251-269`). Both paths can remove nonduplicates or fail to remove duplicates.

### Track and output control flow loses data

If the first processed track with no detected pattern leaves `list_of_all_patterns` empty, the function returns from the entire song (`pattern_detection_old.py:288-293`). Later tracks are never considered.

When one file per pattern is enabled, `pattern_number` resets for each track and the output path does not include the track. Later tracks can overwrite earlier files (`pattern_detection_old.py:295-316`). The batch user interface used grouped output by default (`test.py:120-121`). Grouped files retain source absolute note times (`pattern_detection_old.py:318-340`), which explains the long leading silence in most generated pattern tracks.

The batch traversal stops when its directory counter reaches 2,200 (`test.py:49-73`). It has no manifest of attempted inputs, successes, no match outcomes or failures. The generated corpus cannot establish complete source coverage from directory contents alone.

### Documentation claims exceed the evidence

The README states that the data contains unique patterns, each at least one bar long, with natural phrase boundaries (`testing_tools/test_scripts/asle_scripts/README.md:91-151` and `SaMuGed-SimilarMidis/README.md:148-157`). The implementation and local output measurements do not support those statements.

The later similarity system compresses each whole MIDI to global statistics (`SaMuGed-SimilarMidis/feature_calculator.py:24-75`) and ranks standardized vectors with Euclidean distance (`SaMuGed-SimilarMidis/database.py:218-240`). It is a retrieval prototype, not evidence that the extracted items are recurrent phrases. Its weight rationale is explicitly a draft (`testing_tools/clustering/choosing_feature_weights.md:1-29`), feature statistics cover 22 files (`testing_tools/clustering/feature_statistics.txt:1-14`) and the project still lists accuracy and edge case tests as unfinished (`SaMuGed-SimilarMidis/docs/PROGRESS.md:390-400`).

## Local corpus measurements

The source corpus contains 17,232 regular files ending in lowercase `.mid`. A default `rg --files` count produces 17,230 because it omits the hidden `.38 Special` directory, which contains two additional MIDI files. There are no `.midi`, `.MID` or `.MIDI` variants. This reconciles the two observed counts.

The generated `datasets/two_pointers_repeats_only` tree contains 2,851 song directories whose names end in `.mid` and 7,662 regular `track*.mid` files. The apparent 10,513 `.mid` paths from an unrestricted recursive glob are the sum of these directories and files.

All 7,662 regular generated MIDI files parsed with `miditoolkit`. They contain 15,165 instrument tracks, treated here as extracted pattern instances. Measurements used these definitions:

- Start tick is the minimum note onset in an instrument track.
- An exact duplicate has the same ordered sequence of absolute pitches, onset offsets from the track's first note and note durations. Velocity and instrument metadata are ignored.
- Duration in beats is `(maximum note end - minimum note start) / ticks_per_beat`.
- Note count is the number of notes in one generated instrument track.

Results:

- 353 of 15,165 pattern instances start at tick zero. The median first onset is 30,600 ticks and the maximum is 960,000 ticks.
- 433 later pattern instances are exact duplicates of an earlier instrument track in the same generated file by the definition above. They occur in 370 generated files.
- Note count has minimum 1, median 16 and maximum 1,073. One instance has one note and two have two notes.
- 44 instances span less than one quarter note beat. 3,626 span less than four quarter note beats. The median is 7.9896 beats and the maximum is 415.5 beats. Four beats must not be equated with one bar for non 4/4 meters.
- Generated file size has minimum 93 bytes, mean 1,028.17 bytes and maximum 14,148 bytes.

These measurements describe local artifacts. They do not establish precision, recall, musical phrase quality or memorability.

### Reproduction commands

The inventory reconciliation used:

```sh
find 'datasets/Lakh MIDI Clean' -type f -name '*.mid' | wc -l
find 'datasets/Lakh MIDI Clean' -type f | rg -i '\.(mid|midi)$' | wc -l
find 'datasets/Lakh MIDI Clean/.38 Special' -type f -name '*.mid'
find datasets/two_pointers_repeats_only -mindepth 2 -type d -name '*.mid' | wc -l
find datasets/two_pointers_repeats_only -type f -name 'track*.mid' | wc -l
find datasets/two_pointers_repeats_only -type f -name 'track*.mid' -exec stat -f '%z' {} + \
  | awk '{n++; s+=$1; if ($1<min || NR==1) min=$1; if ($1>max) max=$1} END {print n,s,min,max,s/n}'
```

The meter and predicate checks used:

```sh
source .venv/bin/activate
python - <<'PY'
import importlib.util
from miditoolkit.midi.containers import Note, TimeSignature

path = 'testing_tools/test_scripts/asle_scripts/pattern_detection_old.py'
spec = importlib.util.spec_from_file_location('legacy_detector', path)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

print(legacy.ticks_per_bar(480, 0, []))
print(legacy.ticks_per_bar(480, 0, [TimeSignature(6, 8, 0)]))
try:
    print(legacy.ticks_per_bar(480, 0, [TimeSignature(4, 4, 100)]))
except Exception as error:
    print(type(error).__name__, str(error))

notes = [Note(100, 60, 0, 240), Note(100, 60, 10000, 10240)]
print(legacy.compare_notes(notes, 0, 1))
notes = [Note(100, 60, 0, 240), Note(100, 65, 1000, 1240)]
print(legacy.compare_notes(notes, 0, 1))
PY
```

The artifact scan used the project virtual environment and read files without writing output:

```sh
source .venv/bin/activate
python - <<'PY'
from collections import Counter
from pathlib import Path
import statistics
from miditoolkit import MidiFile

files = [p for p in Path('datasets/two_pointers_repeats_only').rglob('*.mid') if p.is_file()]
instrument_counts = []
note_counts = []
start_ticks = []
durations_beats = []
duplicate_tracks = 0
files_with_duplicates = 0

for path in files:
    midi = MidiFile(str(path))
    instrument_counts.append(len(midi.instruments))
    seen = set()
    duplicates_here = 0
    for instrument in midi.instruments:
        note_counts.append(len(instrument.notes))
        if not instrument.notes:
            continue
        first = min(note.start for note in instrument.notes)
        last = max(note.end for note in instrument.notes)
        start_ticks.append(first)
        durations_beats.append((last - first) / midi.ticks_per_beat)
        key = tuple(
            (note.pitch, note.start - first, note.end - note.start)
            for note in sorted(instrument.notes, key=lambda n: (n.start, n.pitch, n.end))
        )
        if key in seen:
            duplicate_tracks += 1
            duplicates_here += 1
        seen.add(key)
    if duplicates_here:
        files_with_duplicates += 1

print('files', len(files))
print('instances', len(note_counts))
print('starts_at_zero', sum(value == 0 for value in start_ticks))
print('median_start', statistics.median(start_ticks), 'max_start', max(start_ticks))
print('duplicates', duplicate_tracks, 'files_with_duplicates', files_with_duplicates)
print('note_min_median_max', min(note_counts), statistics.median(note_counts), max(note_counts))
print('one_note', sum(value == 1 for value in note_counts), 'two_notes', sum(value == 2 for value in note_counts))
print('duration_lt_1_beat', sum(value < 1 for value in durations_beats))
print('duration_lt_4_beats', sum(value < 4 for value in durations_beats))
print('duration_median_max', statistics.median(durations_beats), max(durations_beats))
PY
```

## Useful prior work

The strongest reusable parts are ideas and fixtures rather than a validated detector.

- `PatternSegmentationNgrams.py:38-60` contains a simple exact repeated n-gram baseline. Its current version searches pitch and duration independently and stops after the first n-gram length with any repeat, so it should be adapted rather than used unchanged.
- `PatternSegmentationSlidingWindow.py:38-79` enumerates exact pitch n-grams and occurrence positions. It provides a second simple baseline but ignores rhythm and transposition and emits every nested repeated subsequence.
- `PatternSegmentationBarEuclidean.py:13-66` correctly includes the time signature denominator for its first time signature and aligns material to bars. Its vector distance (`:80-135`) mixes pitch, tick time, duration and velocity on a single arbitrary scale and assumes no meter change, so its representation and threshold are not defensible as is.
- The archived DTW experiments show an intended approximate matching direction. They use uncalibrated thresholds and in some cases compare individual notes rather than sequences, so they are exploratory only.
- `testing_tools/Manual_seg/take_on_me_seg` provides manually named structural segments for one song. The accompanying labels are section boundaries (`take_on_me_song_structure.txt:1-21`), not recurring melodic phrase families. They are useful for visual sanity checks but cannot serve as a recurrence benchmark.
- The synthetic retrieval MIDI files test file loading, vector shape and self retrieval. They do not test recurring phrase boundaries or negative cases.

## Recommended detector

The proposed per part onset skyline detector is a reasonable deterministic starting point if its scope is explicit. A skyline can fabricate a melody by switching between the highest notes of successive chords. Record the source part, polyphony ratio and skyline transformation, then compare a monophonic only subset with the skyline subset as an ablation.

Represent time in quarter note beats using ticks per beat, then quantize onset intervals and durations with one documented resolution. Preserve original ticks in provenance. Use separate tokens for pitch or pitch interval, inter onset interval and duration. Do not infer silence from velocity.

Candidate note counts of 6, 8, 12, 16, 24 and 32 with spans of 4 to 32 beats are testable. They impose length priors and generate many nested versions of an ostinato. Apply maximal repeat or dominance filtering after occurrence verification and report results by candidate length. Fix these values before evaluating the held out set.

Use an interval seed index for candidate generation, then verify the complete window with explicit rhythm and duration comparisons. Keep the three matching modes distinct:

- Exact mode requires equal absolute pitch, quantized onset interval and quantized duration tokens.
- Transposed mode requires equal pitch interval, quantized onset interval and quantized duration tokens.
- Approximate mode uses a stated weighted edit or alignment distance. Tune its threshold on development songs only and freeze it before test evaluation.

Require at least two nonoverlapping occurrences to suppress self overlap. This policy can exclude valid overlapping ostinati, so keep an overlap rejection count and test an overlap allowed ablation. Treat diversity reranking as a curation step after detection. Report detector metrics both before and after reranking so dataset balancing cannot hide detector errors.

Write one manifest record per motif family with all occurrences. At minimum it should contain source relative path and content hash, part and program, source ticks per beat, detector version and configuration hash, match mode, canonical tokens, occurrence start and end in ticks and beats, similarity components, rejection reason if applicable and the representative MIDI path. Exported MIDI excerpts should start at tick zero. Stable identifiers should derive from source content, part and canonical motif content rather than traversal order.

The batch runner should sort inputs, process every source independently, checkpoint safely and record `accepted`, `no_match`, `parse_error` or `processing_error`. A final accounting invariant should reconcile the 17,232 discovered source paths with these outcomes.

## Baselines and experiments

Compare the proposed detector with methods that answer the same recurrence question:

1. Legacy state machine adapter using `pattern_detection_old.py` semantics, with exceptions captured per file.
2. Exact absolute pitch n-gram baseline from the sliding window prototype.
3. Exact transposition invariant interval plus rhythm token baseline.
4. Proposed exact, transposed and approximate configurations.

Do not use the FAISS global feature retriever as the primary baseline because it ranks whole extracted files and does not detect recurring spans. It may be reported separately as a retrieval experiment.

Build deterministic synthetic cases with known occurrences and known negatives. Required cases include exact recurrence, transposition, changed tempo with the same beat relative pattern, differing ticks per beat, 3/4 and 6/8, a time signature change, rhythmic alteration, one inserted or deleted note, repeated pitch runs, long rests, phrase starts off the bar line, overlapping occurrences, a distractor sharing only its first note, polyphonic chords, skyline switching and a drum only track. Each case should assert family count, occurrence spans, match mode and rejection behavior.

Create a human annotated evaluation set grouped by source song, not by extracted window. Stratify by meter, density, phrase length and monophonic or polyphonic input. Two annotators should mark recurring melodic phrase families and all occurrence boundaries without seeing detector output. Report agreement and resolve only the held out gold set. The existing Take On Me sections can seed annotation procedure design but should not dominate the set.

Tune quantization, approximate thresholds and dominance rules on development songs. Freeze them before the test run. Prevent artist and song leakage between development and test groups.

Primary metrics should be occurrence precision, recall and F1 with a predeclared boundary tolerance, plus pairwise motif family F1. Also report exact boundary F1, accepted families per song, source coverage, duplicate rate, parse failure rate and runtime per note. Use song clustered bootstrap confidence intervals and paired song level comparisons for detector differences. Publish per stratum results and the full rejection accounting.

The scientific report should distinguish structural recurrence from human response. Repetition frequency, span, transposition and rhythmic stability are measurable MIDI properties. The current repository has no listening study or human memorability labels, so no experiment here can support a claim that detected recurrence predicts earworm memorability. Such a claim requires a separate preregistered human study with an appropriate outcome measure and held out evaluation.

## Acceptance criteria for a replacement dataset

- Every discovered input has one terminal manifest outcome and totals reconcile.
- Every accepted family has at least two verified occurrences under its declared match mode.
- Every MIDI artifact parses, starts at tick zero, has positive note durations and matches its manifest spans.
- Stable source grouped splits and detector configuration are preserved with hashes.
- Duplicate and nested candidate policies are deterministic and measured.
- Synthetic tests cover the required positive, negative, meter, timing and polyphony cases.
- Held out metrics include uncertainty and outperform the legacy and exact n-gram baselines on the declared primary metric.
- Claims remain limited to recurring melodic phrase extraction unless separate human evidence is collected.
