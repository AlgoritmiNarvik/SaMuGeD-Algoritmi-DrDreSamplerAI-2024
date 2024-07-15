import numpy as np
import os
from collections import Counter, defaultdict

from miditoolkit.midi.parser import MidiFile
from miditoolkit.midi.containers import Instrument, Note
from miditoolkit.midi import parser as mid_parser

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from scipy.spatial.distance import euclidean

def detect_patterns(mido_obj: str | object) -> list:
    """
    Takes path to a midifile or a class instance of miditoolkit.midi.parser.MidiFile

    Returns a list of tracks, each track is a list of segments, each segment containing notes.
    """
    #find end of last note, that is the end of the song or time window to look at
    #1:01:00 is the first(0th) tick in flstudio
    #x:16:24 first number is bar, starting with 1st bar. each bar is divided into steps, every 16 steps is one bar. Each step is divided into 24 ticks.
    #The very start of the track is 1:01:00, which in ticks is 400?
    #1 bar duration = 384 ticks

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

    tracks = [] #This list will contain a list for each track, each list containing segments

    for ins_nr, instrument in enumerate(mido_obj.instruments):
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

            if ticks_since_last_note == 384: #save segment when 1 bar has passed since end of last note
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

def find_repeating_patterns(segmented_tracks, timings_by_track, min_sample_length=1, similarity_threshold=0.1):
    """
    Finds repeating patterns in segmented tracks, grouped by similarity.
    
    Args:
    segmented_tracks (dict): Dictionary of segmented tracks, where each track is a list of bars.
    timings_by_track (dict): Dictionary of bar timings for each track.
    min_sample_length (int): Minimum number of bars for a pattern.
    similarity_threshold (float): Threshold for considering bars similar.
    
    Returns:
    dict: Dictionary where keys are track indices and values are lists of pattern groups.
    """
    patterns_by_track = {}
    
    for track_idx, bars in segmented_tracks.items():
        max_notes = get_max_notes(bars)
        patterns = defaultdict(list)
        
        for i in range(len(bars) - min_sample_length + 1):
            sample = bars[i:i+min_sample_length]
            found_match = False
            
            for pattern_id, pattern_samples in patterns.items():
                if all(are_bars_similar(sample[j], pattern_samples[0][j], similarity_threshold, max_notes) 
                       for j in range(min_sample_length)):
                    patterns[pattern_id].append(sample)
                    found_match = True
                    break
            
            if not found_match:
                patterns[len(patterns)] = [sample]
        
        # sort patterns by number of repetitions
        sorted_patterns = sorted(patterns.values(), key=len, reverse=True)
        patterns_by_track[track_idx] = sorted_patterns
    
    return patterns_by_track

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

def save_pattern_as_midi(pattern, filename):
    """
    FOUND ISSUES HERE
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

if __name__ == "__main__":

    #mido_obj = mid_parser.MidiFile("take_on_me.mid")
    #mido_obj = mid_parser.MidiFile("testing_tools/test_scripts/take_on_me/track1.mid")
    #mido_obj = mid_parser.MidiFile("testing_tools/test_scripts/take_on_me.mid")
    #mido_obj = mid_parser.MidiFile("testing_tools/test_scripts/take_on_me.mid")

    # tracks = detect_patterns("testing_tools/test_scripts/take_on_me.mid")
    # for x, track in enumerate(tracks):
    #     if x == 0:
    #         print(f'Drum track')
    #     else:
    #         print(f'Track {x}')
    #     for i, segment in enumerate(track):
    #         print(f'Segment {i+1}: {segment}', end="\n")
            
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
            
            filename = f"{output_dir}/track{track_idx}_pattern{i:02d}_rep{len(pattern_group):03d}.mid"
            try:
                pattern_midi = extract_pattern(midi_file, track_idx, pattern_group[0], timings_by_track[track_idx])
                pattern_midi.dump(filename)
                print(f"    Saved as: {filename}")
            except Exception as e:
                print(f"    Error saving pattern: {str(e)}")
        print()
