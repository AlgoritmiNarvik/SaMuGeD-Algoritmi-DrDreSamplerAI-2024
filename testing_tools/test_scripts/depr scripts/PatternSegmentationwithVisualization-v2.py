import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt
from miditoolkit.midi.parser import MidiFile
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN

def is_bar_empty(notes, bar_start, bar_end):
    """
    Check if a bar is empty.

    Args:
        notes (list): List of MIDI note objects.
        bar_start (int): Start time of the bar in ticks.
        bar_end (int): End time of the bar in ticks.

    Returns:
        bool: True if the bar is empty, False otherwise.
    """
    return all(note.end <= bar_start or note.start >= bar_end for note in notes)

def extract_note_sequence(notes, bar_start, bar_end):
    """
    Extract a sequence of notes from a bar.

    Args:
        notes (list): List of MIDI note objects.
        bar_start (int): Start time of the bar in ticks.
        bar_end (int): End time of the bar in ticks.

    Returns:
        list: Sequence of (pitch, start_time, duration) tuples.
    """
    return [(note.pitch, note.start - bar_start, note.end - note.start) 
            for note in notes if bar_start <= note.start < bar_end]

def preprocess_midi_track(notes, ticks_per_bar):
    """
    Preprocess MIDI track data.

    Args:
        notes (list): List of MIDI note objects.
        ticks_per_bar (int): Number of ticks per bar.

    Returns:
        list: Preprocessed data for each bar.
    """
    start_time = notes[0].start if notes else 0
    end_time = notes[-1].end if notes else 0
    
    preprocessed_data = []
    
    for bar_start in range(start_time, end_time, ticks_per_bar):
        bar_end = bar_start + ticks_per_bar
        
        if is_bar_empty(notes, bar_start, bar_end):
            preprocessed_data.append({
                'start': bar_start,
                'end': bar_end,
                'type': 'empty',
                'notes': []
            })
        else:
            note_sequence = extract_note_sequence(notes, bar_start, bar_end)
            preprocessed_data.append({
                'start': bar_start,
                'end': bar_end,
                'type': 'non_empty',
                'notes': note_sequence
            })
    
    return preprocessed_data

def compute_similarity(seq1, seq2):
    """
    Compute similarity between two note sequences.

    Args:
        seq1 (list): First note sequence.
        seq2 (list): Second note sequence.

    Returns:
        float: Similarity score between 0 (completely different) and 1 (identical).
    """
    if not seq1 and not seq2:  # Both sequences are empty
        return 1.0
    if not seq1 or not seq2:  # One sequence is empty, the other is not
        return 0.0
    
    pitches1 = [note[0] for note in seq1]
    pitches2 = [note[0] for note in seq2]
    
    # Use dynamic time warping or other advanced similarity measure here
    # For simplicity, we'll use a basic pitch sequence comparison
    matches = sum(p1 == p2 for p1, p2 in zip(pitches1, pitches2))
    return matches / max(len(pitches1), len(pitches2))

