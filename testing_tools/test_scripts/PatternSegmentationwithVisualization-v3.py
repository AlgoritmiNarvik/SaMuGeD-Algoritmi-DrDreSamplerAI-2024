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
    used_indices = set()
    
    for length in range(max_length, min_length - 1, -1):
        for i in range(n - length + 1):
            if i in used_indices:
                continue
            pattern = tuple(tuple(bar['notes']) for bar in preprocessed_data[i:i+length] if bar['type'] == 'non_empty')
            if pattern:
                occurrences = [i]
                for j in range(i + 1, n - length + 1):
                    if j in used_indices:
                        continue
                    compare = tuple(tuple(bar['notes']) for bar in preprocessed_data[j:j+length] if bar['type'] == 'non_empty')
                    if len(pattern) == len(compare):
                        if all(compute_similarity(p, c) >= similarity_threshold for p, c in zip(pattern, compare)):
                            occurrences.append(j)
                
                if len(occurrences) > 1:
                    patterns[pattern] = occurrences
                    used_indices.update(range(occ, occ+length) for occ in occurrences)
    
    return {k: v for k, v in patterns.items() if len(v) > 1}

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
            if not current_phrase or i == current_phrase[-1] + 1:
                current_phrase.append(i)
            else:
                if len(current_phrase) >= 2:  # Only keep phrases of 2 or more bars
                    phrases.append(current_phrase)
                current_phrase = [i]
        elif current_phrase:
            if len(current_phrase) >= 2:
                phrases.append(current_phrase)
            current_phrase = []
    
    if current_phrase and len(current_phrase) >= 2:
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
    pattern_boundaries = []
    
    # Classify repeating patterns
    for pattern_idx, (pattern, occurrences) in enumerate(repeating_patterns.items()):
        for start in occurrences:
            end = start + len(pattern) - 1
            classifications.append({
                'type': 'Repeating Pattern',
                'start': preprocessed_data[start]['start'],
                'end': preprocessed_data[end]['end'],
                'length': len(pattern),
                'description': f'Repeating pattern {pattern_idx + 1} of {len(pattern)} bars',
                'pattern_id': pattern_idx
            })
            pattern_boundaries.append({
                'type': 'Pattern Start',
                'position': preprocessed_data[start]['start'],
                'pattern_id': pattern_idx,
                'description': f'P{pattern_idx + 1} Start'
            })
            pattern_boundaries.append({
                'type': 'Pattern End',
                'position': preprocessed_data[end]['end'],
                'pattern_id': pattern_idx,
                'description': f'P{pattern_idx + 1} End'
            })
    
    # Classify melodic phrases
    for phrase_idx, phrase in enumerate(melodic_phrases):
        classifications.append({
            'type': 'Melodic Phrase',
            'start': preprocessed_data[phrase[0]]['start'],
            'end': preprocessed_data[phrase[-1]]['end'],
            'length': len(phrase),
            'description': f'Melodic phrase {phrase_idx + 1} of {len(phrase)} bars'
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
    
    return sorted(classifications, key=lambda x: x['start']), sorted(pattern_boundaries, key=lambda x: x['position'])

def smart_text_placement(ax, texts, positions, y_offset=0, max_attempts=100):
    """
    Places text labels on the plot, avoiding overlaps.

    Args:
        ax (matplotlib.axes.Axes): Axes to place the text on.
        texts (list): List of text strings to place.
        positions (list): List of (x, y) positions for each text.
        y_offset (float): Initial y-offset for text placement.
        max_attempts (int): Maximum number of attempts to place each text.

    Returns:
        list: List of placed matplotlib.text.Text objects.
    """
    placed_texts = []
    for text, pos in zip(texts, positions):
        x, y = pos
        for i in range(max_attempts):
            t = ax.text(x, y + (i + y_offset) * 0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]), text,
                        rotation=90, va='bottom', ha='center', fontsize=8)
            renderer = ax.figure.canvas.get_renderer()
            bbox = t.get_window_extent(renderer=renderer).transformed(ax.transData.inverted())
            if not any(bbox.overlaps(pt.get_window_extent(renderer=renderer).transformed(ax.transData.inverted()))
                       for pt in placed_texts):
                placed_texts.append(t)
                break
            t.remove()
    return placed_texts

def visualize_track_segmentation(notes, classifications, pattern_boundaries, ticks_per_bar):
    """
    Visualize the track with segmentation, including final segmentation boundaries, repeating patterns, and pattern start/end markers.

    Args:
        notes (list): List of MIDI note objects.
        classifications (list): Segment classifications.
        pattern_boundaries (list): Pattern start and end points.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # Plot notes
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    # Plot segments
    pattern_colors = plt.cm.Set2(np.linspace(0, 1, len(set(c['pattern_id'] for c in classifications if 'pattern_id' in c))))
    color_map = {'Melodic Phrase': 'lightgreen', 'Empty': 'lightgray'}
    
    for segment in classifications:
        start_tick = segment['start']
        end_tick = segment['end']
        if segment['type'] == 'Repeating Pattern':
            color = pattern_colors[segment['pattern_id']]
        else:
            color = color_map.get(segment['type'], 'white')
        ax.axvspan(start_tick, end_tick, facecolor=color, alpha=0.3)
    
    # Add final segmentation boundaries
    for segment in classifications:
        ax.axvline(x=segment['start'], color='red', linestyle='--', alpha=0.7)
    ax.axvline(x=classifications[-1]['end'], color='red', linestyle='--', alpha=0.7)
    
    # Add pattern start and end markers
    for boundary in pattern_boundaries:
        if boundary['type'] == 'Pattern Start':
            ax.axvline(x=boundary['position'], color='green', linestyle='-', linewidth=4)
        else:  # Pattern End
            ax.axvline(x=boundary['position'], color='orange', linestyle='-', linewidth=4)
    
    # Smart text placement for segment classifications
    texts = [f"{s['type']}\n{s['length']} bars" for s in classifications]
    positions = [(s['start'], ax.get_ylim()[1]) for s in classifications]
    smart_text_placement(ax, texts, positions)
    
    # Smart text placement for pattern boundaries
    boundary_texts = [b['description'] for b in pattern_boundaries]
    boundary_positions = [(b['position'], ax.get_ylim()[1]) for b in pattern_boundaries]
    smart_text_placement(ax, boundary_texts, boundary_positions, y_offset=3)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Track Segmentation with Repeating Patterns and Boundaries')
    
    plt.tight_layout()
    plt.show()

def visualize_raw_notes(notes, ticks_per_bar):
    """
    Visualizes the raw MIDI notes.

    Args:
        notes (list): List of MIDI note objects.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Raw Note Data')
    
    max_time = max(note.end for note in notes)
    for bar in range(0, int(max_time), ticks_per_bar):
        ax.axvline(x=bar, color='gray', linestyle=':', alpha=0.5)
    
    plt.tight_layout()
    plt.show()

