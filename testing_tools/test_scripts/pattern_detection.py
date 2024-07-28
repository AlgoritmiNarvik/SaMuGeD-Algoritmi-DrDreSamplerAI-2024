import numpy as np
import os
from collections import Counter, defaultdict

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

from miditoolkit.midi.parser import MidiFile
from miditoolkit.midi.containers import Instrument, Note
from miditoolkit.midi import parser as mid_parser

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from scipy.stats import skew, kurtosis
from scipy.spatial.distance import euclidean
from scipy.spatial.distance import cdist

def detect_patterns(mido_obj: str | object) -> list:
    """
    Takes path to a midifile or a class instance of miditoolkit.midi.parser.MidiFile

    Returns a list of tracks, each track is a list of segments, each segment containing notes.
    """
    #find end of last note, that is the end of the song or time window to look at
    #1:01:00 is the first(0th) tick in flstudio
    #x:16:24 first number is bar, starting with 1st bar. each bar is divided into steps, every 16 steps is one bar. Each step is divided into 24 ticks.
    #The very start of the track is 1:01:00, which in ticks is 400?
    #1 bar duration = 384 ticks (for 4/4 time signature, 2nd number is how many beats are in each bar)

    if isinstance(mido_obj, mid_parser.MidiFile):
        mido_obj = mido_obj
    elif type(mido_obj) is str:
        try:
            mido_obj = mid_parser.MidiFile(mido_obj)
        except:
            print(f'Unable to open {mido_obj}')
    else:
        print(f'Input not a path or instance of MidiFile class')
        return None
    
    ticks_per_beat = mido_obj.ticks_per_beat
    time_signature = mido_obj.time_signature_changes
    ticks_per_bar = ticks_per_beat * time_signature[0].denominator

    tracks = [] #This list will contain a list for each track, each list containing segments

    for ins_nr, instrument in enumerate(mido_obj.instruments):
        if instrument.is_drum == True:
            continue
        notes = instrument.notes
        sorted_notes = sorted(notes, key=lambda x: x.start)
        first_note_start = np.inf
        last_note_end = 0
        for note in sorted_notes:
            if note.start < first_note_start:
                first_note_start = note.start
            if note.end > last_note_end:
                last_note_end = note.end
        print(f'Track: {ins_nr}, {instrument=}\n {first_note_start=}, {last_note_end=}')

        note_playing = False #Is a note playing?
        note_playing_end = 0 #The tick the currently active note will end on
        ticks_since_last_note = 385 #Set value greater than 384 so that we don't save an empty segment at the start
        segments = [] #The list where segments/samples will be saved
        temp = [] #Temporary list that keeps track of notes in the current segment
        notes_to_remove = [] #Empty set to keep track of note indecies in the list of notes
        #k = 0 #Counter used to keep track of bars
        for i in range(0, last_note_end):
            notes_to_remove = [] #Empty set to keep track of note indecies in the list of notes
            if note_playing == False: #Increment silence counter if no note is playing
                ticks_since_last_note += 1
            elif i >= note_playing_end: #Check if the playing note has ended
                note_playing = False
                note_playing_end = 0
            for x, note in enumerate(sorted_notes): #Iterate through notes to see if they are currently playing
                if i == note.start:
                    temp.append(note)
                    note_playing = True
                    note_playing_end = note.end if note.end > note_playing_end else note_playing_end
                    ticks_since_last_note = 0
                    notes_to_remove.append(note)#Add played notes to a list so we can remove them later
                
            for note in notes_to_remove[::-1]: #Remove played notes from list of notes to reduce code execution time
                sorted_notes.remove(note)

            if ticks_since_last_note == ticks_per_bar: #save segment when 1 bar has passed since end of last note
                segments.append(temp)
                temp = []

            """ k+=0
            if ((k % 384) == 0) and (note_playing == False):
                k=0
                segments.append(temp)
                temp = []
            """

        if len(temp) > 0:
            segments.append(temp)
            temp = []

        tracks.append(segments)

    
    return tracks

