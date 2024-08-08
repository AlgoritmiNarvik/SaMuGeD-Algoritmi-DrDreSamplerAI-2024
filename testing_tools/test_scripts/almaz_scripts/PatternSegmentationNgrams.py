import mido
import numpy as np
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import json

def parse_midi_file(midi_file):
    mid = mido.MidiFile(midi_file)
    tracks = defaultdict(list)
    time_signature = None
    ticks_per_beat = mid.ticks_per_beat
    
    for i, track in enumerate(mid.tracks):
        time = 0
        active_notes = {}
        for msg in track:
            time += msg.time
            if msg.type == 'time_signature':
                time_signature = (msg.numerator, msg.denominator)
            elif msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = (time, msg.velocity)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if msg.note in active_notes:
                    start_time, velocity = active_notes[msg.note]
                    duration = time - start_time
                    tracks[i].append((msg.note, start_time, duration, velocity))
                    del active_notes[msg.note]
    
    if time_signature is None:
        time_signature = (4, 4)  # Default to 4/4 if not specified
    
    return tracks, time_signature, ticks_per_beat

def n_grams(sequence, n):
    """Generate n-grams from a sequence."""
    return list(zip(*[sequence[i:] for i in range(n)]))

def find_longest_patterns(sequence, min_count=2):
    """Find the longest repeated patterns in a sequence."""
    max_len = len(sequence)
    longest_patterns = []
    
    for n in range(1, max_len):
        ngrams = n_grams(sequence, n)
        counter = Counter(ngrams)
        for pattern, count in counter.items():
            if count >= min_count:
                longest_patterns.append((pattern, count))
    
    longest_patterns.sort(key=lambda x: (-len(x[0]), -x[1]))
    
    return longest_patterns

def segment_by_durations(track, min_count=2):
    """Segment the track based on repeated duration patterns."""
    durations = [note[2] for note in track]
    duration_patterns = find_longest_patterns(durations, min_count=min_count)
    
    segments = []
    used_indexes = set()
    boundaries = []
    
    for pattern, count in duration_patterns:
        pattern_length = len(pattern)
        indexes = [i for i in range(len(durations) - pattern_length + 1) 
                   if tuple(durations[i:i+pattern_length]) == pattern]
        for index in indexes:
            if index not in used_indexes:
                segments.append(track[index:index+pattern_length])
                used_indexes.update(range(index, index+pattern_length))
                boundaries.append(track[index][1])  # Start time of segment
    
    boundaries.sort()
    return segments, boundaries

def analyze_segments(segments, min_count=2):
    """Analyze note patterns within each segment."""
    segment_reports = []
    
    for segment in segments:
        pitches = [note[0] for note in segment]
        pitch_patterns = find_longest_patterns(pitches, min_count=min_count)
        segment_reports.append({
            'segment': segment,
            'pitch_patterns': pitch_patterns
        })
    
    return segment_reports

def visualize_segmentation(track, boundaries, ticks_per_beat):
    plt.figure(figsize=(15, 10))
    
    # Plot pitches
    ax1 = plt.subplot(2, 1, 1)
    ax1.plot([note[1] for note in track], [note[0] for note in track], 'b.')
    ax1.set_ylabel('MIDI Note')
    ax1.set_title('Pitch Segmentation')
    
    # Plot durations
    ax2 = plt.subplot(2, 1, 2)
    ax2.plot([note[1] for note in track], [note[2] for note in track], 'r.')
    ax2.set_ylabel('Duration (ticks)')
    ax2.set_xlabel('Time (ticks)')
    ax2.set_title('Duration Segmentation')
    
    # Add segmentation to both plots
    for ax in [ax1, ax2]:
        ymin, ymax = ax.get_ylim()
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i+1]
            color = 'lightblue' if i % 2 == 0 else 'lightgreen'
            ax.axvspan(start, end, alpha=0.3, color=color)
            ax.text((start + end) / 2, ymax, f'Segment {i+1}', 
                    horizontalalignment='center', verticalalignment='top')
        
        # Add bar lines
        max_time = max(note[1] for note in track)
        bar_length = ticks_per_beat * 4  # Assume 4/4 time signature
        for bar in range(0, int(max_time), int(bar_length)):
            ax.axvline(x=bar, color='gray', linestyle=':', alpha=0.5, linewidth=0.5)
    
    plt.suptitle('Segmentation Visualization')
    plt.tight_layout()
    plt.show()

def save_report(reports, filename):
    """Save the analysis report to a JSON file."""
    with open(filename, 'w') as f:
        json.dump(reports, f, indent=4)

def analyze_midi_file(midi_file, report_file):
    tracks, time_signature, ticks_per_beat = parse_midi_file(midi_file)
    
    all_reports = {}
    
    for track_num, track in tracks.items():
        print(f"Analyzing track {track_num}")
        
        # Segment by durations
        segments, boundaries = segment_by_durations(track)
        print(f"Found {len(segments)} rhythmic segments in track {track_num}")
        
        # Visualize segmentation
        visualize_segmentation(track, boundaries, ticks_per_beat)
        
        # Analyze note patterns within each segment
        reports = analyze_segments(segments)
        all_reports[track_num] = reports
        
        for i, report in enumerate(reports):
            print(f"Segment {i+1} has {len(report['pitch_patterns'])} pitch patterns")
    
    save_report(all_reports, report_file)
    print(f"Saved analysis report to {report_file}")

# Usage
midi_file = 'archived/i_am_trying_sf_segmenter_a_bit/Something_in_the_Way.mid'
report_file = 'testing_tools/test_scripts/almaz_scripts/midi_analysis_report.json'

# Analyze the MIDI file and save the report
analyze_midi_file(midi_file, report_file)
