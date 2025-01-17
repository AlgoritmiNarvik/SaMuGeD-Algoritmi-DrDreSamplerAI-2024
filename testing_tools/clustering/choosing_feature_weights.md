**TL;DR**: We should focus on capturing the *internal intervals* (pitch distances) and *relative rhythmic patterns* first, rather than absolute pitch or global tempo. For producers, the most important features are those that reflect “how the notes move in relation to each other” (both pitch-wise and rhythm-wise). That means weighting *rhythmic features* (onset patterns, relative durations) and *intervallic pitch features* (differences from note to note) more strongly than static measures like absolute mean pitch.

## Music-theory priorities? [draft v 030]

   **Relative Pitch & Rhythm**  
   - Music producers typically care most about *intervallic pitch movement* and *rhythmic pattern similarity*.  
   - If you keep absolute pitch and tempo features (pitch_mean, pitch_std, tempo, etc.), consider *downgrading* those weights somewhat.

   **Weight Hierarchy**  
   - **High Weight** (2× or 3× normal):  
     - Interval-based pitch features (e.g., pitch_std if it reflects melodic “spread”)  
     - Rhythmic complexity (ioi_std, syncopation_ratio) if it captures the “groove” accurately  
   - **Moderate Weight** (1×):  
     - ioi_mean (overall note density) ***NOTE: maybe this feature should be more important?***
     - duration_mean/duration_std (some effect, but less critical than interval patterns)  
   - **Lower Weight** (0.5× or 0.75×):  
     - pitch_mean (often overshadowed by interval movement)  
     - tempo (some difference in BPM might be tolerable as long as the pattern is the same)  

> **Example**: If you define a base weight of `1.0` for each feature:
> - `pitch_mean`: 0.7  
> - `pitch_std`: 2.0  
> - `duration_mean`: 1.0  
> - `duration_std`: 1.0  
> - `ioi_mean`: 1.0  
> - `ioi_std`: 2.0  
> - `syncopation_ratio`: 2.0  
> - `tempo`: 0.5  
# we can also have these as user input in "advanced settings" tab or region of the plugin's UI

**Problem Statement**  
- We have a large MIDI library and a user’s own MIDI file. The goal: **find the MIDI samples in the library that are most similar** to the user’s input.  
- “Similarity” is more than just BPM or average pitch; we need to capture *musical feel*.
---

### Core Musical Concepts

1. **Pitch vs. Interval**  
   - **Absolute Pitch**: The raw MIDI values (0–127).  
   - **Relative Pitch (Intervals)**: The distance between consecutive notes (e.g., 7 semitones from A to E). This is how many producers conceive melodic “shape.”  
   - **Why Relative Pitch Matters**:  
     - Two melodies transposed to different keys may still *feel* similar.  
     - Example: Melody “A–E–C–E–D” vs. “Eb–Bb–Gb–Bb–Ab.” Both have the same interval pattern (0, +7, +3, +7, +5).

2. **Rhythmic Features**  
   - **Onset Patterns**: Where notes fall in time, especially relative to the measure (e.g., 4/4).  
   - **Inter-Onset Intervals (IOI)**: The time gaps between notes (e.g., 1/8 vs. dotted 1/16).  
   - **Syncopation**: How much notes fall “off” the strong beats.  
   - **Why Rhythm/Syncopation Matters**:  
     - Rhythmic “feel” often dictates how a melody grooves.  
     - Subtle differences like 1/16 vs. dotted 1/16 can be crucial for matching a “tight” or “swing” pattern.

3. **Timing Signatures and Beat Hierarchy**  
   - **Higher Weight for Early Beats**: For many producers, notes in the first half of the bar often set the groove or motif.  
   - Example: If the first two beats have matching patterns, they are considered strongly similar even if the latter half differs slightly.
---

### Single-number summaries vs. Full sequence comparison

We need a **single scalar** per sequence (beyond just mean or mean+std) that still conveys
the “essence” of that sequence. We’re avoiding expensive note-by-note comparisons in a
20,000-note library, but a lone average discards too much detail.

### Additional features for capturing pitch/note Changes

Beyond `pitch_mean` and `pitch_std`, we can incorporate features that reflect how pitches
(or durations) *evolve* over the sequence, but **without** explicitly comparing every note.
Some ideas:

1. **Interval-based stats**  
   - **Mean Interval** (average absolute pitch difference between consecutive notes)  
   - **Interval Std** (standard deviation of those consecutive pitch differences)  
   - **Interval Skew** (skewness of the pitch-difference distribution)  
   These describe how “jumpy” or “smooth” the melodic shape is, even if we ignore exact note order.

2. **Pitch Contour “Slope”**  
   - Compute a simple measure of how often the melody moves up vs. down overall.  
   - For instance, `(number_of_ascents - number_of_descents) / total_intervals`.  
   - This single value can distinguish a mostly ascending line from a mostly descending one.

3. **Peak-to-Mean ratio** (or “Peakiness”)  
   - Ratio of max pitch to mean pitch (similarly for duration).  
   - Captures whether there’s a sudden leap far above the “average” pitch range.

4. **Duration variation (Relative)**  
   - Instead of raw `duration_mean`/`std`, we measure how a note’s duration compares to its neighbors 
     (e.g., average ratio of consecutive durations).  
   - This highlights a “staccato vs. legato” feel *without* requiring the entire sequence.

All these features retain some **sequence essence** (interval jumps, directional trends)
while still rolling everything into a small handful of numbers. That means we avoid
“point-by-point” comparisons of long MIDI files, yet capture more than a naive global mean
ever could.

**We need to accept some information loss**  
Any single-number compression inevitably loses detail. If speed and simplicity
are important, a carefully chosen scalar can still be ok for the task
