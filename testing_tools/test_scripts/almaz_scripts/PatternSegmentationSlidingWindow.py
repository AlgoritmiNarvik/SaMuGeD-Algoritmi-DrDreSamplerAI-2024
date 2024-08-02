import os
import mido
from collections import defaultdict

def read_midi_file(file_path):
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

def group_notes_by_time(notes):
    """
    Group notes that start at the same time, considering them as chords.
    """
    chords = defaultdict(list)
    for note in notes:
        chords[note[1]].append(note)
    return chords

def find_repeating_motifs(notes, min_length, max_length):
    motifs = {}
    pitches_only = [note[0] for note in notes]
    motif_id = 0
    
    for length in range(min_length, min(max_length, len(pitches_only)) + 1):
        for i in range(len(pitches_only) - length + 1):
            motif = tuple(pitches_only[i:i+length])
            if motif in motifs:
                motifs[motif]['positions'].append(i)
            else:
                motifs[motif] = {'id': motif_id, 'positions': [i]}
                motif_id += 1
    
    repeating_motifs = {m: v for m, v in motifs.items() if len(v['positions']) > 1}
    print(f"Found {len(repeating_motifs)} repeating motifs")
    if len(repeating_motifs) > 0:
        print("Example motif:", next(iter(repeating_motifs)))
    return repeating_motifs

def find_repeating_chord_motifs(chords, min_length, max_length):
    """
    Identify repeating chord motifs based on chord sequences.
    """
    motifs = {}
    chord_sequences = list(chords.values())
    motif_id = 0

    for length in range(min_length, min(max_length, len(chord_sequences)) + 1):
        for i in range(len(chord_sequences) - length + 1):
            motif = tuple(tuple(note[0] for note in chord) for chord in chord_sequences[i:i+length])
            if motif in motifs:
                motifs[motif]['positions'].append(i)
            else:
                motifs[motif] = {'id': motif_id, 'positions': [i]}
                motif_id += 1

    repeating_motifs = {m: v for m, v in motifs.items() if len(v['positions']) > 1}
    print(f"Found {len(repeating_motifs)} repeating chord motifs")
    if len(repeating_motifs) > 0:
        print("Example chord motif:", next(iter(repeating_motifs)))
    return repeating_motifs

def segment_track(notes, repeating_motifs, max_silence_ticks=1000):
    segments = []
    used_indices = set()
    last_end_tick = 0  # This will track the end of the last segment to manage silences

    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: (len(x[0]), len(x[1]['positions'])), reverse=True)

    for motif, data in sorted_motifs:
        motif_id = data['id']
        positions = data['positions']
        for pos in positions:
            if all(i not in used_indices for i in range(pos, pos + len(motif))):
                start_tick = notes[pos][1]
                end_tick = notes[pos + len(motif) - 1][1] + notes[pos + len(motif) - 1][2]
                if start_tick > last_end_tick:
                    # Handle silence between motifs
                    segments.append((last_end_tick, start_tick, 1, (), -1))
                segments.append((start_tick, end_tick, len(positions), motif, motif_id))
                used_indices.update(range(pos, pos + len(motif)))
                last_end_tick = end_tick

    # Handle trailing silence if any
    max_time = max(note[1] + note[2] for note in notes)
    if last_end_tick < max_time:
        segments.append((last_end_tick, max_time, 1, (), -1))

    all_segments = sorted(segments, key=lambda x: x[0])
    print(f"Created {len(all_segments)} segments (including non-motif segments)")
    return all_segments

def save_patterns_to_midi(original_midi, notes, segments, output_file_path):
    output_midi = mido.MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)
    
    # Keep the original track for reference
    output_midi.tracks.append(original_midi.tracks[-1])  # assuming the last track is the one with notes
    
    # Append a new track for each segment
    for segment in segments:
        track = mido.MidiTrack()
        output_midi.tracks.append(track)

        start_time, end_time, count, motif, motif_id = segment
        last_event_time = 0  # This keeps track of the end time of the last event

        # Handle the silence before the first note of the segment
        if start_time > last_event_time:
            silence_before = start_time - last_event_time
            if silence_before < 0:
                print("Calculated negative silence, adjusting to 0.")
                silence_before = 0
            track.append(mido.Message('note_on', note=0, velocity=0, time=silence_before))

        for note in notes:
            if start_time <= note[1] < end_time:
                # Calculate the start time of the note relative to the start of the segment
                note_start_time = note[1] - start_time
                # Ensure there's no overlap or negative time
                if note_start_time < last_event_time:
                    note_start_time = last_event_time
                note_duration = note[2]
                
                # Note on
                delta_time = note_start_time - last_event_time
                track.append(mido.Message('note_on', note=note[0], velocity=note[3], time=delta_time))
                
                # Note off
                track.append(mido.Message('note_off', note=note[0], velocity=0, time=note_duration))
                last_event_time = note_start_time + note_duration

    # Save the MIDI file
    output_midi.save(output_file_path)
    print(f"Saved MIDI with original and segmented tracks to {output_file_path}")
                       
def process_track(track_notes, track_index, original_midi, output_dir, input_filename):
    print(f"\nProcessing Track {track_index}")
    repeating_motifs = find_repeating_motifs(track_notes, min_length=4, max_length=30)
    segments = segment_track(track_notes, repeating_motifs, max_silence_ticks=1000)

    if len(segments) == 0:
        print("Warning: No segments found for this track.")
        return

    # Generate the output file name for this track
    output_filename = f"{os.path.splitext(input_filename)[0]}_track{track_index}_patterns_SlidingWindow.mid"
    output_file_path = os.path.join(output_dir, output_filename)

    # Save patterns to MIDI file
    save_patterns_to_midi(original_midi, track_notes, segments, output_file_path)

"""     # Print report for this track
    print(f"Segment Report for Track {track_index}:")
    for i, (start_time, end_time, count, motif, motif_id) in enumerate(segments):
        if motif:  # Only print segments with non-empty motifs
            print(f"Segment {i + 1}:")
            print(f"  Start: {start_time} ticks")
            print(f"  End: {end_time} ticks")
            print(f"  Length: {end_time - start_time} ticks")
            print(f"  Motif ID: {motif_id}")
            print(f"  Repetitions: {count}")
            print(f"  Motif: {motif}")
            print("-" * 20) """

def main(file_path):
    try:
        tracks_notes, original_midi = read_midi_file(file_path)
        
        if not tracks_notes:
            print("Error: No notes found in the MIDI file. Please check the file format and content.")
            return

        # Create the output directory if it doesn't exist
        output_dir = os.path.join('testing_tools', 'test_scripts', 'pattern_output', 'PatternSegmentationSlidingWindow')
        os.makedirs(output_dir, exist_ok=True)

        # Process each track
        input_filename = os.path.basename(file_path)
        for i, track_notes in enumerate(tracks_notes):
            process_track(track_notes, i, original_midi, output_dir, input_filename)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

# Path to your MIDI file
file_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
main(file_path)