def visualize_repeating_patterns(notes, repeating_patterns, ticks_per_bar):
    """
    Visualizes the repeating patterns in a MIDI track.

    Args:
        notes (list): List of MIDI note objects.
        repeating_patterns (dict): Dictionary of repeating patterns and their occurrences.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    pattern_colors = plt.cm.Set2(np.linspace(0, 1, len(repeating_patterns)))
    
    for idx, (pattern, occurrences) in enumerate(repeating_patterns.items()):
        color = pattern_colors[idx]
        for start in occurrences:
            end = start + len(pattern) * ticks_per_bar
            ax.axvspan(start * ticks_per_bar, end * ticks_per_bar, facecolor=color, alpha=0.3)
            ax.text(start * ticks_per_bar, ax.get_ylim()[1], f'P{idx+1}', rotation=90, va='top', ha='right', fontsize=8)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Repeating Patterns')
    
    plt.tight_layout()
    plt.show()

def visualize_melodic_phrases(notes, melodic_phrases, ticks_per_bar):
    """
    Visualizes the melodic phrases in a MIDI track.

    Args:
        notes (list): List of MIDI note objects.
        melodic_phrases (list): List of melodic phrases.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    for idx, phrase in enumerate(melodic_phrases):
        start = phrase[0] * ticks_per_bar
        end = (phrase[-1] + 1) * ticks_per_bar
        ax.axvspan(start, end, facecolor='lightgreen', alpha=0.3)
        ax.text(start, ax.get_ylim()[1], f'M{idx+1}', rotation=90, va='top', ha='right', fontsize=8)
        ax.axvline(x=start, color='green', linestyle='--', alpha=0.7)
        ax.axvline(x=end, color='green', linestyle='--', alpha=0.7)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Melodic Phrases')
    
    plt.tight_layout()
    plt.show()

def visualize_final_segmentation(notes, classifications, ticks_per_bar):
    """
    Visualizes the final segmentation of a MIDI track.

    Args:
        notes (list): List of MIDI note objects.
        classifications (list): List of segment classifications.
        ticks_per_bar (int): Number of ticks per bar.
    """
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    texts = []
    positions = []
    for segment in classifications:
        ax.axvline(x=segment['start'], color='red', linestyle='--', alpha=0.7)
        texts.append(f"{segment['type']}\n{segment['length']} bars")
        positions.append((segment['start'], ax.get_ylim()[1]))
    
    ax.axvline(x=classifications[-1]['end'], color='red', linestyle='--', alpha=0.7)
    
    smart_text_placement(ax, texts, positions)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Final Segmentation')
    
    plt.tight_layout()
    plt.show()

def analyze_midi_track(midi_file, min_pattern_length=2, max_pattern_length=8):
    """
    Analyzes a MIDI track for patterns and segments.

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
        print("Warning: Time signature information not found. Assuming 4/4 time signature.")
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
        
        classifications, pattern_boundaries = classify_segments(preprocessed_data, repeating_patterns, melodic_phrases)
        
        visualize_raw_notes(notes, ticks_per_bar)
        visualize_repeating_patterns(notes, repeating_patterns, ticks_per_bar)
        visualize_melodic_phrases(notes, melodic_phrases, ticks_per_bar)
        visualize_final_segmentation(notes, classifications, ticks_per_bar)
        
        results.append({
            'track_idx': track_idx,
            'preprocessed_data': preprocessed_data,
            'repeating_patterns': repeating_patterns,
            'melodic_phrases': melodic_phrases,
            'classifications': classifications,
            'pattern_boundaries': pattern_boundaries
        })
    
    return results

# Usage
midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
analysis_results = analyze_midi_track(midi_file, min_pattern_length=1, max_pattern_length=2)

for result in analysis_results:
    print(f"Track {result['track_idx']}:")
    print(f"  Found {len(result['repeating_patterns'])} repeating patterns")
    print(f"  Found {len(result['melodic_phrases'])} melodic phrases")
    print("  Segment classifications:")
    for classification in result['classifications']:
        print(f"    {classification['type']} ({classification['length']} bars): {classification['description']}")
    print("  Pattern boundaries:")
    for boundary in result['pattern_boundaries']:
        print(f"    {boundary['type']} at position {boundary['position']}: {boundary['description']}")
    print()