def segment_midi_to_bars(midi_file):
    """
    Segments a MIDI file into bars for each track
    
    Args:
    midi_file (str): path to the MIDI file
    
    Returns:
    dict: a dictionary where keys are track numbers and values are lists of bars
    dict: a dictionary where keys are track numbers and values are lists of bar timings
    """
    try:
        midi_obj = mid_parser.MidiFile(midi_file)
    except:
        print(f'Unable to open {midi_file}')
        return None, None

    segments_by_track = {}
    timings_by_track = {}

    for track_idx, instrument in enumerate(midi_obj.instruments):
        notes = instrument.notes
        sorted_notes = sorted(notes, key=lambda x: x.start)
        
        if not sorted_notes:
            continue  # skip empty tracks
        
        track_start = sorted_notes[0].start
        track_end = max(note.end for note in sorted_notes)
        
        time_sig = midi_obj.time_signature_changes[0]  # assume time signature doesn't change
        ticks_per_bar = time_sig.numerator * midi_obj.ticks_per_beat * 4 // time_sig.denominator
        
        bars = []
        timings = []
        current_bar_start = track_start - (track_start % ticks_per_bar)
        while current_bar_start < track_end:
            bar_end = min(current_bar_start + ticks_per_bar, track_end)
            bar_notes = [note for note in sorted_notes if note.start < bar_end and note.end > current_bar_start]
            
            if bar_notes:  # only add the bar if it contains notes
                bars.append({
                    'start': current_bar_start,
                    'end': bar_end,
                    'notes': bar_notes
                })
                timings.append((current_bar_start, bar_end))
            
            current_bar_start += ticks_per_bar

        segments_by_track[track_idx] = bars
        timings_by_track[track_idx] = timings

    return segments_by_track, timings_by_track

def get_max_notes(bars):
    """
    Determine the maximum number of notes in any bar of the track.
    
    Args:
    bars (list): List of bar dictionaries for a track.
    
    Returns:
    int: Maximum number of notes found in any bar.
    """
    return max(len(bar['notes']) for bar in bars)

def convert_bar_to_feature_vector(bar, max_notes):
    """
    Converts a bar to a feature vector for similarity comparison.
    
    This function creates a variable-length feature vector that represents the musical content of a bar.
    The vector includes information about pitch, timing, duration, and velocity of notes.
    The length of the vector adapts to the maximum number of notes found in any bar of the track.
    
    Args:
    bar (dict): A dictionary representing a bar, containing 'notes' and timing information.
    max_notes (int): Maximum number of notes to consider, based on the track.
    
    Returns:
    np.array: A feature vector representing the bar, with shape (4 * max_notes,).
    """
    n_notes = len(bar['notes'])
    if n_notes > 0:
        pitches = [note.pitch for note in bar['notes']]
        start_times = [note.start - bar['start'] for note in bar['notes']]
        durations = [note.end - note.start for note in bar['notes']]
        velocities = [note.velocity for note in bar['notes']]
    else:
        pitches = start_times = durations = velocities = []
    
    # pad to max_notes length
    pitches = pitches + [0] * (max_notes - len(pitches))
    start_times = start_times + [0] * (max_notes - len(start_times))
    durations = durations + [0] * (max_notes - len(durations))
    velocities = velocities + [0] * (max_notes - len(velocities))
    
    return np.array(pitches + start_times + durations + velocities)

def are_bars_similar(bar1, bar2, threshold=0.1, max_notes=None):
    """
    Determines if two bars are similar based on their feature vectors.
    
    This function computes the similarity between two bars using their feature vectors.
    It uses Euclidean distance as a measure of dissimilarity, which is then converted to a similarity score.
    
    Args:
    bar1, bar2 (dict): Dictionaries representing bars to be compared.
    threshold (float): Similarity threshold. Bars are considered similar if their 
                       similarity score is greater than (1 - threshold).
    max_notes (int): Maximum number of notes to consider, based on the track.
    
    Returns:
    bool: True if bars are similar (similarity > 1 - threshold), False otherwise.
    """
    if max_notes is None:
        max_notes = max(len(bar1['notes']), len(bar2['notes']))
    vec1 = convert_bar_to_feature_vector(bar1, max_notes)
    vec2 = convert_bar_to_feature_vector(bar2, max_notes)
    distance = euclidean(vec1, vec2)
    max_distance = np.sqrt(len(vec1)) * 127  # maximum possible distance
    similarity = 1 - (distance / max_distance)
    return similarity > (1 - threshold)

def cluster_bars(bars, n_clusters=5): # n_clusters=5 for now, experimenting
    """
    DEPRECATED
    clusters bars using k-means algorithm
    
    args:
    bars (list): list of bars
    n_clusters (int): number of clusters to form
    
    returns:
    list: cluster labels for each bar
    """
    feature_vectors = np.array([convert_bar_to_feature_vector(bar) for bar in bars])
    
    scaler = StandardScaler()
    feature_vectors_normalized = scaler.fit_transform(feature_vectors)
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(feature_vectors_normalized)
    
    return cluster_labels

