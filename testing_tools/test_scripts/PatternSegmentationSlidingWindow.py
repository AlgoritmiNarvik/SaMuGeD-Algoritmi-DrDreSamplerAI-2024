import music21
from mido import MidiFile, MidiTrack, Message, MetaMessage

def find_repeating_motifs(score_path, min_length=4, max_length=10):
    score = music21.converter.parse(score_path)
    melody = score.parts[0].flat.notesAndRests
    pitch_sequence = [n.pitch.midi for n in melody if n.isNote]
    
    motifs = {}
    for length in range(min_length, max_length + 1):
        for i in range(len(pitch_sequence) - length + 1):
            motif = tuple(pitch_sequence[i:i+length])
            if motif in motifs:
                motifs[motif].append(i)
            else:
                motifs[motif] = [i]
    
    repeating_motifs = {m: pos for m, pos in motifs.items() if len(pos) > 4}
    return repeating_motifs

def extract_note_info(midi_file):
    note_info = []
    current_time = 0
    for msg in midi_file.tracks[0]:
        current_time += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            note_info.append({'note': msg.note, 'start': current_time, 'velocity': msg.velocity})
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            for note in reversed(note_info):
                if note['note'] == msg.note and 'end' not in note:
                    note['end'] = current_time
                    break
    return note_info

def save_motifs_to_midi(original_midi_path, repeating_motifs, output_path):
    original_midi = MidiFile(original_midi_path)
    note_info = extract_note_info(original_midi)
    
    new_midi = MidiFile(type=original_midi.type, ticks_per_beat=original_midi.ticks_per_beat)
    
    # Copy all original tracks
    for track in original_midi.tracks:
        new_midi.tracks.append(track)
    
    for motif, positions in repeating_motifs.items():
        motif_track = MidiTrack()
        new_midi.tracks.append(motif_track)
        motif_track.append(MetaMessage('track_name', name=f'Motif {motif}'))
        
        for pos in positions:
            if pos + len(motif) > len(note_info):
                continue  # Skip if the motif goes beyond the available notes
            
            motif_start = note_info[pos]['start']
            for i, pitch in enumerate(motif):
                note = note_info[pos + i]
                start_time = note['start'] - motif_start
                duration = note['end'] - note['start']
                
                motif_track.append(Message('note_on', note=note['note'], velocity=note['velocity'], time=int(start_time)))
                motif_track.append(Message('note_off', note=note['note'], velocity=0, time=int(duration)))
    
    new_midi.save(output_path)

# Usage
score_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
output_path = 'testing_tools/test_scripts/pattern_output/track1_with_motifs.mid'

repeating_motifs = find_repeating_motifs(score_path)

for motif, positions in repeating_motifs.items():
    print(f"Motif {motif} repeats at positions: {positions}")

save_motifs_to_midi(score_path, repeating_motifs, output_path)
print(f"MIDI file with motifs saved as {output_path}")
