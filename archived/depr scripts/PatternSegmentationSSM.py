import mido
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

def extract_notes(midi_file):
    mid = mido.MidiFile(midi_file)
    notes = []
    current_time = 0
    
    for track in mid.tracks:
        for msg in track:
            current_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                notes.append((msg.note, current_time, 0, msg.velocity))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                for i in reversed(range(len(notes))):
                    if notes[i][0] == msg.note and notes[i][2] == 0:
                        notes[i] = (notes[i][0], notes[i][1], current_time - notes[i][1], notes[i][3])
                        break
    
    return sorted(notes, key=lambda x: x[1])

def find_patterns(notes, min_length=3, max_length=20):
    patterns = defaultdict(list)
    
    for i in range(len(notes) - min_length + 1):
        for j in range(min_length, min(max_length, len(notes) - i) + 1):
            pattern = tuple(round(note[0] / 12) for note in notes[i:i+j])  # Use octave-invariant pitch classes
            patterns[pattern].append(i)
    
    return {k: v for k, v in patterns.items() if len(v) > 1}

def rank_patterns(patterns):
    return sorted(patterns.items(), key=lambda x: (len(x[1]), len(x[0])), reverse=True)

def patterns_to_segments(notes, patterns, min_gap=1.0, min_duration=2.0):
    segments = []
    sorted_patterns = sorted(patterns.items(), key=lambda x: (len(x[1]), len(x[0])), reverse=True)
    covered_indices = set()

    for pattern, occurrences in sorted_patterns:
        for start_index in occurrences:
            if start_index not in covered_indices:
                end_index = start_index + len(pattern) - 1
                if end_index not in covered_indices:
                    start_time = notes[start_index][1]
                    end_time = notes[end_index][1] + notes[end_index][2]
                    
                    if end_time - start_time >= min_duration:
                        # Merge with previous segment if gap is small
                        if segments and start_time - segments[-1][1] <= min_gap:
                            segments[-1] = (segments[-1][0], max(segments[-1][1], end_time))
                        else:
                            segments.append((start_time, end_time))
                        
                        covered_indices.update(range(start_index, end_index + 1))

    return sorted(segments)

def plot_simple_piano_roll_with_segments(notes, segments):
    plt.figure(figsize=(20, 10))
    
    # Plot notes
    for note in notes:
        start_time, pitch, duration, velocity = note
        plt.plot([start_time, start_time + duration], [pitch, pitch], color='blue', linewidth=1, alpha=0.5)
    
    # Plot segment boundaries
    for i, (start, end) in enumerate(segments):
        plt.axvline(x=start, color='red', linestyle='--', alpha=0.5)
        plt.axvline(x=end, color='red', linestyle='--', alpha=0.5)
        plt.text(start, plt.ylim()[1], f'{i+1}', horizontalalignment='left', verticalalignment='top')
    
    plt.ylabel('Pitch')
    plt.xlabel('Time (ms)')
    plt.title('Piano Roll with Segment Boundaries')
    
    plt.tight_layout()
    plt.show()

def main(midi_file):
    notes = extract_notes(midi_file)
    patterns = find_patterns(notes)
    ranked_patterns = rank_patterns(patterns)
    segments = patterns_to_segments(notes, dict(ranked_patterns))
    
    print(f"Found {len(segments)} segments:")
    for i, (start, end) in enumerate(segments, 1):
        duration = end - start
        print(f"{i}. Segment from {start:.2f} to {end:.2f} (duration: {duration:.2f})")
    
    plot_simple_piano_roll_with_segments(notes, segments)

if __name__ == "__main__":
    midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
    main(midi_file)
    