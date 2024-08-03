import os
import mido
from collections import defaultdict
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from music21 import chord

def extract_midi_metadata(midi_file):
    """
    Extract metadata from a MIDI file.

    Args:
        midi_file (mido.MidiFile): The MIDI file object to extract metadata from.

    Returns:
        dict: A dictionary containing the following metadata:
            - tempo_changes: List of tuples (time, tempo)
            - time_signature_changes: List of tuples (time, (numerator, denominator))
            - key_signature_changes: List of tuples (time, key)
            - program_changes: List of tuples (time, program, channel)
            - control_changes: List of tuples (time, control, value, channel)
            - notes: List of tuples (time, note, velocity, channel, type)
            - ticks_per_beat: Number of ticks per beat
            - type: MIDI file type

    Note:
        Time is measured in ticks. Tempo is in microseconds per beat.
    """
    metadata = defaultdict(list)
    current_tempo = 500000  # Default tempo (120 BPM)
    current_time_signature = (4, 4)  # Default time signature
    current_key_signature = 0  # Default key signature (C major / A minor)

    for i, track in enumerate(midi_file.tracks):
        track_time = 0
        for msg in track:
            track_time += msg.time
            if msg.type == 'set_tempo':
                metadata['tempo_changes'].append((track_time, msg.tempo))
                current_tempo = msg.tempo
            elif msg.type == 'time_signature':
                metadata['time_signature_changes'].append((track_time, (msg.numerator, msg.denominator)))
                current_time_signature = (msg.numerator, msg.denominator)
            elif msg.type == 'key_signature':
                metadata['key_signature_changes'].append((track_time, msg.key))
                current_key_signature = msg.key
            elif msg.type == 'program_change':
                metadata['program_changes'].append((track_time, msg.program, msg.channel))
            elif msg.type == 'control_change':
                metadata['control_changes'].append((track_time, msg.control, msg.value, msg.channel))
            elif msg.type in ['note_on', 'note_off']:
                metadata['notes'].append((track_time, msg.note, msg.velocity, msg.channel, msg.type))

    # If no changes were recorded, use the last known values
    if not metadata['tempo_changes']:
        metadata['tempo_changes'].append((0, current_tempo))
    if not metadata['time_signature_changes']:
        metadata['time_signature_changes'].append((0, current_time_signature))
    if not metadata['key_signature_changes']:
        metadata['key_signature_changes'].append((0, current_key_signature))

    metadata['ticks_per_beat'] = midi_file.ticks_per_beat
    metadata['type'] = midi_file.type

    return metadata

def read_midi_file(file_path):
    """
    Read a MIDI file and extract note information.

    Args:
        file_path (str): Path to the MIDI file.

    Returns:
        tuple: A tuple containing two elements:
            - tracks_notes (list): List of lists, where each inner list contains note information
              for a track. Each note is represented as a tuple (pitch, start_time, duration, velocity).
            - midi_file (mido.MidiFile): The original MIDI file object.

    Note:
        Times and durations are measured in ticks.
        Pitch is represented as MIDI note number (0-127).
        Velocity is in the range 0-127.
    """
    midi_file = mido.MidiFile(file_path)
    tracks_notes = []

    for track in midi_file.tracks:
        notes = []
        current_time = 0
        for msg in track:
            current_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                notes.append((msg.note, current_time, msg.velocity))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                for i, note in enumerate(reversed(notes)):
                    if note[0] == msg.note and len(note) == 3:
                        duration = current_time - note[1]
                        notes[-(i + 1)] = (note[0], note[1], duration, note[2])
                        break
        track_notes = [note for note in notes if len(note) == 4]
        if track_notes:
            tracks_notes.append(track_notes)

    print(f"Read {len(tracks_notes)} tracks with notes from the MIDI file")
    return tracks_notes, midi_file