def extract_pattern(midi_file, track_idx, pattern, timings):
    """
    Extract a pattern from the original MIDI file.
    
    Args:
    midi_file (str): Path to the original MIDI file.
    track_idx (int): Index of the track containing the pattern.
    pattern (list): List of bars representing the pattern.
    timings (list): List of (start, end) tuples for each bar in the track.
    
    Returns:
    MidiFile: A new MIDI file containing only the extracted pattern.
    """
    midi_obj = mid_parser.MidiFile(midi_file)
    new_midi = MidiFile()
    new_midi.ticks_per_beat = midi_obj.ticks_per_beat

    # Copy time signature and tempo information
    new_midi.time_signature_changes = midi_obj.time_signature_changes
    new_midi.tempo_changes = midi_obj.tempo_changes

    # Create a new instrument for the pattern
    new_instrument = Instrument(program=midi_obj.instruments[track_idx].program,
                                is_drum=midi_obj.instruments[track_idx].is_drum,
                                name=f"Pattern from Track {track_idx}")

    # Extract notes for the pattern
    if not pattern:
        print(f"Warning: Empty pattern for track {track_idx}")
        return new_midi

    # Debug information
    print(f"Pattern start: {pattern[0]['start']}")
    print(f"Timings length: {len(timings)}")
    print(f"First few timings: {timings[:5]}")

    # Find the correct start time
    start_time = None
    for i, (bar_start, bar_end) in enumerate(timings):
        if bar_start == pattern[0]['start']:
            start_time = bar_start
            break
    
    if start_time is None:
        print(f"Warning: Could not find start time for pattern in track {track_idx}")
        start_time = pattern[0]['start']

    for bar in pattern:
        for note in bar['notes']:
            new_note = Note(velocity=note.velocity,
                            pitch=note.pitch,
                            start=note.start - start_time,
                            end=note.end - start_time)
            new_instrument.notes.append(new_note)

    new_midi.instruments.append(new_instrument)
    return new_midi

def save_pattern_as_midi(pattern, filename, original_midi=None, instrument_program=0):
    """
    Save a pattern (list of bars) as a MIDI file.
    
    Args:
    pattern (list): List of bar dictionaries representing the pattern
    filename (str): Name of the file to save the pattern to
    original_midi (MidiFile): Original MIDI file to copy metadata from (optional)
    instrument_program (int): MIDI program number for the instrument (default: 0)
    """
    try:
        midi = MidiFile()
        if original_midi:
            midi.ticks_per_beat = original_midi.ticks_per_beat
            midi.time_signature_changes = original_midi.time_signature_changes
            midi.tempo_changes = original_midi.tempo_changes

        instrument = Instrument(program=instrument_program, is_drum=False, name="Pattern")
        
        pattern_start = pattern[0]['start']
        for bar in pattern:
            for note in bar['notes']:
                new_start = note.start - pattern_start
                new_end = note.end - pattern_start
                if new_end <= new_start:
                    new_end = new_start + 1
                new_note = Note(velocity=note.velocity, pitch=note.pitch, start=new_start, end=new_end)
                instrument.notes.append(new_note)
        
        midi.instruments.append(instrument)
        midi.dump(filename)
        print(f"Pattern successfully saved to {filename}")
    except Exception as e:
        print(f"Error saving pattern to MIDI: {str(e)}")

def save_pattern_as_midi_DEPR(pattern, filename):
    """
    DEPR FOUND ISSUES HERE
    Save a pattern (list of bars) as a MIDI file.
    
    Args:
    pattern (list): List of bar dictionaries representing the pattern
    filename (str): Name of the file to save the pattern to
    """
    midi = MidiFile()
    instrument = Instrument(program=0, is_drum=False, name="Pattern")
    
    # adjust start times to fit within the bar
    for bar in pattern:
        start_offset = bar['start']
        for note in bar['notes']:
            # adjust the note start and end times relative to the bar start time
            new_start = note.start - start_offset
            new_end = note.end - start_offset
            # ensure the times are non-negative
            if new_start < 0:
                new_start = 0
            if new_end < new_start:
                new_end = new_start + 1  # ensure end time is greater than start time
            new_note = Note(velocity=note.velocity, pitch=note.pitch, start=new_start, end=new_end)
            instrument.notes.append(new_note)
    
    midi.instruments.append(instrument)
    midi.dump(filename)

