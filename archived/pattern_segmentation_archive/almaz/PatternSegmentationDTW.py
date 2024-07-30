import pretty_midi
import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from sklearn.cluster import AgglomerativeClustering
import matplotlib.pyplot as plt

# Function to load MIDI file and extract note information
def load_midi(midi_file):
    midi_data = pretty_midi.PrettyMIDI(midi_file)
    notes = []

    for instrument in midi_data.instruments:
        for note in instrument.notes:
            notes.append([note.start, note.end, note.pitch])

    note_array = np.array(notes)
    return note_array

# Function to calculate DTW distances between sequences of notes considering both time and pitch
def calculate_dtw_distances(note_array):
    n = len(note_array)
    distances = np.zeros((n, n))

    for i in range(n):
        for j in range(i + 1, n):
            distance, _ = fastdtw(note_array[i].reshape(-1, 3), note_array[j].reshape(-1, 3), dist=euclidean)
            distances[i, j] = distance
            distances[j, i] = distance

    return distances

# Function to plot the piano roll with segments
def plot_segments(note_array, clusters):
    plt.figure(figsize=(15, 8))
    plt.title('Piano Roll with Segments')

    unique_clusters = np.unique(clusters)
    colors = plt.cm.tab20(np.linspace(0, 1, len(unique_clusters)))

    for cluster, color in zip(unique_clusters, colors):
        cluster_notes = note_array[clusters == cluster]
        for note in cluster_notes:
            start, end, pitch = note
            plt.plot([start, end], [pitch, pitch], color=color, linewidth=6)

    plt.xlabel('Time (s)')
    plt.ylabel('Pitch')
    plt.show()

# Main script execution
midi_file = 'testing_tools/Manual_seg/take_on_me/track1.mid'
note_array = load_midi(midi_file)
print(f"Loaded {len(note_array)} notes from the MIDI file.")

# Clustering notes based on time intervals
distances = calculate_dtw_distances(note_array)  # Use time and pitch for distance calculation
print(f"Calculated distance matrix: \n{distances}")

clustering = AgglomerativeClustering(n_clusters=None, distance_threshold=10, metric='precomputed', linkage='complete')
clusters = clustering.fit_predict(distances)
print(f"Clusters: {clusters}")
print(f"Found {len(np.unique(clusters))} unique clusters.")

# Plotting the results
plot_segments(note_array, clusters)
