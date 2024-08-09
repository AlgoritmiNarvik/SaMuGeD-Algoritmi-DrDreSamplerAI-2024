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

def calculate_bar_length(time_signature, ticks_per_beat):
    numerator, denominator = time_signature
    return numerator * ticks_per_beat * 4 // denominator

def find_ngrams(sequence, n):
    ngrams = [tuple(sequence[i:i+n]) for i in range(len(sequence)-n+1)]
    return ngrams

def find_frequent_patterns(sequence, max_ngram_size, min_occurrences):
    longest_frequent_patterns = []
    ngram_frequencies = {}
    
    # Analyze n-grams from longest to shortest
    for n in range(max_ngram_size, 0, -1):
        ngrams = find_ngrams(sequence, n)
        ngram_counts = Counter(ngrams)
        frequent_patterns = [(ngram, count) for ngram, count in ngram_counts.items() if count >= min_occurrences]
        
        for pattern, count in frequent_patterns:
            if pattern not in ngram_frequencies:
                ngram_frequencies[pattern] = count

        if frequent_patterns:
            longest_frequent_patterns = frequent_patterns
            break  # Stop as soon as we find the longest frequent pattern

    return longest_frequent_patterns, ngram_frequencies

def segment_track(track, duration_patterns, pitch_patterns, bar_length, min_bars, max_bars, silent_regions):
    boundaries = set()
    
    # Add boundaries based on strongest patterns
    all_patterns = duration_patterns + pitch_patterns
    for pattern, _ in all_patterns[:20]:  # Use top 20 patterns
        for i, (note, start_time, duration, velocity) in enumerate(track):
            segment = track[i:i+len(pattern)]
            segment_durations = tuple(note[2] for note in segment)
            segment_pitches = tuple(note[0] for note in segment)
            if segment_durations == pattern or segment_pitches == pattern:
                if not any(s_start <= start_time < s_end for s_start, s_end in silent_regions):
                    boundaries.add(start_time)
                    boundaries.add(start_time + sum(d[2] for d in segment))
    
    # Add additional boundaries to satisfy min/max bar constraints
    boundaries = sorted(list(boundaries))
    filtered_boundaries = [boundaries[0]]
    for boundary in boundaries[1:]:
        if boundary - filtered_boundaries[-1] > max_bars * bar_length:
            # Add intermediate boundaries
            current = filtered_boundaries[-1]
            while current + max_bars * bar_length < boundary:
                current += max_bars * bar_length
                filtered_boundaries.append(current)
        if boundary - filtered_boundaries[-1] >= min_bars * bar_length:
            filtered_boundaries.append(boundary)
    
    return filtered_boundaries

def detect_silence(track, silence_threshold):
    silent_regions = []
    start = None
    for i, note in enumerate(track):
        if note[3] < silence_threshold:  # Using velocity as a proxy for silence
            if start is None:
                start = note[1]
        elif start is not None:
            silent_regions.append((start, note[1]))
            start = None
    return silent_regions

def save_boundaries(boundaries, filename):
    with open(filename, 'w') as f:
        json.dump(boundaries, f)

def load_boundaries(filename):
    with open(filename, 'r') as f:
        return json.load(f)

def extract_segments(track, boundaries):
    segments = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i+1]
        segment = [note for note in track if start <= note[1] < end]
        segments.append(segment)
    return segments

def visualize_segmentation(track, boundaries, bar_length, min_bars, max_bars):
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
            ax.text((start + end) / 2, ymax, f'{i+1}', 
                    horizontalalignment='center', verticalalignment='top')
        
        # Add bar lines
        max_time = max(note[1] for note in track)
        for bar in range(0, int(max_time), int(bar_length)):
            ax.axvline(x=bar, color='gray', linestyle=':', alpha=0.5, linewidth=0.5)
    
    plt.suptitle(f'Segmentation (Min: {min_bars} bars, Max: {max_bars} bars)')
    plt.tight_layout()
    plt.show()