def compare_notes(segment, note_number, compare_note_number, duration_difference=10) -> bool:
    """Returns True if the notes have the same pitch and within specified duration difference"""
    try:
        if segment[note_number].pitch == segment[compare_note_number].pitch:
            note_duration = segment[note_number].end - segment[note_number].start
            compare_note_duration = segment[compare_note_number].end - segment[compare_note_number].start
            if abs(note_duration - compare_note_duration) <= duration_difference:
                
                return True
    except:
        pass

    return False

def almaz():

    # usage for segmenting tracks into bars
    # for track_idx, bars in segmented_tracks.items():
    #     print(f"track {track_idx}: {len(bars)} bars")
    #     for i, bar in enumerate(bars[:10]):  # This will iterate over the first 10 bars
    #         print(f"  bar {i}: start={bar['start']}, end={bar['end']}, notes={len(bar['notes'])}")
    #     if len(bars) > 10:
    #         print("  ... and so on")  
        
    # usage for finding patterns, kinda whole process

    midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
    output_dir = "testing_tools/test_scripts/pattern_output"
    os.makedirs(output_dir, exist_ok=True)
    
    min_sample_length = int(input("Enter the minimum sample length in bars (1-4): "))
    
    if min_sample_length < 1 or min_sample_length > 4:
        print("Invalid sample length. Using default value of 1.")
        min_sample_length = 1

    segmented_tracks, timings_by_track = segment_midi_to_bars(midi_file)
    if segmented_tracks is None:
        print("Failed to process MIDI file.")
        exit(1)

    # Debug information
    for track_idx, track_timings in timings_by_track.items():
        print(f"Track {track_idx} timings: {len(track_timings)} bars")
        print(f"First few timings: {track_timings[:5]}")

    repeating_patterns = find_repeating_patterns(segmented_tracks, timings_by_track, min_sample_length)
    
    for track_idx, patterns in repeating_patterns.items():
        print(f"Track {track_idx}:")
        for i, pattern_group in enumerate(patterns):
            print(f"  Pattern group {i}: {len(pattern_group)} repetitions")
            print(f"    Representative: start={pattern_group[0][0]['start']}, end={pattern_group[0][-1]['end']}, notes={sum(len(bar['notes']) for bar in pattern_group[0])}")
            
            filename = f"{output_dir}/track{track_idx}_pattern{i:03d}_repeated{len(pattern_group):03d}.mid"
            try:
                pattern_midi = extract_pattern(midi_file, track_idx, pattern_group[0], timings_by_track[track_idx])
                pattern_midi.dump(filename)
                print(f"    Saved as: {filename}")
            except Exception as e:
                print(f"    Error saving pattern: {str(e)}")
        print()

def find_repeating_patterns_DEPR(segmented_tracks, timings_by_track, min_sample_length=1, similarity_threshold=0.1):
    """
    Finds repeating patterns in segmented tracks.

    Args:
    segmented_tracks (dict): Dictionary of segmented tracks.
    timings_by_track (dict): Dictionary of timings for each track.
    min_sample_length (int): Minimum length of a sample in bars.
    similarity_threshold (float): Threshold for bar similarity comparison.

    Returns:
    dict: Dictionary where keys are track indices and values are lists of pattern groups.
    """
    patterns_by_track = {}
    
    for track_idx, bars in segmented_tracks.items():
        max_notes = get_max_notes(bars)
        patterns = defaultdict(list)
        
        for i in range(len(bars) - min_sample_length + 1):
            sample = bars[i:i+min_sample_length]
            sample_hash = hash(tuple(bar['start'] for bar in sample))
            
            if sample_hash in patterns:
                patterns[sample_hash].append(sample)
            else:
                for pattern_hash, pattern_samples in patterns.items():
                    if all(are_bars_similar(sample[j], pattern_samples[0][j], similarity_threshold, max_notes) 
                           for j in range(min_sample_length)):
                        patterns[pattern_hash].append(sample)
                        break
                else:
                    patterns[sample_hash] = [sample]
        
        # filter patterns, keeping only those that repeat more than once
        filtered_patterns = [pattern for pattern in patterns.values() if len(pattern) > 1]
        
        # sort patterns by number of repetitions
        sorted_patterns = sorted(filtered_patterns, key=len, reverse=True)
        patterns_by_track[track_idx] = sorted_patterns
        
        print(f"Track {track_idx}: Found {len(sorted_patterns)} pattern groups")
        for i, pattern_group in enumerate(sorted_patterns):
            print(f"  Pattern group {i}: {len(pattern_group)} repetitions, length: {min_sample_length} bars")
            print(f"    Start ticks: {[p[0]['start'] for p in pattern_group]}")
            print(f"    End ticks: {[p[-1]['end'] for p in pattern_group]}")
    
    return patterns_by_track

