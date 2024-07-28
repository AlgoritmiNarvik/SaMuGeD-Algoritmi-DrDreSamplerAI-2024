import pretty_midi
import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt

# Function to load MIDI file and extract note information
def load_midi(midi_file):
    midi_data = pretty_midi.PrettyMIDI(midi_file)
    notes = []

    for instrument in midi_data.instruments:
        for note in instrument.notes:
            notes.append([note.start, note.pitch, note.end - note.start])

    note_array = np.array(notes)
    return note_array

# Function to calculate DTW distances between sequences of notes
def calculate_dtw_distances(note_array):
    n = len(note_array)
    distances = np.zeros((n, n))

    for i in range(n):
        for j in range(i + 1, n):
            distance, _ = fastdtw(note_array[i].reshape(-1, 1), note_array[j].reshape(-1, 1), dist=euclidean)
            distances[i, j] = distance
            distances[j, i] = distance

    return distances

# Function to plot the piano roll with segments
def plot_segments(note_array, clusters):
    plt.figure(figsize=(15, 7))
    unique_clusters = np.unique(clusters)
    colors = plt.cm.tab20(np.linspace(0, 1, len(unique_clusters)))

    for cluster, color in zip(unique_clusters, colors):
        cluster_notes = note_array[clusters == cluster]
        for note in cluster_notes:
            start_time = note[0]
            pitch = note[1]
            duration = note[2]
            plt.barh(pitch, duration, left=start_time, color=color, edgecolor='black', height=0.5)

    plt.xlabel('Time (s)')
    plt.ylabel('Pitch')
    plt.title('Piano Roll with Segments')
    plt.show()

# Main script execution
midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
note_array = load_midi(midi_file)
print(f"Loaded {len(note_array)} notes from the MIDI file.")

# Clustering notes based on time intervals
distances = calculate_dtw_distances(note_array[:, [0, 1]])  # Use time and pitch for distance calculation
print(f"Calculated distance matrix: \n{distances}")

# Using KMeans for clustering
kmeans = KMeans(n_clusters=85)  # You can adjust the number of clusters as needed
clusters = kmeans.fit_predict(note_array)
print(f"Clusters: {clusters}")
print(f"Found {len(np.unique(clusters))} unique clusters.")

# Plotting the results
plot_segments(note_array, clusters)
