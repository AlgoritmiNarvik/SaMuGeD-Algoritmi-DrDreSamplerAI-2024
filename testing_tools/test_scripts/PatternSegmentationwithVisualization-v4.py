import numpy as np
from collections import defaultdict
from sklearn.cluster import AgglomerativeClustering
from difflib import SequenceMatcher
from miditoolkit.midi.parser import MidiFile
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

def is_bar_empty(notes, bar_start, bar_end):
    return all(note.end <= bar_start or note.start >= bar_end for note in notes)

def extract_note_sequence(notes, bar_start, bar_end):
    return [(note.pitch, note.start - bar_start, note.end - note.start) 
            for note in notes if bar_start <= note.start < bar_end]

def preprocess_midi_track(notes, ticks_per_bar):
    start_time = notes[0].start if notes else 0
    end_time = notes[-1].end if notes else 0
    
    preprocessed_data = []
    empty_segment_start = None
    
    for bar_start in range(start_time, end_time, ticks_per_bar):
        bar_end = bar_start + ticks_per_bar
        
        if is_bar_empty(notes, bar_start, bar_end):
            if empty_segment_start is None:
                empty_segment_start = bar_start
        else:
            if empty_segment_start is not None:
                preprocessed_data.append({
                    'start': empty_segment_start,
                    'end': bar_start,
                    'type': 'empty',
                    'notes': []
                })
                empty_segment_start = None
            
            note_sequence = extract_note_sequence(notes, bar_start, bar_end)
            preprocessed_data.append({
                'start': bar_start,
                'end': bar_end,
                'type': 'non_empty',
                'notes': note_sequence
            })
    
    if empty_segment_start is not None:
        preprocessed_data.append({
            'start': empty_segment_start,
            'end': end_time,
            'type': 'empty',
            'notes': []
        })
    
    return preprocessed_data

def compute_similarity(seq1, seq2):
    if not seq1 and not seq2:  # Both sequences are empty
        return 1.0
    if not seq1 or not seq2:  # One sequence is empty, the other is not
        return 0.0
    
    # Compute pitch similarity
    pitches1 = [note[0] for note in seq1]
    pitches2 = [note[0] for note in seq2]
    pitch_similarity = SequenceMatcher(None, pitches1, pitches2).ratio()
    
    # Compute duration similarity
    durations1 = [note[2] for note in seq1]
    durations2 = [note[2] for note in seq2]
    duration_similarity = 1 - sum(abs(d1 - d2) for d1, d2 in zip(durations1, durations2)) / sum(durations1 + durations2)
    
    # Compute interval similarity
    intervals1 = [seq1[i+1][0] - seq1[i][0] for i in range(len(seq1)-1)]
    intervals2 = [seq2[i+1][0] - seq2[i][0] for i in range(len(seq2)-1)]
    interval_similarity = SequenceMatcher(None, intervals1, intervals2).ratio()
    
    # Compute rhythmic pattern similarity
    rhythm1 = [note[2] for note in seq1]
    rhythm2 = [note[2] for note in seq2]
    rhythm_similarity = SequenceMatcher(None, rhythm1, rhythm2).ratio()
    
    # Compute overall similarity
    weights = [0.69, 0.1, 0.01, 0.2]  # Assign weights to different similarity aspects
    similarity_scores = [pitch_similarity, duration_similarity, interval_similarity, rhythm_similarity]
    overall_similarity = sum(weight * score for weight, score in zip(weights, similarity_scores))
    
    return overall_similarity

def segment_melodic_phrases_advanced(preprocessed_data, notes, ticks_per_bar, min_phrase_length=2, max_phrase_length=8):
    phrases = []
    start_idx = 0
    
    while start_idx < len(preprocessed_data):
        end_idx = start_idx + 1
        
        while end_idx < len(preprocessed_data) and end_idx - start_idx + 1 <= max_phrase_length:
            if preprocessed_data[end_idx]['type'] == 'empty':
                break
            
            # Check for melodic continuity
            if not is_melodically_continuous(notes, preprocessed_data[end_idx - 1]['end'], preprocessed_data[end_idx]['start']):
                break
            
            # Check for rhythmic continuity
            if not is_rhythmically_continuous(notes, preprocessed_data[end_idx - 1]['end'], preprocessed_data[end_idx]['start']):
                break
            
            end_idx += 1
        
        if end_idx - start_idx >= min_phrase_length:
            phrases.append(list(range(start_idx, end_idx)))
        
        start_idx = end_idx
    
    return phrases

def is_melodically_continuous(notes, prev_end, curr_start):
    prev_notes = [note for note in notes if prev_end <= note.start < curr_start]
    curr_notes = [note for note in notes if curr_start <= note.start < curr_start + 200]  # Consider notes within 200 ticks
    
    if not prev_notes or not curr_notes:
        return False
    
    prev_pitch = prev_notes[-1].pitch
    curr_pitch = curr_notes[0].pitch
    
    pitch_diff = abs(curr_pitch - prev_pitch)
    
    return pitch_diff <= 2  # Allow a maximum pitch difference of 2 semitones for melodic continuity

def is_rhythmically_continuous(notes, prev_end, curr_start):
    prev_notes = [note for note in notes if prev_end - 200 <= note.start < prev_end]  # Consider notes within 200 ticks
    curr_notes = [note for note in notes if curr_start <= note.start < curr_start + 200]  # Consider notes within 200 ticks
    
    if not prev_notes or not curr_notes:
        return False
    
    prev_duration = prev_notes[-1].end - prev_notes[-1].start
    curr_duration = curr_notes[0].end - curr_notes[0].start
    
    duration_ratio = max(prev_duration, curr_duration) / min(prev_duration, curr_duration)
    
    return duration_ratio <= 2  # Allow a maximum duration ratio of 2 for rhythmic continuity