def visualize_track_with_patterns(midi_obj, track_idx, patterns, timings):
    """
    Visualizes a track with found patterns.

    Args:
    midi_obj (MidiFile): MIDI file object.
    track_idx (int): Index of the track to visualize.
    patterns (list): List of pattern groups.
    timings (list): List of timings for the track.
    """
    notes = midi_obj.instruments[track_idx].notes
    
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for note in notes:
        ax.plot([note.start, note.end], [note.pitch, note.pitch], linewidth=2, color='blue', alpha=0.5)
    
    colors = plt.cm.rainbow(np.linspace(0, 1, len(patterns)))
    
    for i, (pattern_group, color) in enumerate(zip(patterns, colors)):
        pattern_name = f"P{i+1}"
        for j, pattern in enumerate(pattern_group):
            start = pattern[0]['start']
            end = pattern[-1]['end']
            ax.axvspan(start, end, facecolor=color, alpha=0.2)
            
            ax.annotate(f"{pattern_name}", 
                        xy=(start, ax.get_ylim()[1]), 
                        xytext=(0, 10), 
                        textcoords='offset points',
                        rotation=90,
                        va='bottom',
                        color=color,
                        fontweight='bold')
            
            # Add vertical lines for start and end with labels
            ax.axvline(x=start, color=color, linestyle='--', alpha=0.7, linewidth=1)
            ax.axvline(x=end, color=color, linestyle='--', alpha=0.7, linewidth=1)
            
            # Add labels for start and end
            ax.text(start, ax.get_ylim()[0], f'{pattern_name} start', rotation=90, 
                    va='bottom', ha='right', color=color, fontsize=8)
            ax.text(end, ax.get_ylim()[0], f'{pattern_name} end', rotation=90, 
                    va='bottom', ha='right', color=color, fontsize=8)
    
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch')
    ax.set_title(f'Track {track_idx} with Patterns')
    
    plt.subplots_adjust(bottom=0.2)
    ax.set_xlim(0, max(note.end for note in notes))
    
    legend_elements = [plt.Line2D([0], [0], color=color, lw=4, label=f'P{i+1} (x{len(pattern_group)})') 
                       for i, (pattern_group, color) in enumerate(zip(patterns, colors))]
    ax.legend(handles=legend_elements, loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=3)
    
    plt.tight_layout()
    plt.show()
  
def extract_bar_features(bar):
    """Extract more features from a bar."""
    notes = bar['notes']
    if not notes:
        return np.zeros(10)  # Return zero vector for empty bars
    
    pitches = [note.pitch for note in notes]
    velocities = [note.velocity for note in notes]
    durations = [note.end - note.start for note in notes]
    start_times = [note.start - bar['start'] for note in notes]
    
    features = [
        len(notes),  # Number of notes
        np.mean(pitches),  # Mean pitch
        np.std(pitches) if len(pitches) > 1 else 0,  # Pitch variety
        np.mean(velocities),  # Mean velocity
        np.std(velocities) if len(velocities) > 1 else 0,  # Velocity variety
        np.mean(durations),  # Mean note duration
        np.std(durations) if len(durations) > 1 else 0,  # Duration variety
        skew(start_times) if len(start_times) > 2 else 0,  # Skewness of note start times
        kurtosis(start_times) if len(start_times) > 3 else 0,  # Kurtosis of note start times
        len(set(pitches)) / len(pitches) if pitches else 0  # Pitch uniqueness ratio
    ]
    return np.array(features)

