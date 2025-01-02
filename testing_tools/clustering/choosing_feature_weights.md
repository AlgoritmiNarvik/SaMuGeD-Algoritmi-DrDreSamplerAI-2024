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
