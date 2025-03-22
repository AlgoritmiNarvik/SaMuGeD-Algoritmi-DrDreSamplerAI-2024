# MIDI Pattern Detection and Dataset Creation

This directory contains the scripts used to generate the Lakh_MIDI_Clean_Patterns_v1 dataset that powers the SaMuGed application's similarity search functionality.

## Contents

- [MIDI Pattern Detection and Dataset Creation](#midi-pattern-detection-and-dataset-creation)
  - [Contents](#contents)
  - [Main Components](#main-components)
  - [How the Dataset Was Created](#how-the-dataset-was-created)
    - [Overview](#overview)
    - [Technical Process](#technical-process)
    - [Using the Scripts](#using-the-scripts)
      - [Single File Processing](#single-file-processing)
      - [Batch Processing](#batch-processing)
      - [Configuration Options](#configuration-options)
    - [Implementation Details](#implementation-details)
      - [MIDI File Preparation](#midi-file-preparation)
      - [Segmentation Algorithm](#segmentation-algorithm)
      - [Pattern Matching Algorithm](#pattern-matching-algorithm)
      - [Advanced Deduplication Strategy](#advanced-deduplication-strategy)
      - [MIDI Output Generation](#midi-output-generation)
      - [Parallel Processing Implementation](#parallel-processing-implementation)
  - [Output Format](#output-format)
  - [Limitations](#limitations)

## Main Components

The dataset creation process involves two primary files:

- `test.py` - User interface and processing manager
- `pattern_detection_old.py` - Core pattern detection and extraction algorithm

## How the Dataset Was Created

### Overview

The pattern detection system analyzes MIDI files to identify repeating musical patterns or motifs within each track. These extracted patterns are saved as individual MIDI files, which collectively form the dataset used for similarity search.

### Technical Process

1. **Segmentation**: Each MIDI track is divided into segments based on natural breaks in the music (silence between notes)
   
2. **Pattern Detection**: Within each segment, the algorithm looks for repeating note sequences by:
   - Comparing note pitches and durations
   - Identifying when patterns begin and end
   - Requiring patterns to be at least one bar in length
   - Handling cases where notes may overlap or occur simultaneously
   
3. **Deduplication**: Similar patterns are identified and filtered to prevent duplicates
   
4. **Output Generation**: Each unique pattern is saved as a separate MIDI file or grouped by track

### Using the Scripts

#### Single File Processing

To process an individual MIDI file:
1. Run `test.py`
2. Click "single file"
3. Select a MIDI file
4. The extracted patterns will be saved to a new directory with "_Patterns" appended to the original filename

#### Batch Processing

To process an entire directory of MIDI files:
1. Run `test.py`
2. Click "folder"
3. Select a directory containing MIDI files
4. The script will process all MIDI files in the directory and its subdirectories
5. Patterns will be organized in a directory structure mirroring the input directory

#### Configuration Options

- **Overwrite existing patterns**: When enabled, overwrites any existing pattern files
- **One file per pattern**: When enabled, saves each pattern as a separate MIDI file; otherwise, saves patterns grouped by track

### Implementation Details

#### MIDI File Preparation

1. The algorithm loads MIDI files using the `miditoolkit` library
2. Drum tracks are explicitly excluded from analysis
3. Notes within each track are sorted by start time for sequential processing
4. The time signature is extracted to determine bar length in ticks (default: 384 ticks per bar for 4/4 time)

#### Segmentation Algorithm

The segmentation process works as follows:

1. The algorithm iterates through each tick of the MIDI file from start to end
2. It maintains a counter for "ticks since last note" which increments during silence
3. When a note starts playing:
   - The note is added to the current segment
   - The "note playing" flag is set to true 
   - The silence counter is reset to zero
4. When silence persists for exactly one bar length (as determined by the time signature):
   - The current segment is considered complete
   - The notes collected thus far are stored as a segment
   - A new empty segment is started
5. After processing all ticks, any remaining notes are saved as the final segment

This approach creates natural boundaries at musical phrase endings, which typically have rests between them.

#### Pattern Matching Algorithm

The pattern detection implements a state machine with the following components:

1. **Pattern State Tracking**:
   - `active_pattern`: Flag indicating if a pattern is currently being processed
   - `pattern_end`: The tick value when the current pattern candidate ends
   - `old_note_number`: Index to return to when the pattern ends or fails
   - `previous_compare_match`: Index of the matching note for the current pattern

2. **Note Comparison Logic**:
   - Notes are compared based on pitch (must be identical)
   - Duration differences are allowed up to 10 ticks (configurable tolerance)
   - When notes match, the algorithm checks if this is a new pattern or continuation

3. **Pattern Detection Steps**:
   - Algorithm compares each note with subsequent notes in the segment
   - When matching notes are found, it checks if they form a pattern:
     - If not already in a pattern, marks the start of a potential pattern
     - If already in a pattern, checks if the pattern is repeating
     - If the pattern ends (no more matches), the pattern is saved if it contains at least 3 notes
   - The algorithm looks for patterns that span at least one bar in length (measured in ticks)

4. **Pattern Boundary Detection**:
   - Pattern start: When first matching note pair is found
   - Pattern end: When subsequent notes no longer match the pattern
   - Minimum length requirement: Pattern must span at least one bar length

#### Advanced Deduplication Strategy

The deduplication process is multi-layered:

1. **Intra-segment Deduplication**:
   - Compares patterns within the current segment
   - For each pattern pair with the same length, compares notes one-by-one
   - If all pitches match, the second pattern is marked for removal

2. **Inter-segment Deduplication**:
   - Compares patterns with all previously found patterns across segments
   - Uses the same note-by-note comparison for patterns of equal length
   - Removes redundant patterns from the current segment

This thorough approach ensures that the dataset contains only unique musical patterns.

#### MIDI Output Generation

The algorithm can generate output in two formats:

1. **One file per pattern** (when ONE_FILE_PER_PATTERN is True):
   - Creates a new MIDI file for each pattern
   - Preserves original tempo, time signature, and MIDI metadata
   - Names files sequentially (pattern1.mid, pattern2.mid, etc.)
   - Organizes files in a directory structure reflecting source files

2. **Grouped by track** (when ONE_FILE_PER_PATTERN is False):
   - Creates one MIDI file per instrument track
   - Each pattern becomes a separate track within the file
   - Preserves original MIDI metadata
   - Option to include the original track alongside patterns (KEEP_ORIGINAL flag)

Both approaches include all MIDI metadata from the original file: tempo changes, time signatures, key signatures, and other events.

#### Parallel Processing Implementation

For batch processing, the implementation uses Python's multiprocessing module:

1. System cores are detected automatically
2. A worker pool is created with (cores - 2) workers (or cores - 4 for systems with >16 cores)
3. Files are distributed among workers using a queue system
4. Each worker thread processes files in sequence until the queue is empty
5. The main thread waits for all workers to complete before proceeding

This approach maximizes throughput while preventing system overload.

## Output Format

The dataset consists of MIDI files organized as follows:

```
Lakh_MIDI_Clean_Patterns_v1/
├── Artist_Name/
│   ├── Song_Name_Patterns/
│   │   ├── Instrument_Name/
│   │   │   ├── pattern1.mid
│   │   │   ├── pattern2.mid
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── ...
```

Each pattern MIDI file contains only the notes from the detected pattern, preserving the original tempo, time signature, and other MIDI metadata.

## Limitations

- The algorithm focuses on exact repetitions and may miss variations of patterns
- Minimum pattern length is set to one bar, which may miss shorter motifs
- Works best with monophonic sequences; complex polyphonic material may have variable results
- The pitch matching is strict (no transposition detection)
- The duration tolerance is fixed at 10 ticks, which may be too rigid for some performance styles
- Drum tracks are completely excluded from analysis