def compute_similarity(sample1, sample2):
    """Compute similarity between two samples using their features."""
    features1 = np.array([extract_bar_features(bar) for bar in sample1])
    features2 = np.array([extract_bar_features(bar) for bar in sample2])
    
    # If the samples have different lengths, pad the shorter one with zeros
    if features1.shape[0] < features2.shape[0]:
        features1 = np.pad(features1, ((0, features2.shape[0] - features1.shape[0]), (0, 0)))
    elif features2.shape[0] < features1.shape[0]:
        features2 = np.pad(features2, ((0, features1.shape[0] - features2.shape[0]), (0, 0)))
    
    # Flatten the features
    features1 = features1.flatten()
    features2 = features2.flatten()
    
    return 1 / (1 + np.linalg.norm(features1 - features2))

def find_repeating_patterns(segmented_tracks, timings_by_track, pattern_length=4, similarity_threshold=0.3):
    """Find repeating patterns with fixed pattern length."""
    patterns_by_track = {}
    
    for track_idx, bars in segmented_tracks.items():
        patterns = []
        
        for i in range(len(bars) - pattern_length + 1):
            sample = bars[i:i+pattern_length]
            
            # Check if this sample is similar to any existing pattern
            if patterns:
                similarities = [compute_similarity(sample, group[0]) for group in patterns]
                max_similarity_idx = np.argmax(similarities)
                if similarities[max_similarity_idx] > similarity_threshold:
                    patterns[max_similarity_idx].append(sample)
                    continue
            
            patterns.append([sample])
        
        # Filter out patterns that don't repeat
        patterns = [group for group in patterns if len(group) > 1]
        
        # Sort patterns by number of repetitions
        patterns.sort(key=len, reverse=True)
        
        patterns_by_track[track_idx] = patterns
        
        print(f"Track {track_idx}: Found {len(patterns)} pattern groups")
        for i, pattern_group in enumerate(patterns):
            print(f"  Pattern group {i}: {len(pattern_group)} repetitions, length: {pattern_length} bars")
            print(f"    Start ticks: {[p[0]['start'] for p in pattern_group]}")
            print(f"    End ticks: {[p[-1]['end'] for p in pattern_group]}")
    
    return patterns_by_track

def almaz_visualize():
    midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
    
    pattern_length = int(input("Enter the fixed pattern length in bars (1-8): "))
    
    if pattern_length < 1 or pattern_length > 8:
        print("Invalid pattern length. Using default value of 4.")
        pattern_length = 4

    segmented_tracks, timings_by_track = segment_midi_to_bars(midi_file)
    if segmented_tracks is None:
        print("Failed to process MIDI file.")
        exit(1)

    midi_obj = mid_parser.MidiFile(midi_file)
    repeating_patterns = find_repeating_patterns(segmented_tracks, timings_by_track, pattern_length)
    
    for track_idx, patterns in repeating_patterns.items():
        print(f"\nVisualizing Track {track_idx}")
        print(f"Number of pattern groups: {len(patterns)}")
        for i, pattern_group in enumerate(patterns):
            print(f"  Pattern group {i}: {len(pattern_group)} repetitions")
            rep = pattern_group[0]
            print(f"    Representative: start={rep[0]['start']}, end={rep[-1]['end']}, "
                  f"length={len(rep)} bars, notes={sum(len(bar['notes']) for bar in rep)}")
        
        visualize_track_with_patterns(midi_obj, track_idx, patterns, timings_by_track[track_idx])
             