def analyze_midi_file(midi_file, output_file, min_bars, max_bars, max_ngram_size, min_occurrences, silence_threshold):
    tracks, time_signature, ticks_per_beat = parse_midi_file(midi_file)
    bar_length = calculate_bar_length(time_signature, ticks_per_beat)
    
    all_track_boundaries = {}
    segment_reports = {}

    for track_num, track in tracks.items():
        print(f"Analyzing track {track_num}")
        
        # Analyze durations
        durations = [note[2] for note in track]
        duration_patterns, duration_frequencies = find_frequent_patterns(durations, max_ngram_size, min_occurrences)
        print(f"Found {len(duration_patterns)} duration patterns")
        
        # Analyze pitches
        pitches = [note[0] for note in track]
        pitch_patterns, pitch_frequencies = find_frequent_patterns(pitches, max_ngram_size, min_occurrences)
        print(f"Found {len(pitch_patterns)} pitch patterns")
        
        # Detect silent regions
        silent_regions = detect_silence(track, silence_threshold)

        # Pass silent regions to the segment_track function
        boundaries = segment_track(track, duration_patterns, pitch_patterns, bar_length, min_bars, max_bars, silent_regions)
        
        all_track_boundaries[track_num] = boundaries
        
        print(f"Found {len(boundaries)-1} segments in track {track_num}")
        visualize_segmentation(track, boundaries, bar_length, min_bars, max_bars)
        
        # Record segment report
        segment_reports[track_num] = {
            'duration_patterns': duration_patterns,
            'duration_frequencies': duration_frequencies,
            'pitch_patterns': pitch_patterns,
            'pitch_frequencies': pitch_frequencies,
        }
    
    save_boundaries(all_track_boundaries, output_file)
    print(f"Saved boundaries to {output_file}")
    
    # Generate segment report
    with open('segment_report.json', 'w') as f:
        json.dump(segment_reports, f, indent=4)
    print("Segment report saved to segment_report.json")

def save_segments_to_midi(original_midi, tracks, all_boundaries, output_file_path):
    """
    Save identified segments as a new MIDI file, including the original tracks.

    Args:
        original_midi (mido.MidiFile): The original MIDI file object.
        tracks (dict): Dictionary of track note information.
        all_boundaries (dict): Dictionary containing segment boundaries for each track.
        output_file_path (str): Path where the new MIDI file will be saved.

    Note:
        This function creates a new MIDI file with the original tracks and additional tracks for each identified segment.
        Each segment is represented as a separate track in the output MIDI file.
    """
    output_midi = mido.MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)

    # Copy all original tracks
    for track in original_midi.tracks:
        output_midi.tracks.append(track.copy())

    # Add segment tracks
    for track_num, boundaries in all_boundaries.items():
        original_track = tracks[track_num]
        for i, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            segment = [note for note in original_track if start <= note[1] < end]
            if not segment:
                continue  # Skip empty segments

            segment_track = mido.MidiTrack()
            segment_track.append(mido.MetaMessage('track_name', name=f'Segment {i+1}', time=0))
            
            # Add notes to segment track, ensuring they start at time 0
            current_time = 0
            for note, start_time, duration, velocity in segment:
                delta_time = start_time - start
                segment_track.append(mido.Message('note_on', note=note, velocity=velocity, time=delta_time))
                segment_track.append(mido.Message('note_off', note=note, velocity=0, time=duration))
                current_time = start_time + duration - start

            # Ensure all notes are turned off at the end of the segment
            segment_track.append(mido.MetaMessage('end_of_track', time=1))

            output_midi.tracks.append(segment_track)

            print(f"Added track for segment {i+1}: Start={start}, End={end}, Duration={end-start}")

    # Save the MIDI file
    output_midi.save(output_file_path)
    print(f"Original tracks and segments saved to {output_file_path}")

def extract_segments_from_file(midi_file, boundaries_file, track_num):
    tracks, _, _ = parse_midi_file(midi_file)
    boundaries = load_boundaries(boundaries_file)
    
    if str(track_num) in boundaries:
        track = tracks[track_num]
        track_boundaries = boundaries[str(track_num)]
        segments = extract_segments(track, track_boundaries)
        
        print(f"Extracted {len(segments)} segments from track {track_num}")
        return segments
    else:
        print(f"No boundaries found for track {track_num}")
        return []

# Main script
if __name__ == "__main__":
    # CONSTANTS
    MIDI_FILE = 'testing_tools/Manual_seg/take_on_me/track1.mid'
    OUTPUT_FILE = 'testing_tools/test_scripts/almaz_scripts/boundaries.json'
    SEGMENTS_OUTPUT_FILE = 'testing_tools/test_scripts/almaz_scripts/segments_output.mid'
    MIN_BARS = 2
    MAX_BARS = 8
    MAX_NGRAM_SIZE = 64  # Starting with a large size to find the longest patterns
    MIN_OCCURRENCES = 2
    SILENCE_THRESHOLD = 100
    TRACK_NUM = 0  # Change this to the desired track number
    
    # Analyze the MIDI file and save boundaries
    analyze_midi_file(MIDI_FILE, OUTPUT_FILE, MIN_BARS, MAX_BARS, MAX_NGRAM_SIZE, MIN_OCCURRENCES, SILENCE_THRESHOLD)

    # Load the original MIDI file
    original_midi = mido.MidiFile(MIDI_FILE)

    # Extract boundaries for each track
    tracks, _, _ = parse_midi_file(MIDI_FILE)
    all_boundaries = load_boundaries(OUTPUT_FILE)

    # Save segments as a new MIDI file
    save_segments_to_midi(original_midi, tracks, all_boundaries, SEGMENTS_OUTPUT_FILE)
