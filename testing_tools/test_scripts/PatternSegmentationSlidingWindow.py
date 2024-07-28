from music21 import converter, note
import matplotlib.pyplot as plt
import numpy as np

def read_midi_file(file_path):
    score = converter.parse(file_path)
    melody = score.parts[0].flat.notesAndRests
    pitch_sequence = [n.pitch.midi for n in melody if n.isNote]
    return pitch_sequence

def find_repeating_motifs(pitch_sequence, min_length=4, max_length=20):
    motifs = {}
    for length in range(min_length, max_length + 1):
        for i in range(len(pitch_sequence) - length + 1):
            motif = tuple(pitch_sequence[i:i+length])
            if motif in motifs:
                motifs[motif].append(i)
            else:
                motifs[motif] = [i]
    
    repeating_motifs = {m: pos for m, pos in motifs.items() if len(pos) > 1}
    return repeating_motifs

def segment_track(pitch_sequence, repeating_motifs):
    segments = []
    used_indices = set()
    
    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: (len(x[0]), len(x[1])), reverse=True)
    
    for motif, positions in sorted_motifs:
        for pos in positions:
            if all(i not in used_indices for i in range(pos, pos + len(motif))):
                segments.append((pos, pos + len(motif)))
                used_indices.update(range(pos, pos + len(motif)))
    
    return sorted(segments)

def plot_piano_roll(pitch_sequence, segments):
    max_pitch = max(pitch_sequence)
    min_pitch = min(pitch_sequence)
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    for segment in segments:
        start, end = segment
        ax.add_patch(plt.Rectangle((start, min_pitch - 0.5), end - start, max_pitch - min_pitch + 1, color='lightblue', alpha=0.5))
    
    ax.plot(pitch_sequence, 'k', marker='o', markersize=4, linestyle='None')
    
    ax.set_xlim(0, len(pitch_sequence))
    ax.set_ylim(min_pitch - 1, max_pitch + 1)
    ax.set_xlabel('Time')
    ax.set_ylabel('Pitch')
    
    plt.title('Piano Roll with Segmented Motifs')
    plt.show()

# Используем путь к вашему MIDI-файлу
file_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
pitch_sequence = read_midi_file(file_path)
repeating_motifs = find_repeating_motifs(pitch_sequence)
segments = segment_track(pitch_sequence, repeating_motifs)
plot_piano_roll(pitch_sequence, segments)