def extract_duration_sequences(durations, sequence_length=8):
    """
    Extract sequences of note durations from a list of durations.

    Args:
        durations (list): List of note durations.
        sequence_length (int, optional): Length of each sequence. Defaults to 8.

    Returns:
        list: List of tuples, where each tuple is a sequence of durations.

    Note:
        Durations are typically in seconds or ticks, depending on the input.
    """
    sequences = [tuple(durations[i:i+sequence_length]) for i in range(len(durations) - sequence_length + 1)]
    return sequences

def extract_chord_sequences(notes, sequence_length=4):
    """
    Extract sequences of chords from a list of notes.

    Args:
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        sequence_length (int, optional): Length of each sequence. Defaults to 4.

    Returns:
        list: List of tuples, where each tuple is a sequence of chord representations.
    """
    if len(notes) < sequence_length:
        return []
    
    # Group notes into chords
    chord_dict = {}
    for note in notes:
        pitch, start_time, duration, velocity = note
        if start_time not in chord_dict:
            chord_dict[start_time] = []
        chord_dict[start_time].append((pitch, duration, velocity))
    
    # Sort chords by start time
    sorted_chords = sorted(chord_dict.items())
    
    # Create chord representations
    chord_representations = []
    for start_time, chord_notes in sorted_chords:
        pitches = [note[0] for note in chord_notes]
        c = chord.Chord(pitches)
        chord_type = c.commonName
        bass = min(pitches)
        duration = max(note[1] for note in chord_notes)
        density = len(chord_notes)
        chord_representations.append((chord_type, bass, duration, density))
    
    # Create sequences
    sequences = [tuple(chord_representations[i:i+sequence_length]) 
                 for i in range(len(chord_representations) - sequence_length + 1)]
    
    return sequences

def optimal_cluster_number(X, max_clusters=10):
    """
    Determine the optimal number of clusters using silhouette score.

    Args:
        X (numpy.ndarray): Input data for clustering.
        max_clusters (int, optional): Maximum number of clusters to consider. Defaults to 10.

    Returns:
        int: Optimal number of clusters.

    Note:
        This function uses K-means clustering and silhouette score to determine the optimal number of clusters.
    """
    if len(X) < max_clusters:
        max_clusters = len(X)
    
    silhouette_scores = []
    for n_clusters in range(2, max_clusters + 1):
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        cluster_labels = kmeans.fit_predict(X)
        silhouette_avg = silhouette_score(X, cluster_labels)
        silhouette_scores.append(silhouette_avg)
    
    optimal_clusters = silhouette_scores.index(max(silhouette_scores)) + 2
    return optimal_clusters

def cluster_chord_sequences(chord_sequences):
    """
    Cluster chord sequences using K-means clustering.

    Args:
        chord_sequences (list): List of chord sequences to cluster.

    Returns:
        numpy.ndarray: Array of cluster labels for each chord sequence.
    """
    if not chord_sequences:
        print("Warning: No chord sequences to cluster.")
        return []

    # Convert chord sequences to numerical features
    features = []
    for sequence in chord_sequences:
        seq_features = []
        for chord_rep in sequence:
            chord_type, bass, duration, density = chord_rep
            # Convert chord type to a numerical value (you might want to create a mapping)
            chord_type_value = hash(chord_type) % 100  # Simple hash function, might want to improve this
            seq_features.extend([chord_type_value, bass, duration, density])
        features.append(seq_features)

    X = np.array(features)
    
    n_clusters = optimal_cluster_number(X)
    
    if n_clusters == 1:
        print("Only one cluster found. All chord sequences might be similar.")
        return [0] * len(chord_sequences)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(X)
    
    print(f"Optimal number of clusters: {n_clusters}")
    return cluster_labels

def cluster_duration_patterns(duration_sequences):
    """
    Cluster duration sequences using K-means clustering.

    Args:
        duration_sequences (list): List of duration sequences to cluster.

    Returns:
        numpy.ndarray: Array of cluster labels for each duration sequence.

    Note:
        This function determines the optimal number of clusters and then performs K-means clustering.
    """
    X = np.array(duration_sequences)
    n_clusters = optimal_cluster_number(X)
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(X)
    
    print(f"Optimal number of clusters: {n_clusters}")
    return cluster_labels