def find_repeating_patterns_sia(preprocessed_data, notes, ticks_per_bar, min_pattern_length=2, max_pattern_length=8, similarity_threshold=0.8):
    patterns = defaultdict(list)
    
    for start in range(len(preprocessed_data)):
        for end in range(start + min_pattern_length, min(start + max_pattern_length + 1, len(preprocessed_data))):
            if preprocessed_data[end - 1]['type'] == 'empty':
                continue
            
            pattern = tuple(tuple(bar['notes']) for bar in preprocessed_data[start:end] if bar['type'] == 'non_empty')
            if pattern:
                patterns[pattern].append(start)
    
    # Filter patterns based on occurrence count
    frequent_patterns = {k: v for k, v in patterns.items() if len(v) > 1}
    
    # Cluster similar patterns
    if frequent_patterns:
        pattern_features = np.array([compute_pattern_features(pattern) for pattern in frequent_patterns.keys()])
        clustering = AgglomerativeClustering(n_clusters=None, distance_threshold=1-similarity_threshold, linkage='average', metric='cosine')
        clustering.fit(pattern_features)
        
        clustered_patterns = defaultdict(list)
        for pattern, label in zip(frequent_patterns.keys(), clustering.labels_):
            clustered_patterns[label].extend(frequent_patterns[pattern])
    else:
        clustered_patterns = {}
    
    return clustered_patterns

def compute_pattern_features(pattern, max_length=100):
    pitch_contour = [note[0] for bar in pattern for note in bar]
    rhythm_profile = [note[2] for bar in pattern for note in bar]
    
    # Pad sequences to max_length
    pitch_contour = (pitch_contour + [0] * max_length)[:max_length]
    rhythm_profile = (rhythm_profile + [0] * max_length)[:max_length]
    
    return np.concatenate((pitch_contour, rhythm_profile))

def classify_segments(preprocessed_data, repeating_patterns, melodic_phrases, ticks_per_bar):
    classifications = []
    pattern_boundaries = []
    
    for pattern_idx, (pattern, occurrences) in enumerate(repeating_patterns.items()):
        # Debugging information to check the structure of pattern
        print(f"Pattern {pattern_idx}: {pattern}")
        
        if isinstance(pattern, tuple) and all(isinstance(bar, tuple) for bar in pattern):
            pattern_length = len(pattern)
        else:
            print(f"Unexpected pattern structure: {pattern}")
            continue  # Skip this pattern if the structure is unexpected
        
        for start in occurrences:
            end = start + pattern_length - 1
            if end >= len(preprocessed_data):
                continue  # Skip if end index goes out of bounds
            
            classifications.append({
                'type': 'Repeating Pattern',
                'start': preprocessed_data[start]['start'],
                'end': preprocessed_data[end]['end'],
                'length': pattern_length,
                'description': f'Repeating pattern {pattern_idx + 1} of {pattern_length} bars',
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
    
    for phrase_idx, phrase in enumerate(melodic_phrases):
        classifications.append({
            'type': 'Melodic Phrase',
            'start': preprocessed_data[phrase[0]]['start'],
            'end': preprocessed_data[phrase[-1]]['end'],
            'length': len(phrase),
            'description': f'Melodic phrase {phrase_idx + 1} of {len(phrase)} bars'
        })
    
    for i, bar in enumerate(preprocessed_data):
        if bar['type'] == 'empty':
            classifications.append({
                'type': 'Empty',
                'start': bar['start'],
                'end': bar['end'],
                'length': (bar['end'] - bar['start']) // ticks_per_bar,
                'description': 'Empty bar segment'
            })
    
    return sorted(classifications, key=lambda x: x['start']), sorted(pattern_boundaries, key=lambda x: x['position'])

def visualize_track_segmentation(notes, classifications, pattern_boundaries, ticks_per_bar):
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=4, color='blue', alpha=0.5)
    
    colors = {'Melodic Phrase': 'green', 'Repeating Pattern': 'orange', 'Empty': 'gray'}
    
    for segment in classifications:
        start_tick = segment['start']
        end_tick = segment['end']
        segment_type = segment['type']
        color = colors[segment_type]
        ax.add_patch(Rectangle((start_tick, ax.get_ylim()[0]), end_tick - start_tick, ax.get_ylim()[1] - ax.get_ylim()[0], facecolor=color, alpha=0.3))
    
    for boundary in pattern_boundaries:
        ax.axvline(x=boundary['position'], color='red', linestyle='--', alpha=0.7)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title('Track Segmentation')
    
    plt.tight_layout()
    plt.show()

def analyze_midi_track(midi_file):
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
        
        melodic_phrases = segment_melodic_phrases_advanced(preprocessed_data, notes, ticks_per_bar)
        
        repeating_patterns = find_repeating_patterns_sia(preprocessed_data, notes, ticks_per_bar)
        
        classifications, pattern_boundaries = classify_segments(preprocessed_data, repeating_patterns, melodic_phrases, ticks_per_bar)
        
        visualize_track_segmentation(notes, classifications, pattern_boundaries, ticks_per_bar)
        
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
analysis_results = analyze_midi_track(midi_file)

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
