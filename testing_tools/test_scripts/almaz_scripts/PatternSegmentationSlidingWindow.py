import os
import mido
import numpy as np
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
                        notes[-(i+1)] = (note[0], note[1], duration, note[2])
                        break
        track_notes = [note for note in notes if len(note) == 4]
        if track_notes:
            tracks_notes.append(track_notes)

    print(f"Read {len(tracks_notes)} tracks with notes from the MIDI file")
    return tracks_notes, midi_file

# TODO: chords are not being processed properly, needs to be fixed
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

# TODO: chords are not being processed properly, needs to be fixed
def segment_track(notes, repeating_motifs, max_silence_ticks=1000):
    segments = []
    used_indices = set()
    
    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: (len(x[0]), len(x[1]['positions'])), reverse=True)
    
    for motif, data in sorted_motifs:
        motif_id = data['id']
        positions = data['positions']
        for pos in positions:
            if all(i not in used_indices for i in range(pos, pos + len(motif))):
                start_tick = notes[pos][1]
                end_tick = notes[pos + len(motif) - 1][1] + notes[pos + len(motif) - 1][2]
                # Check for maximum silence
                is_valid_segment = True
                for i in range(pos, pos + len(motif) - 1):
                    if notes[i + 1][1] - (notes[i][1] + notes[i][2]) > max_silence_ticks:
                        is_valid_segment = False
                        break
                if is_valid_segment:
                    segments.append((start_tick, end_tick, len(positions), motif, motif_id))
                    used_indices.update(range(pos, pos + len(motif)))
    
    # Add non-motif segments
    all_times = sorted(set([0] + [note[1] for note in notes] + [note[1] + note[2] for note in notes]))
    current_start = 0
    for end in all_times[1:]:
        if not any(s <= current_start < end <= e for s, e, _, _, _ in segments):
            if end > current_start:  # Ensure we're not adding empty segments
                segments.append((current_start, end, 1, (), -1))
        current_start = end
    
    all_segments = sorted(segments, key=lambda x: x[0])
    
    print(f"Created {len(all_segments)} segments (including non-motif segments)")
    return all_segments

def save_patterns_to_midi(original_midi, notes, segments, output_file_path):
    # TODO: the rest (between segments for example) should be grouped as one segment and be displayed as the same track

    output_midi = mido.MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)

    # Copy metadata track if it exists
    if original_midi.tracks and not any(msg.type == 'note_on' for msg in original_midi.tracks[0]):
        output_midi.tracks.append(original_midi.tracks[0])

    # Add the original track as the first track (exact copy)
    output_midi.tracks.append(original_midi.tracks[-1])

    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda x: x[0])

    # Add tracks for all non-empty segments
    for i, segment in enumerate(sorted_segments):
        start_time, end_time, count, motif, motif_id = segment
        
        # Get notes for this segment
        segment_notes = [n for n in notes if start_time <= n[1] < end_time]
        
        # Skip if there are no notes in this segment
        if not segment_notes:
            continue

        track = mido.MidiTrack()
        
        # Add program change (use the program from the original track if available)
        original_program = next((msg.program for msg in original_midi.tracks[-1] if msg.type == 'program_change'), 0)
        track.append(mido.Message('program_change', program=original_program, time=0))

        # Add silence before the segment
        track.append(mido.Message('note_on', note=0, velocity=0, time=int(start_time)))

        current_time = start_time
        for note in sorted(segment_notes, key=lambda x: x[1]):
            delta_on = max(0, note[1] - current_time)
            track.append(mido.Message('note_on', note=note[0], velocity=note[3], time=int(delta_on)))
            track.append(mido.Message('note_off', note=note[0], velocity=0, time=int(note[2])))
            current_time = note[1] + note[2]

        # Add silence after the segment to fill the rest of the track
        if current_time < original_midi.length:
            track.append(mido.Message('note_on', note=0, velocity=0, time=int(original_midi.length - current_time)))

        output_midi.tracks.append(track)
        
        if motif:
            print(f"Added track for motif segment {i+1}: Start={start_time}, End={end_time}, Motif={motif}")
        else:
            print(f"Added track for non-motif segment {i+1}: Start={start_time}, End={end_time}")

    # Save the MIDI file
    output_midi.save(output_file_path)
    print(f"Original track and all non-empty segments saved to {output_file_path}")
                  
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

    # Print report for this track
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
            print("-" * 20)
            
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