def identify_rhythmic_boundaries(notes, cluster_labels, sequence_length=8):
    """
    Identify rhythmic boundaries based on changes in cluster labels.

    Args:
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        cluster_labels (numpy.ndarray): Array of cluster labels for each duration sequence.
        sequence_length (int, optional): Length of each duration sequence. Defaults to 8.

    Returns:
        list: List of boundary times (in ticks) where rhythmic patterns change.

    Note:
        This function identifies points where the cluster label changes, indicating a potential rhythmic boundary.
    """
    boundaries = []
    current_cluster = cluster_labels[0]
    for i, label in enumerate(cluster_labels[1:], 1):
        if label != current_cluster:
            boundaries.append(notes[i + sequence_length - 1][1])  # Add the start time of the note at the boundary
            current_cluster = label
    return boundaries

def analyze_rhythmic_patterns(notes, metadata):
    """
    Analyze rhythmic patterns in a sequence of notes.

    Args:
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        metadata (dict): Dictionary containing MIDI metadata, including tempo and time signature information.

    Returns:
        list: List of filtered rhythmic boundary times (in ticks).
    """
    if not notes:
        print("Warning: No notes found in this track.")
        return []

    ticks_per_beat = metadata['ticks_per_beat']
    initial_tempo = metadata['tempo_changes'][0][1]
    initial_time_signature = metadata['time_signature_changes'][0][1]
    
    beat_duration = 60 / (initial_tempo / 1000000)  # Convert tempo to seconds per beat
    
    # Pass full note information to extract_chord_sequences
    chord_sequences = extract_chord_sequences(notes, sequence_length=32)
    
    if not chord_sequences:
        print("Warning: No chord sequences found. All notes might have the same duration.")
        return []

    # Cluster the chord sequences
    cluster_labels = cluster_chord_sequences(chord_sequences)
    
    # Identify boundaries based on cluster changes
    boundaries = identify_rhythmic_boundaries(notes, cluster_labels, sequence_length=32)
    
    # Filter boundaries to keep only significant changes
    min_segment_duration = ticks_per_beat * 4  # Minimum 4 beats between boundaries
    filtered_boundaries = [boundaries[0]] if boundaries else []
    for b in boundaries[1:]:
        if b - filtered_boundaries[-1] >= min_segment_duration:
            filtered_boundaries.append(b)
    
    return filtered_boundaries

def find_repeating_motifs(notes, min_length=8, max_length=128, quantize_duration=30):
    """
    Find repeating motifs in a sequence of notes.

    Args:
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        min_length (int): Minimum length of a motif to consider. Defaults to 8.
        max_length (int): Maximum length of a motif to consider. Defaults to 128.
        quantize_duration (int): Duration (in ticks) to quantize note timings. Defaults to 30.

    Returns:
        dict: Dictionary of repeating motifs, where each key is a motif and each value is a dict containing:
            - id: Unique identifier for the motif
            - positions: List of starting positions (in ticks) where the motif occurs
            - score: Score based on frequency and length of the motif

    Note:
        This function identifies repeating patterns of notes, considering both pitch and rhythm.
        It quantizes note durations to allow for slight timing variations in pattern matching.
    """
    motifs = {}
    chord_sequence = []
    current_chord = []
    current_time = -1
    
    for note in sorted(notes, key=lambda x: x[1]):
        if note[1] != current_time:
            if current_chord:
                chord_sequence.append((tuple(sorted(current_chord)), round((note[1] - current_time) / quantize_duration) * quantize_duration))
            current_chord = [(note[0], round(note[2] / quantize_duration) * quantize_duration)]
            current_time = note[1]
        else:
            current_chord.append((note[0], round(note[2] / quantize_duration) * quantize_duration))
    
    if current_chord:
        chord_sequence.append((tuple(sorted(current_chord)), 0))
    
    for length in range(min_length, min(max_length, len(chord_sequence)) + 1):
        for i in range(len(chord_sequence) - length + 1):
            motif = tuple(chord_sequence[i:i+length])
            if motif in motifs:
                motifs[motif]['positions'].append(i)
            else:
                motifs[motif] = {'id': len(motifs), 'positions': [i], 'score': 0}
    
    # Calculate scores based on frequency and length
    for motif, data in motifs.items():
        data['score'] = len(data['positions']) * len(motif)
    
    repeating_motifs = {m: v for m, v in motifs.items() if len(v['positions']) > 1}
    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: x[1]['score'], reverse=True)
    
    print(f"Found {len(sorted_motifs)} repeating motifs")
    if sorted_motifs:
        print("Top motif:", sorted_motifs[0][0])
    return dict(sorted_motifs)

