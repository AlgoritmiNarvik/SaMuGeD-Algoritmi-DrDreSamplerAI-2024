import pretty_midi
import numpy as np
import matplotlib.pyplot as plt

def load_midi(midi_file):
    """
    Load a MIDI file and extract note information.

    This function uses the PrettyMIDI library to read a MIDI file and extract the start time, pitch, 
    and duration of each note. The extracted information is stored in a NumPy array.

    Args:
    midi_file (str): Path to the MIDI file.

    Returns:
    np.ndarray: Array containing note start time, pitch, and duration.
    """
    midi_data = pretty_midi.PrettyMIDI(midi_file)
    notes = []

    for instrument in midi_data.instruments:
        for note in instrument.notes:
            duration = note.end - note.start
            notes.append([note.start, note.pitch, duration])

    note_array = np.array(notes)
    return note_array

def calculate_cost_matrix(note_array):
    """
    Calculate the cost matrix for dynamic programming based on note differences.

    This function computes a cost matrix where each entry represents the "cost" of transitioning 
    from one note to another. The cost is calculated using the Euclidean distance in a 
    three-dimensional space defined by the start time, pitch, and duration of the notes.

    Args:
    note_array (np.ndarray): Array of notes with each note represented by [start_time, pitch, duration].

    Returns:
    np.ndarray: Cost matrix where cost[i, j] is the cost of transitioning from note i to note j.
    """
    n = len(note_array)
    cost = np.zeros((n, n))

    for i in range(n):
        for j in range(i + 1, n):
            time_diff = note_array[j, 0] - note_array[i, 0]
            pitch_diff = note_array[j, 1] - note_array[i, 1]
            duration_diff = note_array[j, 2] - note_array[i, 2]
            cost[i, j] = np.sqrt(time_diff**2 + pitch_diff**2 + duration_diff**2)
            cost[j, i] = cost[i, j]

    return cost

def segment_notes(note_array, cost_matrix, max_segments=15):
    """
    Perform dynamic programming to segment notes.

    This function segments the sequence of notes using dynamic programming. The goal is to partition 
    the notes into segments that minimize the total transition cost. The dynamic programming approach 
    finds the optimal segmentation by considering all possible segmentations and choosing the one with 
    the lowest cost.

    Args:
    note_array (np.ndarray): Array of notes.
    cost_matrix (np.ndarray): Cost matrix where cost[i, j] is the cost of transitioning from note i to note j.
    max_segments (int): Maximum number of segments.

    Returns:
    list: Indices of segment boundaries.
    """
    n = len(note_array)
    dp = np.zeros((n, max_segments))
    segmentation = np.zeros(n, dtype=int)

    for k in range(1, max_segments):
        for i in range(1, n):
            min_cost = float('inf')
            best_j = -1

            for j in range(i):
                current_cost = dp[j, k-1] + cost_matrix[j, i]
                if current_cost < min_cost:
                    min_cost = current_cost
                    best_j = j

            dp[i, k] = min_cost
            segmentation[i] = best_j

    segments = []
    i = n - 1
    while i > 0:
        segments.append(i)
        i = segmentation[i]
    segments.reverse()

    return segments

def plot_segments(note_array, segments):
    """
    Plot the piano roll with segments.

    This function creates a visual representation of the segmented notes. Each segment is 
    displayed in a different color on the piano roll, which shows the pitch of the notes over time.

    Args:
    note_array (np.ndarray): Array of notes.
    segments (list): Indices of segment boundaries.
    """
    plt.figure(figsize=(15, 7))
    colors = plt.cm.tab20(np.linspace(0, 1, len(segments) + 1))

    start_idx = 0
    for i, end_idx in enumerate(segments):
        segment_notes = note_array[start_idx:end_idx + 1]
        color = colors[i % len(colors)]

        for note in segment_notes:
            start_time = note[0]
            pitch = note[1]
            duration = note[2]
            plt.barh(pitch, duration, left=start_time, color=color, edgecolor='black', height=0.5)

        start_idx = end_idx + 1

    plt.xlabel('Time (s)')
    plt.ylabel('Pitch')
    plt.title('Piano Roll with Segments')
    plt.show()

def main():
    """
    Main function to execute the MIDI note segmentation and plotting.

    This function orchestrates the entire process of loading the MIDI file, calculating the cost matrix, 
    segmenting the notes using dynamic programming, and plotting the results.
    """
    midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
    note_array = load_midi(midi_file)
    print(f"Loaded {len(note_array)} notes from the MIDI file.")

    cost_matrix = calculate_cost_matrix(note_array)
    print(f"Calculated cost matrix: \n{cost_matrix}")

    segments = segment_notes(note_array, cost_matrix, max_segments=5)
    print(f"Segments: {segments}")

    plot_segments(note_array, segments)

if __name__ == "__main__":
    main()
