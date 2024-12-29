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


def get_segments(mid_obj: str | object) -> list:
    """
    Takes path to a midifile or a class instance of miditoolkit.midi.parser.MidiFile

    Returns a list of tracks, each track is a list of segments, each segment containing notes.
    """

    # 1:01:00 is the first(0th) tick in flstudio
    # x:16:24 first number is bar, starting with 1st bar. each bar is divided into steps, every 16 steps is one bar. Each step is divided into 24 ticks.
    # 1 bar duration = 384 ticks (for 4/4 time signature, 2nd number is how many beats are in each bar)

    if isinstance(mid_obj, mid_parser.MidiFile):
        mid_obj = mid_obj
    elif type(mid_obj) is str:
        try:
            mid_obj = mid_parser.MidiFile(mid_obj)
        except:
            print(f'Unable to open {mid_obj}')
    else:
        print(f'Input not a path or instance of MidiFile class')
        return None

    ticks_per_beat = mid_obj.ticks_per_beat
    time_signatures = mid_obj.time_signature_changes

    tracks = []  # This list will contain a list for each track, each list containing segments

    for ins_nr, instrument in enumerate(mid_obj.instruments):
        if instrument.is_drum == True:
            continue
        # if ins_nr > 2: #just here for testing
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
        # print(f'Track: {ins_nr}, {instrument=}\n {first_note_start=}, {last_note_end=}')

        note_playing = False  # Is a note playing?
        note_playing_end = 0  # The tick the currently active note will end on
        # Set value greater than 384 so that we don't save an empty segment at the start
        ticks_since_last_note = 385
        segments = []  # The list where segments/samples will be saved
        temp = []  # Temporary list that keeps track of notes in the current segment
        notes_to_remove = []  # Empty set to keep track of note indecies in the list of notes

        for tick in range(0, last_note_end):
            notes_to_remove = []  # Empty set to keep track of note indecies in the list of notes
            if note_playing == False:  # Increment silence counter if no note is playing
                ticks_since_last_note += 1
            elif tick >= note_playing_end:  # Check if the playing note has ended
                note_playing = False
                note_playing_end = 0
            # Iterate through notes to see if they are currently playing
            for x, note in enumerate(sorted_notes):
                if tick == note.start:
                    temp.append(note)
                    note_playing = True
                    note_playing_end = note.end if note.end > note_playing_end else note_playing_end
                    ticks_since_last_note = 0
                    # Add played notes to a list so we can remove them later
                    notes_to_remove.append(note)

            # Remove played notes from list of notes to reduce code execution time
            for note in notes_to_remove[::-1]:
                sorted_notes.remove(note)

            # save segment when 1 bar has passed since end of last note
            if ticks_since_last_note == ticks_per_bar(ticks_per_beat, tick, time_signatures):
                segments.append(temp)
                temp = []

        if len(temp) > 0:
            segments.append(temp)
            temp = []

        tracks.append(segments)

    return tracks


# Add note offset check, pitch offset check
def compare_notes(segment, note_number, compare_note_number, current_pattern, duration_difference=10) -> bool:
    """Returns True if the notes have the same pitch and within specified duration difference"""

    if segment[note_number].pitch == segment[compare_note_number].pitch:
        note_duration = segment[note_number].end - segment[note_number].start
        compare_note_duration = segment[compare_note_number].end - \
            segment[compare_note_number].start
        if abs(note_duration - compare_note_duration) <= duration_difference:
            return True
    else:  # There can be patterns where multiple notes start at the same time, but are listed in different orders.
        for i in range(-7, 8):
            try:
                if (segment[compare_note_number].start == segment[compare_note_number+i].start) and (segment[note_number].pitch == segment[compare_note_number+i].pitch):
                    note_duration = segment[note_number].end - \
                        segment[note_number].start
                    compare_note_duration = segment[compare_note_number].end - \
                        segment[compare_note_number].start
                    if abs(note_duration - compare_note_duration) <= duration_difference:
                        if segment[compare_note_number+i] not in current_pattern:
                            return True
            except IndexError:
                continue

    return False


def ticks_per_bar(ticks_per_beat, current_note_time, time_signatures) -> int:

    if len(time_signatures) == 0:  # If there is no timesignatures in the midi we assume 4 beats per bar
        return 384

    for i in time_signatures:
        if i.time > current_note_time:
            break
        ticks = ticks_per_beat * i.numerator

    return ticks