def asle():
    
    tracks = detect_patterns("testing_tools\\i_am_trying_sf_segmenter_a_bit\\Something_in_the_Way.mid")
    
    #Todo
    #For each track
        #For each segment
            #For each note
                #Iterate through notes comparing pitch and duration(+/- some small amount)
                #When a match is found, check if the following notes also match
                #If notes match for 1 bar or more, save as a sample

            #remove duplicate samples, keep only unique

    #if match is found, save the width
    #move both pointers and repeat
    #if match is not found reset first pointer, save pattern into a temp list if it is long enough
    #finally keep the longest unique patterns in that segment

    
    mid_obj = mid_parser.MidiFile("testing_tools\\i_am_trying_sf_segmenter_a_bit\\Something_in_the_Way.mid")

    ticks_per_beat = mid_obj.ticks_per_beat
    time_signature = mid_obj.time_signature_changes
    ticks_per_bar = ticks_per_beat * time_signature[0].denominator #This needs to be changed for music that has time signature changes

    list_of_all_patterns = []
    for track_number, track in enumerate(tracks):
        #if track_number > 0:
        #    break
        list_of_patterns_in_segments = []
        for segment_number, segment in enumerate(track):
            current_pattern = []
            not_pattern = []
            active_pattern = False
            note_number = 0
            pattern_end = 0
            previous_compare_match = 0
            old_note_number = 0
            list_of_patterns_in_current_segment = []
            compare_note_number = note_number + 1
            while note_number < len(segment):
                if compare_note_number != previous_compare_match:
                    if compare_notes(segment=segment, note_number=note_number, compare_note_number=compare_note_number): # if notes are the same, save note to pattern
                        if not active_pattern: #If this is the start of a new pattern
                            if segment[compare_note_number].end - segment[note_number].start >= ticks_per_bar:
                                pattern_end = segment[compare_note_number].start
                                old_note_number = note_number # save start of pattern so we can go back when current pattern ends
                                previous_compare_match = compare_note_number
                                active_pattern = True
                                current_pattern.append(segment[note_number])
                                note_number += 1

                        elif segment[note_number].start == pattern_end: #If it is not a new pattern we want to check if the current pattern is repeating
                            #reset
                            
                            active_pattern = False
                            if len(current_pattern) > 2: #TODO Use sf_segmenter for boundaries to help with boundaries of patterns
                                if not_pattern:
                                    list_of_patterns_in_current_segment.append(not_pattern)
                                    not_pattern = []    
                                list_of_patterns_in_current_segment.append(current_pattern)
                                note_number = note_number + len(current_pattern)
                                compare_note_number = note_number
                                old_note_number = note_number
                                previous_compare_match = compare_note_number
                            else:
                                note_number = old_note_number
                                compare_note_number = previous_compare_match
                            current_pattern = []
                            
                        else: #If the pattern is still going save the note
                            #save
                            current_pattern.append(segment[note_number])
                            note_number += 1

                        compare_note_number += 1
                    else: 
                        if active_pattern:#If there was a pattern it has ended, reset
                            note_number = old_note_number
                            compare_note_number = previous_compare_match
                            active_pattern = False
                            #if len(current_pattern) > 2:
                            #    list_of_patterns_in_current_segment.append(current_pattern)
                            current_pattern = []
                            
                        if compare_note_number >= len(segment):
                            not_pattern.append(segment[note_number])
                            note_number += 1
                            compare_note_number = note_number
                        compare_note_number += 1 #increment until a match is found
                else: 
                    if active_pattern:#If there was a pattern it has ended, reset
                        note_number = old_note_number
                        compare_note_number = previous_compare_match
                        active_pattern = False
                        #if len(current_pattern) > 2:
                        #    list_of_patterns_in_current_segment.append(current_pattern)
                        
                    if compare_note_number >= len(segment):
                        note_number += 1
                        compare_note_number = note_number
                    compare_note_number += 1 #increment until a match is found

            if not_pattern:
                list_of_patterns_in_current_segment.append(not_pattern)
                not_pattern = []   
            if list_of_patterns_in_current_segment: #remove duplicates
                list_of_patterns_in_segments.append(list_of_patterns_in_current_segment)
                list_of_patterns_in_current_segment = []
            else:
                list_of_patterns_in_segments.append([segment])
        list_of_all_patterns.append(list_of_patterns_in_segments)
        list_of_patterns_in_segments = []

        mido_obj = mid_parser.MidiFile("testing_tools\\i_am_trying_sf_segmenter_a_bit\\Something_in_the_Way.mid")
        # create a mid file for track i
        obj = mid_parser.MidiFile()
        obj.ticks_per_beat = mido_obj.ticks_per_beat
        obj.max_tick = mido_obj.max_tick
        obj.tempo_changes = mido_obj.tempo_changes
        obj.time_signature_changes = mido_obj.time_signature_changes
        obj.key_signature_changes = mido_obj.key_signature_changes
        obj.lyrics = mido_obj.lyrics
        obj.markers = mido_obj.markers

        obj.instruments.append(mido_obj.instruments[track_number])
        print(f'{list_of_all_patterns=}')
        for track in list_of_all_patterns:
            for segment in track:
                for pattern in segment:
                    print(len(pattern))
                    new_instrument = Instrument(program=mido_obj.instruments[track_number].program, notes=pattern)
                    obj.instruments.append(new_instrument)

        obj.dump("testing_tools\\test_scripts\\pattern_output\\asle_something_in_the_way_" + str(track_number) + ".mid")

        list_of_all_patterns = []

if __name__ == "__main__":
    
    #almaz()
    asle()
    #almaz_visualize()
    