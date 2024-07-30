"""
MIDI Segmentation Algorithm

This script implements a novel approach to MIDI file segmentation using a combination of
color-based grouping and pause detection. The algorithm works as follows:

1. Load MIDI file and extract note information.
2. Assign colors to notes based on their position in the sequence.
3. Group notes into segments based on color changes and long pauses.
4. Visualize the resulting segmentation.

The main idea behind this approach is to leverage the "incorrect" color assignment
that occurs when visualizing MIDI data, which surprisingly results in meaningful
segmentation. This method doesn't use traditional dynamic programming for segmentation,
but rather exploits the visual patterns that emerge from simple color assignment.

The algorithm is particularly useful for identifying repeated patterns and structural
changes in MIDI compositions, which can be helpful for music analysis, automatic
summarization, or creating loop-based samples.
"""

import pretty_midi
import numpy as np
import matplotlib.pyplot as plt

def load_midi(midi_file):
    """
    Load a MIDI file and extract note information along with tempo and time signature.

    Args:
        midi_file (str): Path to the MIDI file.

    Returns:
        tuple: A tuple containing:
            - note_array (np.array): Array of notes, each represented by [start_time, pitch, duration].
            - tempo (tuple): Tempo changes in the MIDI file.
            - time_signature (list): Time signature changes in the MIDI file.
    """
    midi_data = pretty_midi.PrettyMIDI(midi_file)
    notes = []

    for instrument in midi_data.instruments:
        for note in instrument.notes:
            duration = note.end - note.start
            notes.append([note.start, note.pitch, duration])

    note_array = np.array(notes)
    
    # Get tempo and time signature information
    tempo = midi_data.get_tempo_changes()
    time_signature = midi_data.time_signature_changes

    return note_array, tempo, time_signature

def calculate_bar_duration(tempo, time_signature):
    """
    Calculate the duration of one bar based on tempo and time signature.

    This function is crucial for identifying long pauses in the music, which are
    defined as pauses longer than one bar.

    Args:
        tempo (tuple): Tempo information from the MIDI file.
        time_signature (list): Time signature information from the MIDI file.

    Returns:
        float: Duration of one bar in seconds.
    """

    if len(tempo[0]) == 0 or len(time_signature) == 0:
        return 2.0  # Default to 2 seconds if no tempo or time signature info

    # Use the first tempo and time signature change
    tempo_val = tempo[1][0]
    beats_per_bar = time_signature[0].numerator
    beat_duration = 60 / tempo_val  # Duration of one beat in seconds
    
    return beats_per_bar * beat_duration

def assign_segment_colors(note_array, max_segments=15):
    """
    Assign colors to notes based on their position in the sequence.

    This function is the key to our segmentation approach. Instead of using traditional
    segmentation algorithms, we exploit the visual patterns that emerge when we assign
    colors to notes based on their position. This "incorrect" color assignment
    surprisingly results in meaningful segmentation.

    The function divides the note sequence into a fixed number of segments and assigns
    a unique color to each segment. This creates a repeating color pattern that often
    aligns with the musical structure.

    Args:
        note_array (np.array): Array of notes.
        max_segments (int): Maximum number of color segments to use.

    Returns:
        np.array: Array of colors assigned to each note.
    """
    n = len(note_array)
    colors = plt.cm.tab20(np.linspace(0, 1, max_segments))
    note_colors = np.zeros((n, 4))
    
    segment_size = n // max_segments
    for i in range(max_segments):
        start = i * segment_size
        end = (i + 1) * segment_size if i < max_segments - 1 else n
        note_colors[start:end] = colors[i]
    
    return note_colors

def group_notes_by_color_and_pauses(note_array, note_colors, bar_duration, color_threshold=0.01):
    """
    Group notes into segments based on their colors and pauses longer than one bar.

    This function implements the core logic of our segmentation algorithm. It combines
    two criteria for creating segment boundaries:
    1. Color changes: When the color of a note significantly differs from the previous one.
    2. Long pauses: When there's a pause longer than one bar between notes.

    By using these criteria, we can identify both repetitive patterns (through color changes)
    and structural breaks in the music (through long pauses).

    Args:
        note_array (np.array): Array of notes.
        note_colors (np.array): Array of colors assigned to each note.
        bar_duration (float): Duration of one bar in seconds.
        color_threshold (float): Threshold for detecting color changes.

    Returns:
        list: List of segments, where each segment is a list of note indices.
    """
    segments = []
    current_segment = [0]
    current_color = note_colors[0]

    for i in range(1, len(note_array)):
        color_change = np.sum(np.abs(note_colors[i] - current_color)) > color_threshold
        pause_duration = note_array[i][0] - (note_array[i-1][0] + note_array[i-1][2])
        long_pause = pause_duration > bar_duration

        if color_change or long_pause:
            segments.append(current_segment)
            current_segment = [i]
            current_color = note_colors[i]
        else:
            current_segment.append(i)

    segments.append(current_segment)
    return segments

def plot_segments(note_array, segments):
    """
    Plot the piano roll with segments and gaps between them.

    This function visualizes the segmentation result. It plots each note as a horizontal
    bar, with different colors representing different segments. Vertical dashed lines
    are added to clearly show the boundaries between segments.

    Args:
        note_array (np.array): Array of notes.
        segments (list): List of segments, where each segment is a list of note indices.
    """
    plt.figure(figsize=(20, 10))
    colors = plt.cm.tab20(np.linspace(0, 1, len(segments)))

    for i, segment in enumerate(segments):
        segment_notes = note_array[segment]
        color = colors[i % len(colors)]

        for note in segment_notes:
            start_time, pitch, duration = note
            plt.barh(pitch, duration, left=start_time, color=color, edgecolor='black', height=0.5)
        
        # Add vertical line to show segment boundary
        if i < len(segments) - 1:
            boundary = note_array[segments[i+1][0]][0]  # Start time of the first note in the next segment
            plt.axvline(x=boundary, color='red', linestyle='--', alpha=0.5)

    plt.xlabel('Time (s)')
    plt.ylabel('Pitch')
    plt.title('Piano Roll with Segments and Gaps')
    
    # Add legend for segment boundaries
    plt.plot([], [], color='red', linestyle='--', label='Segment Boundary')
    plt.legend()
    
    plt.show()

def main():
    """
    Main function to execute the MIDI segmentation algorithm.

    This function orchestrates the entire segmentation process:
    1. Load the MIDI file
    2. Calculate the duration of one bar
    3. Assign colors to notes
    4. Group notes into segments based on colors and pauses
    5. Visualize the segmentation result

    The resulting plot provides a visual representation of the MIDI file's structure,
    with different colors indicating different segments and vertical lines showing
    segment boundaries.
    """
    midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
    note_array, tempo, time_signature = load_midi(midi_file)
    print(f"Loaded {len(note_array)} notes from the MIDI file.")

    bar_duration = calculate_bar_duration(tempo, time_signature)
    print(f"Calculated bar duration: {bar_duration:.2f} seconds")

    note_colors = assign_segment_colors(note_array, max_segments=15)
    segments = group_notes_by_color_and_pauses(note_array, note_colors, bar_duration)
    print(f"Grouped notes into {len(segments)} segments.")

    plot_segments(note_array, segments)

if __name__ == "__main__":
    main()
    