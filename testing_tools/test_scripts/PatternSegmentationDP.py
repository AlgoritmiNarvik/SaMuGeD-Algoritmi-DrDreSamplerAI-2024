import pretty_midi
import numpy as np
import matplotlib.pyplot as plt

# Function to load MIDI file and extract note information
def load_midi(midi_file):
    midi_data = pretty_midi.PrettyMIDI(midi_file)
    notes = []

    for instrument in midi_data.instruments:
        for note in instrument.notes:
            duration = note.end - note.start
            notes.append([note.start, note.pitch, duration])

    note_array = np.array(notes)
    return note_array

# Function to calculate cost matrix for dynamic programming
def calculate_cost_matrix(note_array):
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

# Function to perform dynamic programming for segmentation
def segment_notes(note_array, cost_matrix, max_segments=15):
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

# Function to plot the piano roll with segments
def plot_segments(note_array, segments):
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

# Main script execution
midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
note_array = load_midi(midi_file)
print(f"Loaded {len(note_array)} notes from the MIDI file.")

# Calculate cost matrix
cost_matrix = calculate_cost_matrix(note_array)
print(f"Calculated cost matrix: \n{cost_matrix}")

# Perform dynamic programming for segmentation
segments = segment_notes(note_array, cost_matrix, max_segments=5)
print(f"Segments: {segments}")

# Plotting the results
plot_segments(note_array, segments)
