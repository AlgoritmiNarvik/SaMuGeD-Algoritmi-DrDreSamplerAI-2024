import numpy as np
from miditoolkit.midi import parser as mid_parser  

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
            
    midi_file = "take_on_me.mid"
    segmented_tracks = segment_midi_to_bars(midi_file)

    for track_idx, bars in segmented_tracks.items():
        print(f"track {track_idx}: {len(bars)} bars")
