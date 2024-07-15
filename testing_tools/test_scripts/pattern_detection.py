import numpy as np
from miditoolkit.midi import parser as mid_parser  

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

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

def convert_bar_to_feature_vector(bar):
    """
    converts a bar to a feature vector
    
    args:
    bar (dict): a dictionary representing a bar
    
    returns:
    np.array: a feature vector representing the bar
    """
    # simple representation of 
    # [number of notes, average pitch, average velocity, bar duration]
    n_notes = len(bar['notes'])
    avg_pitch = np.mean([note.pitch for note in bar['notes']]) if n_notes > 0 else 0
    avg_velocity = np.mean([note.velocity for note in bar['notes']]) if n_notes > 0 else 0
    duration = bar['end'] - bar['start']
    
    return np.array([n_notes, avg_pitch, avg_velocity, duration])

def cluster_bars(bars, n_clusters=5):
    """
    clusters bars using k-means algorithm
    
    args:
    bars (list): list of bars
    n_clusters (int): number of clusters to form
    
    returns:
    list: cluster labels for each bar
    """
    # convert bars to feature vectors
    feature_vectors = np.array([convert_bar_to_feature_vector(bar) for bar in bars])
    
    # normalize features
    scaler = StandardScaler()
    feature_vectors_normalized = scaler.fit_transform(feature_vectors)
    
    # perform clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(feature_vectors_normalized)
    
    return cluster_labels

def find_repeating_patterns(segmented_tracks, n_clusters=5):
    """
    finds repeating patterns in segmented tracks
    
    args:
    segmented_tracks (dict): dictionary of segmented tracks
    n_clusters (int): number of clusters to form for each track
    
    returns:
    dict: dictionary of repeating patterns for each track
    """
    patterns_by_track = {}
    
    for track_idx, bars in segmented_tracks.items():
        cluster_labels = cluster_bars(bars, n_clusters)
        
        # find the most common cluster (the most repeating pattern)
        most_common_cluster = np.argmax(np.bincount(cluster_labels))
        
        # get all bars that belong to the most common cluster
        repeating_pattern = [bar for bar, label in zip(bars, cluster_labels) if label == most_common_cluster]
        
        patterns_by_track[track_idx] = repeating_pattern
    
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
        print(f"track {track_idx}: {len(patterns)} repeating patterns")
        for i, pattern in enumerate(patterns[:10]):  # show first 5 patterns
            print(f"  pattern {i}: start={pattern['start']}, end={pattern['end']}, notes={len(pattern['notes'])}")
        if len(patterns) > 10:
            print("  ...")
            