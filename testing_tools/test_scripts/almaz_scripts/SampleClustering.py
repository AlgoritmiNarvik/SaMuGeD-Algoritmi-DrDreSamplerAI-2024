import os
import numpy as np
import pretty_midi
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

def extract_features_from_midi_with_pretty_midi(file_path):
    try:
        midi = pretty_midi.PrettyMIDI(file_path)
    except Exception as e:
        print(f"Error loading {file_path} with PrettyMIDI: {e}")
        return []

    features = []
    for instrument in midi.instruments:
        if instrument.is_drum:
            continue  # Skip drum tracks

        note_pitches = [note.pitch for note in instrument.notes]
        note_durations = [note.end - note.start for note in instrument.notes]
        velocities = [note.velocity for note in instrument.notes]
        start_times = [note.start for note in instrument.notes]

        if note_pitches:
            pitch_range = max(note_pitches) - min(note_pitches)
            upper_half_notes = [p for p in note_pitches if p > (min(note_pitches) + pitch_range / 2)]
            lower_half_notes = [p for p in note_pitches if p <= (min(note_pitches) + pitch_range / 2)]
            chords = sum([1 for i in range(1, len(start_times)) if start_times[i] == start_times[i - 1]])

            features.append({
                'avg_pitch': np.mean(note_pitches),
                'pitch_std': np.std(note_pitches),
                'avg_velocity': np.mean(velocities),
                'velocity_std': np.std(velocities),
                'avg_duration': np.mean(note_durations),
                'duration_std': np.std(note_durations),
                'note_count': len(note_pitches),
                'pitch_range': pitch_range,
                'avg_interval': np.mean(np.diff(start_times)) if len(start_times) > 1 else 0,
                'track_duration': sum(note_durations),
                'chord_frequency': chords / len(note_pitches) if len(note_pitches) > 0 else 0,
                'silence_ratio': 1 - (sum(note_durations) / max(start_times) if len(start_times) > 0 else 1),
                'upper_half_ratio': len(upper_half_notes) / len(note_pitches),
                'lower_half_ratio': len(lower_half_notes) / len(note_pitches),
                'avg_chord_size': chords / len(start_times) if len(start_times) > 0 else 0,
                'chord_time_ratio': chords / len(note_durations) if len(note_durations) > 0 else 0,
                'note_variety': len(set(note_pitches)),
                'tempo': midi.estimate_tempo(),
                'instrument_name': instrument.name  # Store the instrument name for annotation
            })
    
    return features

def load_midi_files_from_folder(folder_path):
    midi_features = []
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.mid') or file_name.endswith('.midi'):
            file_path = os.path.join(folder_path, file_name)
            # Extract data using pretty_midi
            features = extract_features_from_midi_with_pretty_midi(file_path)
            for feature in features:
                feature['file_name'] = file_name
                midi_features.append(feature)
    return midi_features

def cluster_and_visualize(features):
    # Convert list of features to a NumPy array
    feature_vectors = np.array([[
        f['avg_pitch'], f['pitch_std'], f['avg_velocity'], f['velocity_std'],
        f['avg_duration'], f['duration_std'], f['note_count'], f['pitch_range'],
        f['avg_interval'], f['track_duration'], f['chord_frequency'], f['silence_ratio'],
        f['upper_half_ratio'], f['lower_half_ratio'], f['avg_chord_size'],
        f['chord_time_ratio'], f['note_variety'], f['tempo']
    ] for f in features])

    # Check for sufficient data for clustering
    if feature_vectors.shape[0] < 2:
        print("Not enough data for clustering.")
        return

    # Perform clustering
    kmeans = KMeans(n_clusters=5, random_state=0)
    labels = kmeans.fit_predict(feature_vectors)

    # Calculate silhouette score
    silhouette_avg = silhouette_score(feature_vectors, labels)
    print(f'Silhouette Score: {silhouette_avg}')

    # TSNE visualization
    tsne = TSNE(n_components=2, random_state=0, perplexity=min(30, feature_vectors.shape[0] - 1))
    tsne_result = tsne.fit_transform(feature_vectors)

    plt.figure(figsize=(12, 8))
    scatter = plt.scatter(tsne_result[:, 0], tsne_result[:, 1], c=labels, cmap='viridis')
    plt.title('TSNE Visualization of MIDI Clustering')
    plt.xlabel('TSNE 1')
    plt.ylabel('TSNE 2')

    # Add legend for clusters
    legend1 = plt.legend(*scatter.legend_elements(), title="Clusters")
    plt.gca().add_artist(legend1)

    # Annotate points with file names and instrument names
    for i, feature in enumerate(features):
        x, y = tsne_result[i, 0], tsne_result[i, 1]
        plt.annotate(
            f"{feature['file_name']} - {feature['instrument_name']}",
            xy=(x, y),
            xytext=(5, 2),  # Slightly offset text
            textcoords='offset points',
            ha='right',
            va='bottom',
            fontsize=8  # Smaller font size
        )

    plt.show()

# Main function to execute the analysis
def analyze_midi_folder(folder_path):
    features = load_midi_files_from_folder(folder_path)
    cluster_and_visualize(features)

# usage
analyze_midi_folder('testing_tools/test_scripts/midi_songs_test')