def find_repeating_patterns(preprocessed_data, min_length=2, max_length=8, similarity_threshold=0.8):
    """
    Find repeating patterns in preprocessed data.

    Args:
        preprocessed_data (list): Preprocessed bar data.
        min_length (int): Minimum pattern length in bars.
        max_length (int): Maximum pattern length in bars.
        similarity_threshold (float): Threshold for considering patterns similar.

    Returns:
        dict: Repeating patterns and their occurrences.
    """
    patterns = defaultdict(list)
    n = len(preprocessed_data)
    
    for length in range(min_length, min(max_length, n // 2) + 1):
        for i in range(n - length + 1):
            pattern = tuple(tuple(bar['notes']) for bar in preprocessed_data[i:i+length] if bar['type'] == 'non_empty')
            if pattern:
                for j in range(i + 1, n - length + 1):
                    compare = tuple(tuple(bar['notes']) for bar in preprocessed_data[j:j+length] if bar['type'] == 'non_empty')
                    if len(pattern) == len(compare):
                        if all(compute_similarity(p, c) >= similarity_threshold for p, c in zip(pattern, compare)):
                            patterns[pattern].extend([i, j])
                            break
    
    return {k: sorted(set(v)) for k, v in patterns.items() if len(v) > 1}

def segment_melodic_phrases(preprocessed_data, repeating_indices):
    """
    Segment the non-repeating parts into melodic phrases.

    Args:
        preprocessed_data (list): Preprocessed bar data.
        repeating_indices (set): Indices of bars in repeating patterns.

    Returns:
        list: List of melodic phrase segments.
    """
    all_indices = set(range(len(preprocessed_data)))
    non_repeating = list(all_indices - repeating_indices)
    
    phrases = []
    current_phrase = []
    
    for i in non_repeating:
        if preprocessed_data[i]['type'] == 'non_empty':
            current_phrase.append(i)
        elif current_phrase:
            phrases.append(current_phrase)
            current_phrase = []
    
    if current_phrase:
        phrases.append(current_phrase)
    
    return phrases

def classify_segments(preprocessed_data, repeating_patterns, melodic_phrases):
    """
    Classify segments based on their musical characteristics.

    Args:
        preprocessed_data (list): Preprocessed bar data.
        repeating_patterns (dict): Repeating patterns and their occurrences.
        melodic_phrases (list): List of melodic phrase segments.

    Returns:
        list: Segment classifications.
    """
    classifications = []
    
    # Classify repeating patterns
    for pattern, occurrences in repeating_patterns.items():
        for start in occurrences:
            classifications.append({
                'type': 'Repeating Pattern',
                'start': preprocessed_data[start]['start'],
                'end': preprocessed_data[start + len(pattern) - 1]['end'],
                'length': len(pattern),
                'description': f'Repeating pattern of {len(pattern)} bars'
            })
    
    # Classify melodic phrases
    for phrase in melodic_phrases:
        classifications.append({
            'type': 'Melodic Phrase',
            'start': preprocessed_data[phrase[0]]['start'],
            'end': preprocessed_data[phrase[-1]]['end'],
            'length': len(phrase),
            'description': f'Melodic phrase of {len(phrase)} bars'
        })
    
    # Classify empty segments
    for i, bar in enumerate(preprocessed_data):
        if bar['type'] == 'empty':
            classifications.append({
                'type': 'Empty',
                'start': bar['start'],
                'end': bar['end'],
                'length': 1,
                'description': 'Empty bar'
            })
    
    return sorted(classifications, key=lambda x: x['start'])

def visualize_track_segmentation(notes, classifications, ticks_per_bar):
    """
    Visualize the track with segmentation.

    Args:
        notes (list): List of MIDI note objects.
        classifications (list): Segment classifications.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # Plot notes
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=5, color='blue', alpha=0.5)
    
    # Plot segments
    colors = plt.cm.Set3(np.linspace(0, 1, 3))
    color_map = {'Repeating Pattern': colors[0], 'Melodic Phrase': colors[1], 'Empty': colors[2]}
    
    for segment in classifications:
        start_tick = segment['start']
        end_tick = segment['end']
        ax.axvspan(start_tick, end_tick, facecolor=color_map[segment['type']], alpha=0.3)
        ax.text(start_tick, ax.get_ylim()[1], f"{segment['type']}\n{segment['length']} bars", rotation=90, 
                va='bottom', color=color_map[segment['type']], fontweight='bold')
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Track Segmentation')
    
    plt.tight_layout()
    plt.show()

def analyze_midi_track(midi_file, min_pattern_length=2, max_pattern_length=8):
    """
    Analyze a MIDI track for patterns and segments.

    Args:
        midi_file (str): Path to the MIDI file.
        min_pattern_length (int): Minimum pattern length in bars.
        max_pattern_length (int): Maximum pattern length in bars.

    Returns:
        list: Analysis results for each track.
    """
    midi_obj = MidiFile(midi_file)
    ticks_per_beat = midi_obj.ticks_per_beat
    time_signature = midi_obj.time_signature_changes[0] if midi_obj.time_signature_changes else None
    
    if time_signature is None:
        print("Warning: No time signature found. Assuming 4/4 time signature.")
        ticks_per_bar = ticks_per_beat * 4
    else:
        ticks_per_bar = ticks_per_beat * time_signature.numerator
    
    results = []
    
    for track_idx, track in enumerate(midi_obj.instruments):
        if track.is_drum:
            continue
        
        notes = sorted(track.notes, key=lambda x: x.start)
        if not notes:
            print(f"Warning: Track {track_idx} is empty. Skipping analysis.")
            continue
        
        preprocessed_data = preprocess_midi_track(notes, ticks_per_bar)
        
        repeating_patterns = find_repeating_patterns(preprocessed_data, min_pattern_length, max_pattern_length)
        repeating_indices = set(sum([occ for occ in repeating_patterns.values()], []))
        
        melodic_phrases = segment_melodic_phrases(preprocessed_data, repeating_indices)
        
        classifications = classify_segments(preprocessed_data, repeating_patterns, melodic_phrases)
        
        visualize_track_segmentation(notes, classifications, ticks_per_bar)
        
        results.append({
            'track_idx': track_idx,
            'preprocessed_data': preprocessed_data,
            'repeating_patterns': repeating_patterns,
            'melodic_phrases': melodic_phrases,
            'classifications': classifications
        })
    
    return results

# Usage
midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
analysis_results = analyze_midi_track(midi_file, min_pattern_length=4, max_pattern_length=4)

for result in analysis_results:
    print(f"Track {result['track_idx']}:")
    print(f"  Found {len(result['repeating_patterns'])} repeating patterns")
    print(f"  Found {len(result['melodic_phrases'])} melodic phrases")
    print("  Segment classifications:")
    for classification in result['classifications']:
        print(f"    {classification['type']} ({classification['length']} bars): {classification['description']}")
    print()
    