import numpy as np
import os
import sys
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

def get_segments(mido_obj: str | object) -> list:
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
        #if ins_nr > 2: #just here for testing
        #    break
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


def compare_notes(segment, note_number, compare_note_number, duration_difference=10) -> bool: #Add note offset check, pitch offset check
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


def ticks_per_bar(ticks_per_beat, current_note_time, time_signatures) -> int:

    for i in time_signatures:
        if i.time > current_note_time:
            break
        ticks = ticks_per_beat * i.numerator
    
    return ticks

def asle():
    #INPUT_PATH = "testing_tools/test_scripts/take_on_me.mid"
    INPUT_PATH = "C:\\Users\\Pc\\Downloads\\Lakh MIDI Clean\Michael_Jackson\\Beat_It.mid"
    mid_obj = mid_parser.MidiFile(INPUT_PATH)
    """ OS_TYPE = sys.platform
    project_directory = os.path.dirname(os.path.realpath(__file__)) """

    """ if OS_TYPE == "win32":
        output_dir = project_directory + "\\output\\" + INPUT_PATH[:-4]
        input_file_path = project_directory + "\\" + INPUT_PATH
    else:
        output_dir = project_directory + "/output"
        input_file_path = project_directory + "/" + INPUT_PATH


    if isinstance(INPUT_PATH, mid_parser.MidiFile):
        mid_obj = INPUT_PATH
    elif type(mid_obj) is str:
        try:
            mid_obj = mid_parser.MidiFile(INPUT_PATH)
        except:
            print(f'Unable to open {mid_obj}')
    else:
        print(f'Input not a path or instance of MidiFile class')
        return None """

    tracks = get_segments(mid_obj)
    
    
    
    #tracks = detect_patterns("C:\\Users\\asle1\\Downloads\\Lakh MIDI Clean\\Tool\\Eulogy.mid")
    #mid_obj = mid_parser.MidiFile("C:\\Users\\asle1\\Downloads\\Lakh MIDI Clean\\Tool\\Eulogy.mid")

    ticks_per_beat = mid_obj.ticks_per_beat
    time_signatures = mid_obj.time_signature_changes

    list_of_all_patterns = []
    for track_number, track in enumerate(tracks):
        #if track_number > 0: here for testing
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
                            if segment[compare_note_number].end - segment[note_number].start >= ticks_per_bar(ticks_per_beat, segment[note_number].start, time_signatures): #Sets the minimum length limit to 1 bar
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
                        
                    if compare_note_number >= len(segment):
                        note_number += 1
                        compare_note_number = note_number
                    compare_note_number += 1 #increment until a match is found

            if not_pattern:
                list_of_patterns_in_current_segment.append(not_pattern)
                not_pattern = []   
            if list_of_patterns_in_current_segment: #if patterns were found, remove duplicates within segment first.
                duplicates_to_remove = [False]*len(list_of_patterns_in_current_segment)
                #print(f'{list_of_patterns_in_current_segment=}')
                for i, pattern in enumerate(list_of_patterns_in_current_segment):
                    for k, pattern2 in enumerate(list_of_patterns_in_current_segment):
                        if k == i:
                            continue
                        
                        if len(pattern) == len(pattern2):
                            for x in range(len(pattern)):
                                if pattern[x].pitch != pattern2[x].pitch:
                                    break

                            if duplicates_to_remove[i] or duplicates_to_remove[k]:
                                break
                            duplicates_to_remove[k]=True
                #print(f'{duplicates_to_remove=}')

                for x in range(len(duplicates_to_remove)-1,0,-1):
                    if duplicates_to_remove[x]:
                        list_of_patterns_in_current_segment.pop(x)

                #check if patterns in current segment already exist in list patterns for the current track
                duplicates_to_remove = [False]*len(list_of_patterns_in_current_segment)
                for i, pattern in enumerate(list_of_patterns_in_current_segment):
                    for pattern_list in list_of_patterns_in_segments:
                        for k, pattern2 in enumerate(pattern_list):
                            if len(pattern) == len(pattern2):
                                for x in range(len(pattern)):
                                    if pattern[x].pitch != pattern2[x].pitch:
                                        break

                                if duplicates_to_remove[i] or duplicates_to_remove[k]:
                                    break
                                duplicates_to_remove[k]=True

                for x in range(len(duplicates_to_remove)-1,-1,-1):
                    if duplicates_to_remove[x]:
                        list_of_patterns_in_current_segment.pop(x)

                list_of_patterns_in_segments.append(list_of_patterns_in_current_segment)
                #print(f'{list_of_patterns_in_segments=}')

            else: #Segments might be short and already in pattern list. Might need to redo this 
                segment_is_a_duplicate = False
                for segment_group in list_of_patterns_in_segments:
                    for k, pattern2 in enumerate(pattern_list):
                        
                        if len([segment]) == len(pattern2):
                            for x in range(len([segment])):
                                if [segment][x].pitch != pattern2[x].pitch:
                                    break

                            segment_is_a_duplicate=True

                if segment_is_a_duplicate == False:
                    list_of_patterns_in_segments.append([segment])


        list_of_all_patterns.append(list_of_patterns_in_segments)
        list_of_patterns_in_segments = []

        #mido_obj = mid_parser.MidiFile("testing_tools/test_scripts/take_on_me.mid")
        # create a mid file for track i
        obj = mid_parser.MidiFile()
        obj.ticks_per_beat = mid_obj.ticks_per_beat
        obj.max_tick = mid_obj.max_tick
        obj.tempo_changes = mid_obj.tempo_changes
        obj.time_signature_changes = mid_obj.time_signature_changes
        obj.key_signature_changes = mid_obj.key_signature_changes
        obj.lyrics = mid_obj.lyrics
        obj.markers = mid_obj.markers

        obj.instruments.append(mid_obj.instruments[track_number+1])
        #print(f'{list_of_all_patterns=}')
        for track in list_of_all_patterns:
            for segment in track:
                for pattern in segment:
                    print(len(pattern))
                    new_instrument = Instrument(program=mid_obj.instruments[track_number+1].program, notes=pattern)
                    obj.instruments.append(new_instrument)

        obj.dump("testing_tools/test_scripts/pattern_output/Beat_It" + str(track_number) + ".mid")

        list_of_all_patterns = []


if __name__ == "__main__":

    asle()
