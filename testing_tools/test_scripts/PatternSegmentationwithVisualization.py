import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt
from miditoolkit.midi.parser import MidiFile
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN

def midi_to_pcp(notes, start_time, end_time):
    """Convert MIDI notes to Pitch Class Profile."""
    pcp = np.zeros(12)
    for note in notes:
        if start_time <= note.start < end_time:
            pcp[note.pitch % 12] += note.end - note.start
    return pcp / np.sum(pcp) if np.sum(pcp) > 0 else pcp

def compute_pcps(notes, ticks_per_bar):
    """Compute PCP for each bar."""
    pcps = []
    start_time = notes[0].start
    end_time = notes[-1].end
    for bar_start in range(start_time, end_time, ticks_per_bar):
        bar_end = bar_start + ticks_per_bar
        pcp = midi_to_pcp(notes, bar_start, bar_end)
        pcps.append(pcp)
    return np.array(pcps)

def find_repeating_patterns(pcps, min_length=2, max_length=8):
    """Find repeating PCP patterns."""
    patterns = defaultdict(list)
    n = len(pcps)
    for length in range(min_length, min(max_length, n // 2) + 1):
        for i in range(n - length + 1):
            pattern = tuple(map(tuple, pcps[i:i+length]))
            patterns[pattern].append(i)
    return {k: v for k, v in patterns.items() if len(v) > 1}

def segment_non_repeating(pcps, repeating_indices):
    """Segment the non-repeating parts."""
    all_indices = set(range(len(pcps)))
    non_repeating = list(all_indices - set(repeating_indices))
    return [list(group) for group in np.split(non_repeating, np.where(np.diff(non_repeating) != 1)[0] + 1)]

def detect_boundaries(pcps):
    """Detect segment boundaries based on PCP changes."""
    differences = np.sum(np.abs(np.diff(pcps, axis=0)), axis=1)
    peaks, _ = find_peaks(differences, height=np.mean(differences), distance=2)
    return peaks

def cluster_segments(pcps, segments):
    """Cluster similar non-repeating segments."""
    segment_features = [np.mean(pcps[seg], axis=0) for seg in segments]
    clustering = DBSCAN(eps=0.5, min_samples=2).fit(segment_features)
    return clustering.labels_

def visualize_track_with_patterns(notes, repeating_patterns, non_repeating_segments, boundaries, ticks_per_bar):
    """Visualize the track with patterns, non-repeating segments, and boundaries."""
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # Plot notes
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=1, color='gray', alpha=0.5)
    
    # Plot repeating patterns
    colors = plt.cm.rainbow(np.linspace(0, 1, len(repeating_patterns)))
    for i, ((pattern, occurrences), color) in enumerate(zip(repeating_patterns.items(), colors)):
        pattern_name = f"P{i+1}"
        for start in occurrences:
            end = start + len(pattern)
            start_tick = start * ticks_per_bar
            end_tick = end * ticks_per_bar
            ax.axvspan(start_tick, end_tick, facecolor=color, alpha=0.3)
            ax.text(start_tick, ax.get_ylim()[1], f'{pattern_name}', rotation=90, 
                    va='bottom', color=color, fontweight='bold')
    
    # Plot non-repeating segments
    non_repeating_colors = plt.cm.Pastel1(np.linspace(0, 1, len(non_repeating_segments)))
    for i, (segment, color) in enumerate(zip(non_repeating_segments, non_repeating_colors)):
        start_tick = segment[0] * ticks_per_bar
        end_tick = (segment[-1] + 1) * ticks_per_bar
        ax.axvspan(start_tick, end_tick, facecolor=color, alpha=0.3)
        ax.text(start_tick, ax.get_ylim()[1], f'NR{i+1}', rotation=90, 
                va='bottom', color=color, fontweight='bold')
    
    # Plot boundaries
    for boundary in boundaries:
        boundary_tick = boundary * ticks_per_bar
        ax.axvline(x=boundary_tick, color='red', linestyle='--', alpha=0.7)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Track with Patterns and Segments')
    
    plt.tight_layout()
    plt.show()

def analyze_midi_track(midi_file, min_pattern_length=2, max_pattern_length=8):
    """Analyze a MIDI track for patterns and segments."""
    midi_obj = MidiFile(midi_file)
    ticks_per_beat = midi_obj.ticks_per_beat
    time_signature = midi_obj.time_signature_changes[0]
    ticks_per_bar = ticks_per_beat * time_signature.numerator
    
    results = []
    
    for track_idx, track in enumerate(midi_obj.instruments):
        if track.is_drum:
            continue
        
        notes = sorted(track.notes, key=lambda x: x.start)
        pcps = compute_pcps(notes, ticks_per_bar)
        
        repeating_patterns = find_repeating_patterns(pcps, min_pattern_length, max_pattern_length)
        repeating_indices = set(sum([occ for occ in repeating_patterns.values()], []))
        
        non_repeating_segments = segment_non_repeating(pcps, repeating_indices)
        
        boundaries = detect_boundaries(pcps)
        
        cluster_labels = cluster_segments(pcps, non_repeating_segments)
        
        visualize_track_with_patterns(notes, repeating_patterns, non_repeating_segments, boundaries, ticks_per_bar)
        
        results.append({
            'track_idx': track_idx,
            'repeating_patterns': repeating_patterns,
            'non_repeating_segments': non_repeating_segments,
            'boundaries': boundaries,
            'cluster_labels': cluster_labels
        })
    
    return results

# Usage
midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
analysis_results = analyze_midi_track(midi_file, min_pattern_length=1, max_pattern_length=4)

for result in analysis_results:
    print(f"Track {result['track_idx']}:")
    print(f"  Found {len(result['repeating_patterns'])} repeating patterns")
    print(f"  Found {len(result['non_repeating_segments'])} non-repeating segments")
    print(f"  Detected {len(result['boundaries'])} segment boundaries")
    print()
    