def segment_track(notes, repeating_motifs, rhythmic_boundaries, ticks_per_bar):
    """
    Segment a track based on repeating motifs and rhythmic boundaries.

    Args:
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        repeating_motifs (dict): Dictionary of repeating motifs found in the track.
        rhythmic_boundaries (list): List of rhythmic boundary times.
        ticks_per_bar (int): Number of ticks in one bar.

    Returns:
        list: List of segment tuples (start_time, end_time, repetition_count, motif, motif_id).

    Note:
        This function prioritizes segments with more repetitions and avoids overlaps.
        It aligns segment boundaries with musical bars and fills gaps between motif-based segments.
    """
    segments = []
    used_notes = set()
    
    # Sort motifs by repetition count (descending)
    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: len(x[1]['positions']), reverse=True)
    
    for motif, data in sorted_motifs:
        for position in data['positions']:
            start_tick = notes[position][1]
            end_tick = start_tick + sum(duration for _, duration in motif)
            
            # Adjust segment to align with musical bars
            start_bar = start_tick // ticks_per_bar
            end_bar = (end_tick + ticks_per_bar - 1) // ticks_per_bar
            adjusted_start = start_bar * ticks_per_bar
            adjusted_end = end_bar * ticks_per_bar
            
            # Check for overlap with existing segments or used notes
            if not any(s <= adjusted_start < adjusted_end <= e for s, e, _, _, _ in segments) and \
               not any(note in used_notes for note in range(position, position + len(motif))):
                segments.append((adjusted_start, adjusted_end, len(data['positions']), motif, data['id']))
                used_notes.update(range(position, position + len(motif)))
    
    # Fill gaps with non-motif segments
    segments.sort(key=lambda x: x[0])
    filled_segments = []
    last_end = 0
    for segment in segments:
        if segment[0] > last_end:
            # Add a non-motif segment to fill the gap
            gap_start = (last_end // ticks_per_bar) * ticks_per_bar
            gap_end = (segment[0] // ticks_per_bar) * ticks_per_bar
            if gap_end > gap_start:
                filled_segments.append((gap_start, gap_end, 1, (), -1))
        filled_segments.append(segment)
        last_end = segment[1]
    
    # Add final segment if needed
    if last_end < notes[-1][1]:
        final_start = (last_end // ticks_per_bar) * ticks_per_bar
        final_end = ((notes[-1][1] + ticks_per_bar - 1) // ticks_per_bar) * ticks_per_bar
        filled_segments.append((final_start, final_end, 1, (), -1))
    
    return filled_segments

def merge_small_segments(segments, ticks_per_bar):
    """
    Merge small segments to create more meaningful larger segments.

    Args:
        segments (list): List of segment tuples (start_time, end_time, repetition_count, motif, motif_id).
        ticks_per_bar (int): Number of ticks in one bar.

    Returns:
        list: List of merged segment tuples.

    Note:
        This function combines adjacent small segments that are shorter than 2 bars.
        It preserves the motif information of larger segments when merging.
    """
    merged = []
    current_segment = None
    min_segment_length = 2 * ticks_per_bar

    for segment in segments:
        if current_segment is None:
            current_segment = segment
        elif segment[1] - segment[0] < min_segment_length or current_segment[1] - current_segment[0] < min_segment_length:
            # Merge small segments
            current_segment = (
                min(current_segment[0], segment[0]),
                max(current_segment[1], segment[1]),
                max(current_segment[2], segment[2]),
                current_segment[3] + segment[3],
                current_segment[4] if current_segment[4] != -1 else segment[4]
            )
        else:
            merged.append(current_segment)
            current_segment = segment

    if current_segment:
        merged.append(current_segment)

    return merged

def save_patterns_to_midi(original_midi, notes, segments, output_file_path, metadata):
    """
    Save identified patterns as a new MIDI file, including the original tracks.

    Args:
        original_midi (mido.MidiFile): The original MIDI file object.
        notes (list): List of note information tuples (pitch, start_time, duration, velocity).
        segments (list): List of segment tuples (start_time, end_time, repetition_count, motif, motif_id).
        output_file_path (str): Path where the new MIDI file will be saved.
        metadata (dict): Dictionary containing MIDI metadata.

    Note:
        This function creates a new MIDI file with the original tracks and additional tracks for each identified segment.
        Each segment is represented as a separate track in the output MIDI file.
        Very short segments (less than half a beat) are skipped.
    """
    output_midi = mido.MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)

    # Copy all original tracks
    for track in original_midi.tracks:
        output_midi.tracks.append(track)

    # Create a dictionary to store note events
    note_events = defaultdict(list)
    for note in notes:
        note_events[note[1]].append(('note_on', note[0], note[3]))
        note_events[note[1] + note[2]].append(('note_off', note[0], note[3]))

    # Add segment tracks
    for i, segment in enumerate(segments):
        start_time, end_time, count, motif, motif_id = segment
        
        # Skip very short segments
        if end_time - start_time < metadata['ticks_per_beat'] / 2:
            continue

        track = mido.MidiTrack()
        output_midi.tracks.append(track)
        
        # Add program change
        track.append(mido.Message('program_change', program=0, time=0))

        current_time = 0
        active_notes = set()

        for tick in range(start_time, end_time + 1):
            if tick in note_events:
                for event in note_events[tick]:
                    msg_type, note, velocity = event
                    delta_time = tick - current_time
                    if msg_type == 'note_on' and tick < end_time:
                        track.append(mido.Message(msg_type, note=note, velocity=velocity, time=delta_time))
                        active_notes.add(note)
                        current_time = tick
                    elif msg_type == 'note_off' or tick == end_time:
                        if note in active_notes:
                            track.append(mido.Message('note_off', note=note, velocity=0, time=delta_time))
                            active_notes.remove(note)
                            current_time = tick

        # Ensure all notes are turned off at the end of the segment
        for note in active_notes:
            track.append(mido.Message('note_off', note=note, velocity=0, time=end_time - current_time))

        print(f"Added track for segment {i+1}: Start={start_time}, End={end_time}, Motif ID={motif_id}, Duration={end_time-start_time}")

    # Save the MIDI file
    output_midi.save(output_file_path)
    print(f"Original tracks and segments saved to {output_file_path}")
    
def process_track(track_notes, track_index, original_midi, output_dir, input_filename, metadata):
    """
    Process a single track of a MIDI file to identify and save patterns.

    Args:
        track_notes (list): List of note information tuples for the track.
        track_index (int): Index of the track being processed.
        original_midi (mido.MidiFile): The original MIDI file object.
        output_dir (str): Directory where output files will be saved.
        input_filename (str): Name of the input MIDI file.
        metadata (dict): Dictionary containing MIDI metadata.

    Note:
        This function analyzes a single track, identifies rhythmic patterns and repeating motifs,
        segments the track, and saves the results as a new MIDI file.
        It prints a report of the first 21 segments identified in the track.
    """
    print(f"\nProcessing Track {track_index}")
    
    initial_tempo = metadata['tempo_changes'][0][1]
    initial_time_signature = metadata['time_signature_changes'][0][1]
    
    print(f"Initial Tempo: {60000000 / initial_tempo:.2f} BPM")
    print(f"Initial Time Signature: {initial_time_signature[0]}/{initial_time_signature[1]}")
    
    rhythmic_boundaries = analyze_rhythmic_patterns(track_notes, metadata)
    
    repeating_motifs = find_repeating_motifs(track_notes, min_length=4, max_length=30000)
    
    # Calculate ticks_per_bar
    ticks_per_beat = metadata['ticks_per_beat']
    beats_per_bar = initial_time_signature[0]
    ticks_per_bar = ticks_per_beat * beats_per_bar
    
    segments = segment_track(track_notes, repeating_motifs, rhythmic_boundaries, ticks_per_bar)

    if len(segments) == 0:
        print("Warning: No segments found for this track.")
        return

    output_filename = f"{os.path.splitext(input_filename)[0]}_track{track_index}_patterns_RhythmPitchSilhouette.mid"
    output_file_path = os.path.join(output_dir, output_filename)

    save_patterns_to_midi(original_midi, track_notes, segments, output_file_path, metadata)

    print(f"Segment Report for Track {track_index}:")
    for i, (start_time, end_time, count, motif, motif_id) in enumerate(segments):
        if i >= 21:
            break  # Stop after printing 21 segments
        print(f"Segment {i + 1}:")
        print(f"  Start: {start_time} ticks")
        print(f"  End: {end_time} ticks")
        print(f"  Length: {end_time - start_time} ticks")
        print(f"  Motif ID: {motif_id}")
        print(f"  Repetitions: {count}")
        print(f"  Motif: {motif}")
        print("-" * 20)
    
def main(file_path):
    """
    Main function to process a MIDI file and identify patterns in all tracks.

    Args:
        file_path (str): Path to the input MIDI file.

    Note:
        This function reads the MIDI file, extracts metadata, processes each track,
        and saves the results as new MIDI files in the output directory.
    """
    try:
        tracks_notes, original_midi = read_midi_file(file_path)
        
        if not tracks_notes:
            print("Error: No notes found in the MIDI file. Please check the file format and content.")
            return

        metadata = extract_midi_metadata(original_midi)
        
        print("MIDI Metadata:")
        print(f"MIDI Type: {metadata['type']}")
        print(f"Ticks per Beat: {metadata['ticks_per_beat']}")
        print(f"Initial Tempo: {60000000 / metadata['tempo_changes'][0][1]:.2f} BPM")
        print(f"Initial Time Signature: {metadata['time_signature_changes'][0][1][0]}/{metadata['time_signature_changes'][0][1][1]}")
        print(f"Initial Key Signature: {metadata['key_signature_changes'][0][1]}")
        
        print(f"Number of tempo changes: {len(metadata['tempo_changes'])}")
        print(f"Number of time signature changes: {len(metadata['time_signature_changes'])}")
        print(f"Number of key signature changes: {len(metadata['key_signature_changes'])}")
        print(f"Number of program changes: {len(metadata['program_changes'])}")
        print(f"Number of control changes: {len(metadata['control_changes'])}")
        print(f"Total number of notes: {len(metadata['notes'])}")

        output_dir = os.path.join('testing_tools', 'test_scripts', 'pattern_output', 'PatternSegmentationSlidingWindow')
        os.makedirs(output_dir, exist_ok=True)

        input_filename = os.path.basename(file_path)
        for i, track_notes in enumerate(tracks_notes):
            process_track(track_notes, i, original_midi, output_dir, input_filename, metadata)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

# Path to your MIDI file
file_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
#file_path = 'testing_tools/test_scripts/pattern_output/something_in_the_way/asle_something_in_the_way.mid'
#file_path = 'testing_tools/test_scripts/take_on_me_midi/take_on_me.mid'
#file_path = 'archived/i_am_trying_sf_segmenter_a_bit/Something_in_the_Way.mid'
main(file_path)
