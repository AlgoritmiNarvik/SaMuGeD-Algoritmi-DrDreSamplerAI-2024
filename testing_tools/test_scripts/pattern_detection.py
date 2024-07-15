import numpy as np
from miditoolkit.midi import parser as mid_parser  
from collections import Counter, defaultdict

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
    segments a MIDI file into bars for each track
    
    args:
    midi_file (str): path to the MIDI file
    
    returns:
    dict: a dictionary where keys are track numbers and values are lists of bars
    """
    try:
        midi_obj = mid_parser.MidiFile(midi_file)
    except:
        print(f'unable to open {midi_file}')
        return None

    segments_by_track = {}

    for track_idx, instrument in enumerate(midi_obj.instruments):
        notes = instrument.notes
        sorted_notes = sorted(notes, key=lambda x: x.start)
        
        if not sorted_notes:
            continue  # skip empty tracks
        
        # find time boundaries of the track
        track_start = sorted_notes[0].start
        track_end = max(note.end for note in sorted_notes)
        
        # get time signature information
        # assume time signature doesn't change
        # (which is a weak point, this should be upgraded in the future)
        time_sig = midi_obj.time_signature_changes[0]  # assume time signature doesn't change
        ticks_per_bar = time_sig.numerator * midi_obj.ticks_per_beat * 4 // time_sig.denominator
        
        # segment into bars
        bars = []
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
            
            current_bar_start += ticks_per_bar

        segments_by_track[track_idx] = bars

    return segments_by_track

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

def find_repeating_patterns(segmented_tracks, similarity_threshold=0.1):
    """
    Finds repeating patterns in segmented tracks, grouped by similarity.
    
    This function identifies and groups similar bars within each track, effectively
    finding repeating musical patterns. It uses a similarity-based approach rather than
    clustering, allowing for detection of all repeating patterns regardless of their number.
    
    The function now adapts to the complexity of each track by using a track-specific
    maximum number of notes for feature vector creation.
    
    Algorithm:
    1. For each track:
        a. Determine the maximum number of notes in any bar of the track.
        b. Iterate through all bars in the track.
        c. For each bar, compare it with the representative bar of each existing pattern group.
        d. If the bar is similar to an existing pattern (based on the similarity threshold),
           add it to that pattern group.
        e. If the bar doesn't match any existing pattern, create a new pattern group with this bar.
    2. Sort pattern groups by the number of repetitions (group size) in descending order.
    
    Args:
    segmented_tracks (dict): Dictionary of segmented tracks, where each track is a list of bars.
    similarity_threshold (float): Threshold for considering bars similar. Lower values result
                                  in stricter matching, higher values allow more variation.
    
    Returns:
    dict: Dictionary where keys are track indices and values are lists of pattern groups.
          Each pattern group is a list of similar bars, sorted by frequency of occurrence.
    """
    patterns_by_track = {}
    
    for track_idx, bars in segmented_tracks.items():
        max_notes = get_max_notes(bars)
        patterns = defaultdict(list)
        for i, bar in enumerate(bars):
            found_match = False
            for pattern_id, pattern_bars in patterns.items():
                if are_bars_similar(bar, pattern_bars[0], similarity_threshold, max_notes):
                    patterns[pattern_id].append(bar)
                    found_match = True
                    break
            if not found_match:
                patterns[len(patterns)] = [bar]
        
        # sort patterns by number of repetitions
        sorted_patterns = sorted(patterns.values(), key=len, reverse=True)
        patterns_by_track[track_idx] = sorted_patterns
    
    return patterns_by_track

if __name__ == "__main__":

    midi_file = "testing_tools/test_scripts/take_on_me/track1.mid"
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
            
    segmented_tracks = segment_midi_to_bars(midi_file)

    # usage for segmenting tracks into bars
    # for track_idx, bars in segmented_tracks.items():
    #     print(f"track {track_idx}: {len(bars)} bars")
    #     for i, bar in enumerate(bars[:10]):  # This will iterate over the first 10 bars
    #         print(f"  bar {i}: start={bar['start']}, end={bar['end']}, notes={len(bar['notes'])}")
    #     if len(bars) > 10:
    #         print("  ... and so on")  
        
    # usage for finding patterns
    segmented_tracks = segment_midi_to_bars(midi_file)
    repeating_patterns = find_repeating_patterns(segmented_tracks)

for track_idx, patterns in repeating_patterns.items():
    print(f"track {track_idx}:")
    for i, pattern_group in enumerate(patterns):
        print(f"  pattern group {i}: {len(pattern_group)} repetitions")
        print(f"    representative: start={pattern_group[0]['start']}, end={pattern_group[0]['end']}, notes={len(pattern_group[0]['notes'])}")
        print(f"    span: from bar {pattern_group[0]['start']} to {pattern_group[-1]['end']}")
        print()
            