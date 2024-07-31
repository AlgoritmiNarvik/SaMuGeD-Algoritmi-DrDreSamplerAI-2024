from music21 import converter, note, chord
import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

def read_midi_file(file_path):
    score = converter.parse(file_path)
    melody = score.parts[0].flat.notesAndRests
    ticks_per_quarter = score.metronomeMarkBoundaries()[0][-1].secondsPerQuarter() * 480
    pitch_sequence = []

    for n in melody:
        if isinstance(n, note.Note):
            pitch_sequence.append((n.pitch.midi, int(n.offset * ticks_per_quarter), int((n.offset + n.quarterLength) * ticks_per_quarter)))
        elif isinstance(n, chord.Chord):
            for pitch in n.pitches:
                pitch_sequence.append((pitch.midi, int(n.offset * ticks_per_quarter), int((n.offset + n.quarterLength) * ticks_per_quarter)))
                
    return pitch_sequence

def find_repeating_patterns(pitch_sequence, min_length=4, max_length=16):
    patterns = defaultdict(list)
    pitches_only = [pitch for pitch, _, _ in pitch_sequence]
    
    for length in range(min_length, max_length + 1):
        for i in range(len(pitches_only) - length + 1):
            pattern = tuple(pitches_only[i:i+length])
            patterns[pattern].append(i)
    
    return {p: v for p, v in patterns.items() if len(v) > 1}

def segment_track(pitch_sequence, repeating_patterns, max_silence_ticks=1000):
    segments = []
    used_indices = set()
    
    sorted_patterns = sorted(repeating_patterns.items(), key=lambda x: (len(x[0]), len(x[1])), reverse=True)
    
    for pattern, positions in sorted_patterns:
        for pos in positions:
            if all(i not in used_indices for i in range(pos, pos + len(pattern))):
                start_tick = pitch_sequence[pos][1]
                end_tick = pitch_sequence[pos + len(pattern) - 1][2]
                
                is_valid_segment = True
                for i in range(pos, pos + len(pattern) - 1):
                    if pitch_sequence[i + 1][1] - pitch_sequence[i][2] > max_silence_ticks:
                        is_valid_segment = False
                        break
                
                if is_valid_segment:
                    segments.append((start_tick, end_tick, len(positions), pattern))
                    used_indices.update(range(pos, pos + len(pattern)))
    
    return sorted(segments)

def plot_piano_roll_with_segments(pitch_sequence, segments):
    fig, ax = plt.subplots(figsize=(20, 10))
    
    for pitch, start, end in pitch_sequence:
        rect = Rectangle((start, pitch - 0.4), end - start, 0.8, color='gray', alpha=0.6)
        ax.add_patch(rect)
    
    colors = plt.cm.rainbow(np.linspace(0, 1, len(segments)))
    for i, (start, end, count, pattern) in enumerate(segments):
        color = colors[i]
        ax.add_patch(Rectangle((start, min(pattern) - 0.5), end - start, max(pattern) - min(pattern) + 1, color=color, alpha=0.3))
        ax.text((start + end) / 2, max(pattern) + 1, f'Pattern {i+1}\nRep: {count}', ha='center', va='bottom', fontsize=8, color=color)
    
    ax.set_xlim(0, pitch_sequence[-1][2])
    ax.set_ylim(min(pitch for pitch, _, _ in pitch_sequence) - 1, max(pitch for pitch, _, _ in pitch_sequence) + 2)
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch (MIDI)')
    ax.grid(True, linestyle='--', alpha=0.5)
    
    plt.title('Piano Roll with Segmented Earworms')
    plt.tight_layout()
    plt.show()

def generate_report(segments):
    report = "Earworm Report:\n"
    for i, (start, end, count, pattern) in enumerate(segments):
        report += f"Earworm {i + 1}:\n"
        report += f"  Pattern: {pattern}\n"
        report += f"  Start: {start} ticks\n"
        report += f"  End: {end} ticks\n"
        report += f"  Length: {end - start} ticks\n"
        report += f"  Repetitions: {count}\n"
        report += "-" * 20 + "\n"
    return report

def extract_earworms(midi_file, top_n=500):
    pitch_sequence = read_midi_file(midi_file)
    repeating_patterns = find_repeating_patterns(pitch_sequence)
    segments = segment_track(pitch_sequence, repeating_patterns)
    top_segments = sorted(segments, key=lambda x: x[2] * len(x[3]), reverse=True)[:top_n]
    return pitch_sequence, top_segments

# Example usage
if __name__ == "__main__":
    midi_file = "testing_tools/Manual_seg/take_on_me/track1.mid"
    pitch_sequence, top_earworms = extract_earworms(midi_file)
    
    if top_earworms:
        print("Top potential earworms:")
        for i, (start, end, count, pattern) in enumerate(top_earworms, 1):
            print(f"{i}. Pattern: {pattern}, Repetitions: {count}")
        
        plot_piano_roll_with_segments(pitch_sequence, top_earworms)
        
        report = generate_report(top_earworms)
        print(report)
    else:
        print("No earworms found or an error occurred.")
        