def add_and_reset_current(active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match):
    active_pattern = False
    if len(current_pattern) > 2:  # TODO Use sf_segmenter for boundaries to help with boundaries of patterns
        list_of_patterns_in_current_segment.append(current_pattern)
        #note_number = note_number + len(current_pattern)
        #previous_compare_match = compare_note_number +1 
        #compare_note_number = note_number
        #old_note_number = note_number
    #else:
    note_number = old_note_number
    compare_note_number = previous_compare_match

    return active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match


def asle(INPUT_PATH, OUTPUT_DIR, ONE_FILE_PER_PATTERN):
    KEEP_ORIGINAL = False

    print(f'Processing {INPUT_PATH} ...')
    # INPUT_PATH = "testing_tools/test_scripts/take_on_me.mid"
    # INPUT_PATH = "C:\\Users\\Pc\\Downloads\\Lakh MIDI Clean\\Michael_Jackson\\Beat_It.mid"
    # mid_obj = mid_parser.MidiFile(INPUT_PATH)

    if isinstance(INPUT_PATH, mid_parser.MidiFile):
        mid_obj = INPUT_PATH
    elif type(INPUT_PATH) is str:
        try:
            mid_obj = mid_parser.MidiFile(INPUT_PATH)
        except Exception as e:
            print(f'Unable to open {INPUT_PATH}')
            print(f'Exception: {e=}')
            return None
    else:
        print(f'Input not a path or instance of MidiFile class')
        return None

    tracks = get_segments(mid_obj)

    ticks_per_beat = mid_obj.ticks_per_beat
    time_signatures = mid_obj.time_signature_changes

    list_of_all_patterns = []
    pattern_number = 1
    for track_number, track in enumerate(tracks):
        if track_number == 2:  # here for testing
            pass
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
                # if compare_note_number == previous_compare_match:
                #    if active_pattern:#If there was a pattern it has ended, reset
                #        note_number = old_note_number
                #        compare_note_number = previous_compare_match + 1
                #        active_pattern = False

                # if notes are the same, save note to pattern
                if compare_notes(segment=segment, note_number=note_number, current_pattern=current_pattern, compare_note_number=compare_note_number):
                    if not active_pattern:  # If this is the start of a new pattern
                        # Sets the minimum length limit to 1 bar
                        if segment[compare_note_number].end - segment[note_number].start >= ticks_per_bar(ticks_per_beat, segment[note_number].start, time_signatures):
                            pattern_end = segment[compare_note_number].start
                            # save start of pattern so we can go back when current pattern ends
                            old_note_number = note_number
                            previous_compare_match = compare_note_number
                            active_pattern = True
                            current_pattern.append(segment[note_number])
                            note_number += 1

                    # If it is not a new pattern we want to check if the current pattern is repeating
                    elif segment[note_number].start == pattern_end:
                        # reset
                        active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match = add_and_reset_current(
                            active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match)
                        current_pattern = []

                    else:  # If the pattern is still going save the note
                        # save
                        current_pattern.append(segment[note_number])
                        note_number += 1

                else:
                    if active_pattern:  # If there was a pattern it has ended, reset
                        active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match = add_and_reset_current(
                            active_pattern, current_pattern, list_of_patterns_in_current_segment, note_number, compare_note_number, old_note_number, previous_compare_match)
                        current_pattern = []

                compare_note_number += 1  # increment until a match is found

                if compare_note_number >= len(segment):
                    # not_pattern.append(segment[note_number])
                    note_number += 1
                    compare_note_number = note_number

            if not_pattern:
                # list_of_patterns_in_current_segment.append(not_pattern)
                not_pattern = []
            # if patterns were found, remove duplicates within segment first.
            if list_of_patterns_in_current_segment:
                duplicates_to_remove = [False] * \
                    len(list_of_patterns_in_current_segment)
                for i, pattern in enumerate(list_of_patterns_in_current_segment):
                    for k, pattern2 in enumerate(list_of_patterns_in_current_segment):
                        if k == i:
                            continue

                        if len(pattern) == len(pattern2):
                            for x in range(len(pattern)):
                                if pattern[x].pitch != pattern2[x].pitch:
                                    break
                            try:
                                if duplicates_to_remove[i] or duplicates_to_remove[k]:
                                    break
                                duplicates_to_remove[k] = True
                            except IndexError:
                                pass

                for x in range(len(duplicates_to_remove)-1, 0, -1):
                    if duplicates_to_remove[x]:
                        list_of_patterns_in_current_segment.pop(x)

                # check if patterns in current segment already exist in list patterns for the current track
                duplicates_to_remove = [False] * \
                    len(list_of_patterns_in_current_segment)
                for i, pattern in enumerate(list_of_patterns_in_current_segment):
                    for pattern_list in list_of_patterns_in_segments:
                        for k, pattern2 in enumerate(pattern_list):
                            if len(pattern) == len(pattern2):
                                for x in range(len(pattern)):
                                    if pattern[x].pitch != pattern2[x].pitch:
                                        break
                                try:
                                    if duplicates_to_remove[i] or duplicates_to_remove[k]:
                                        break
                                    duplicates_to_remove[k] = True
                                except IndexError:
                                    pass

                for x in range(len(duplicates_to_remove)-1, -1, -1):
                    if duplicates_to_remove[x]:
                        list_of_patterns_in_current_segment.pop(x)

                list_of_patterns_in_segments.append(
                    list_of_patterns_in_current_segment)

            """ else: #Segments might be short and already in pattern list. Might need to redo this 
                segment_is_a_duplicate = False
                for segment_group in list_of_patterns_in_segments:
                    for k, pattern2 in enumerate(pattern_list):
                        
                        if len([segment]) == len(pattern2):
                            for x in range(len([segment])):
                                if [segment][x].pitch != pattern2[x].pitch:
                                    break

                            segment_is_a_duplicate=True

                if segment_is_a_duplicate == False:
                    list_of_patterns_in_segments.append([segment]) """

        if list_of_patterns_in_segments:
            list_of_all_patterns.append(list_of_patterns_in_segments)
            list_of_patterns_in_segments = []

        if not list_of_all_patterns:
            return None

        if ONE_FILE_PER_PATTERN:
            # pattern_number = 1
            for track in list_of_all_patterns:
                for segment in track:
                    name_number = 1
                    for pattern in segment:
                        obj = mid_parser.MidiFile()
                        obj.ticks_per_beat = mid_obj.ticks_per_beat
                        obj.max_tick = mid_obj.max_tick
                        obj.tempo_changes = mid_obj.tempo_changes
                        obj.time_signature_changes = mid_obj.time_signature_changes
                        obj.key_signature_changes = mid_obj.key_signature_changes
                        obj.lyrics = mid_obj.lyrics
                        obj.markers = mid_obj.markers

                        # print(len(pattern))
                        instrument_name = mid_obj.instruments[track_number].name
                        new_name = "pattern" + " " + str(name_number)
                        new_instrument = Instrument(
                            program=mid_obj.instruments[track_number].program, name=new_name, notes=pattern)
                        obj.instruments.append(new_instrument)

                        track_path = OUTPUT_DIR + "/" + instrument_name
                        if not os.path.exists(track_path):
                            os.mkdir(track_path)
                        # Save pattern_n into a midifile under "artist/song_name/instrument/.."
                        obj.dump(track_path + "/pattern" +
                                 str(pattern_number) + ".mid")
                        pattern_number += 1
        else:
            obj = mid_parser.MidiFile()
            obj.ticks_per_beat = mid_obj.ticks_per_beat
            obj.max_tick = mid_obj.max_tick
            obj.tempo_changes = mid_obj.tempo_changes
            obj.time_signature_changes = mid_obj.time_signature_changes
            obj.key_signature_changes = mid_obj.key_signature_changes
            obj.lyrics = mid_obj.lyrics
            obj.markers = mid_obj.markers

            if KEEP_ORIGINAL:
                # add the original track as the first track in the new file
                obj.instruments.append(mid_obj.instruments[track_number])
            for track in list_of_all_patterns:
                for segment in track:
                    name_number = 1
                    for pattern in segment:
                        # print(len(pattern))
                        new_name = mid_obj.instruments[track_number].name
                        new_name = "pattern" + " " + str(name_number)
                        new_instrument = Instrument(
                            program=mid_obj.instruments[track_number].program, name=new_name, notes=pattern)
                        obj.instruments.append(new_instrument)
                        name_number += 1

            obj.dump(OUTPUT_DIR + "/track" + str(track_number) + ".mid")

        list_of_all_patterns = []

    print(f'Finished processing {INPUT_PATH}')


if __name__ == "__main__":

    asle()
