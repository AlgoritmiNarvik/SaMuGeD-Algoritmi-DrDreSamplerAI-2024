import os
import mido
import numpy as np
from collections import defaultdict

def read_midi_file(file_path):
    midi_file = mido.MidiFile(file_path)
    notes = []
    current_time = 0

    for track in midi_file.tracks:
        track_notes = []
        track_time = 0
        for msg in track:
            track_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                track_notes.append((msg.note, track_time, msg.velocity))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                for i, note in enumerate(reversed(track_notes)):
                    if note[0] == msg.note and len(note) == 3:
                        duration = track_time - note[1]
                        track_notes[-(i+1)] = (note[0], note[1], duration, note[2])
                        break
        notes.extend([note for note in track_notes if len(note) == 4])

    notes.sort(key=lambda x: x[1])  # Sort notes by start time
    print(f"Read {len(notes)} notes from {len(midi_file.tracks)} tracks")
    return notes, midi_file

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
    
    # Add non-pattern segments
    all_times = sorted(set([0] + [note[1] for note in notes] + [note[1] + note[2] for note in notes]))
    all_segments = sorted(segments + [(start, end, 1, (), -1) for start, end in zip(all_times, all_times[1:]) if not any(s <= start < end <= e for s, e, _, _, _ in segments)])
    
    print(f"Created {len(all_segments)} segments (including non-pattern segments)")
    return all_segments

def save_patterns_to_midi(original_midi, notes, segments, output_file_path):
    output_midi = mido.MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)

    # Copy all original tracks
    for track in original_midi.tracks:
        output_midi.tracks.append(track)

    # Add pattern tracks
    for i, segment in enumerate(segments):
        start_time, end_time, count, motif, motif_id = segment
        
        # Skip segments with empty motifs
        if not motif:
            continue

        print(f"Processing segment {i+1}: Start={start_time}, End={end_time}")
        track = mido.MidiTrack()
        
        # Add program change (you can change the instrument if needed)
        track.append(mido.Message('program_change', program=0, time=0))

        # Add silence before the pattern
        if start_time > 0:
            track.append(mido.Message('note_on', note=0, velocity=0, time=start_time))

        current_time = start_time
        for note in notes:
            if start_time <= note[1] < end_time:
                # Note on
                delta_time = max(0, note[1] - current_time)
                track.append(mido.Message('note_on', note=note[0], velocity=note[3], time=int(delta_time)))
                
                # Note off
                track.append(mido.Message('note_off', note=note[0], velocity=note[3], time=int(note[2])))
                
                current_time = note[1] + note[2]

        # Add silence after the pattern
        if current_time < end_time:
            track.append(mido.Message('note_on', note=0, velocity=0, time=max(0, end_time - current_time)))

        output_midi.tracks.append(track)
        
        print(f"Added {len(track)} messages to track {i+1}")

    # Save the MIDI file
    output_midi.save(output_file_path)
    print(f"Patterns saved to {output_file_path}")
     
def main(file_path):
    try:
        notes, original_midi = read_midi_file(file_path)
        print(f"Read {len(notes)} notes from the MIDI file")
        
        if len(notes) == 0:
            print("Error: No notes found in the MIDI file. Please check the file format and content.")
            return

        repeating_motifs = find_repeating_motifs(notes, min_length=4, max_length=30000)
        segments = segment_track(notes, repeating_motifs, max_silence_ticks=1000)

        if len(segments) == 0:
            print("Warning: No segments found. Adjusting parameters...")
            # repeating_motifs = find_repeating_motifs(notes, min_length=4, max_length=20)
            # segments = segment_track(notes, repeating_motifs, max_silence_ticks=2000)

        # Create the output directory if it doesn't exist
        output_dir = os.path.join('testing_tools', 'test_scripts', 'pattern_output', 'PatternSegmentationSlidingWindow')
        os.makedirs(output_dir, exist_ok=True)

        # Generate the output file name
        input_filename = os.path.basename(file_path)
        output_filename = f"{os.path.splitext(input_filename)[0]}_patterns_SlidingWindow.mid"
        output_file_path = os.path.join(output_dir, output_filename)

        # Save patterns to MIDI file
        save_patterns_to_midi(original_midi, notes, segments, output_file_path)

        # Print report
        print("Segment Report:")
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

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        import traceback
        traceback.print_exc()
        
# Path to your MIDI file
file_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
main(file_path)
