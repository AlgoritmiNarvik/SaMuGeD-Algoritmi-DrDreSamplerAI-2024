import os
import numpy as np
import pretty_midi
import pandas as pd
from scipy.stats import skew, kurtosis, entropy
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import pickle
import logging
from collections import Counter

# logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_features_from_midi(file_path):
    try:
        midi = pretty_midi.PrettyMIDI(file_path)
    except Exception as e:
        logging.error(f"Error loading {file_path} with PrettyMIDI: {e}")
        return None

    features = []
    for instrument_index, instrument in enumerate(midi.instruments):
        if instrument.is_drum:
            continue  # Skip drum tracks

        note_pitches = [note.pitch for note in instrument.notes]
        note_durations = [note.end - note.start for note in instrument.notes]
        velocities = [note.velocity for note in instrument.notes]
        start_times = [note.start for note in instrument.notes]

        if note_pitches:
            pitch_range = max(note_pitches) - min(note_pitches)
            chords = sum([1 for i in range(1, len(start_times)) if start_times[i] == start_times[i - 1]])
            upper_half_notes = [p for p in note_pitches if p > (min(note_pitches) + pitch_range / 2)]
            lower_half_notes = [p for p in note_pitches if p <= (min(note_pitches) + pitch_range / 2)]
            pitch_probs = np.array([note_pitches.count(p) / len(note_pitches) for p in set(note_pitches)])
            pitch_entropy = entropy(pitch_probs)

            feature_dict = {
                'avg_pitch': np.mean(note_pitches),
                'pitch_std': np.std(note_pitches),
                'median_pitch': np.median(note_pitches),
                'avg_velocity': np.mean(velocities),
                'velocity_std': np.std(velocities),
                'avg_duration': np.mean(note_durations),
                'duration_std': np.std(note_durations),
                'median_duration': np.median(note_durations),
                'note_count': len(note_pitches),
                'pitch_range': pitch_range,
                'track_duration': sum(note_durations),
                'chord_frequency': chords / len(note_pitches) if len(note_pitches) > 0 else 0,
                'tempo': midi.estimate_tempo(),
                'avg_interval': np.mean(np.diff(start_times)) if len(start_times) > 1 else 0,
                'silence_ratio': 1 - (sum(note_durations) / max(start_times) if len(start_times) > 0 else 1),
                'upper_half_ratio': len(upper_half_notes) / len(note_pitches),
                'lower_half_ratio': len(lower_half_notes) / len(note_pitches),
                'avg_chord_size': chords / len(start_times) if len(start_times) > 0 else 0,
                'chord_time_ratio': chords / len(note_durations) if len(note_durations) > 0 else 0,
                'note_variety': len(set(note_pitches)),
                'note_density': len(note_pitches) / max(start_times) if len(start_times) > 0 else 0,
                'duration_skewness': skew(note_durations),
                'duration_kurtosis': kurtosis(note_durations),
                'duration_min': np.min(note_durations),
                'duration_max': np.max(note_durations),
                'duration_range': np.max(note_durations) - np.min(note_durations),
                'duration_iqr': np.percentile(note_durations, 75) - np.percentile(note_durations, 25),
                'short_long_ratio': len([d for d in note_durations if d < np.median(note_durations)]) / len([d for d in note_durations if d >= np.median(note_durations)]),
                'pitch_entropy': pitch_entropy,
                'instrument_name': instrument.name,  # for reporting, not clustering
                'file_name': os.path.basename(file_path)  # for reporting, not clustering
            }
            features.append(feature_dict)
    
    return features if features else None

def load_midi_files(folder_path):
    midi_features = []
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.mid') or file_name.endswith('.midi'):
            file_path = os.path.join(folder_path, file_name)
            features = extract_features_from_midi(file_path)
            if features:
                midi_features.extend(features)
            else:
                logging.warning(f"No valid features extracted from {file_name}.")
    return midi_features

def determine_optimal_clusters(feature_vectors, max_clusters=10):
    silhouette_scores = []
    inertia_values = []
    for n_clusters in range(2, max_clusters + 1):
        kmeans = KMeans(n_clusters=n_clusters, random_state=0)
        labels = kmeans.fit_predict(feature_vectors)
        silhouette_avg = silhouette_score(feature_vectors, labels)
        silhouette_scores.append((n_clusters, silhouette_avg))
        inertia_values.append(kmeans.inertia_)

    optimal_n_clusters = max(silhouette_scores, key=lambda x: x[1])[0]
    logging.info(f'Optimal number of clusters determined: {optimal_n_clusters}')
    
    plt.figure(figsize=(12, 6))
    plt.subplot(1, 2, 1)
    plt.plot(range(2, max_clusters + 1), [score[1] for score in silhouette_scores], 'bo-', label='Silhouette Score')
    plt.xlabel('Number of clusters')
    plt.ylabel('Silhouette Score')
    plt.title('Silhouette Score vs. Number of Clusters')
    plt.grid(True)

    plt.subplot(1, 2, 2)
    plt.plot(range(2, max_clusters + 1), inertia_values, 'bo-', label='Inertia')
    plt.xlabel('Number of clusters')
    plt.ylabel('Inertia')
    plt.title('Elbow Method for Optimal Clusters')
    plt.grid(True)

    plt.tight_layout()
    plt.show()
    
    return optimal_n_clusters

def cluster_and_visualize(features, max_clusters=10):
    # Use the specific features for clustering (excluding file_name)
    feature_vectors = np.array([[
        f['avg_pitch'], f['pitch_std'], f['median_pitch'], f['avg_velocity'], f['velocity_std'],
        f['avg_duration'], f['duration_std'], f['median_duration'], f['note_count'], f['pitch_range'],
        f['track_duration'], f['chord_frequency'], f['tempo'], f['avg_interval'], f['silence_ratio'],
        f['upper_half_ratio'], f['lower_half_ratio'], f['avg_chord_size'], f['chord_time_ratio'],
        f['note_variety'], f['note_density'], f['duration_skewness'], f['duration_kurtosis'],
        f['duration_min'], f['duration_max'], f['duration_range'], f['duration_iqr'], f['short_long_ratio'],
        f['pitch_entropy']
    ] for f in features])

    if feature_vectors.shape[0] < 2:
        logging.error("Not enough data for clustering.")
        return None, None

    optimal_n_clusters = determine_optimal_clusters(feature_vectors, max_clusters)

    if optimal_n_clusters < 5:
        logging.info("Forcing a higher number of clusters due to large dataset variability.")
        optimal_n_clusters = min(5, feature_vectors.shape[0] - 1)

    kmeans = KMeans(n_clusters=optimal_n_clusters, random_state=0)
    labels = kmeans.fit_predict(feature_vectors)

    with open('testing_tools/test_scripts/almaz_scripts/Clustering/kmeans_model.pkl', 'wb') as model_file:
        pickle.dump(kmeans, model_file)

    # PCA for dimensionality reduction
    pca = PCA(n_components=2)
    pca_result = pca.fit_transform(feature_vectors)

    # Seaborn Pair Plot for feature relationships
    df = pd.DataFrame(feature_vectors, columns=[
        'avg_pitch', 'pitch_std', 'median_pitch', 'avg_velocity', 'velocity_std',
        'avg_duration', 'duration_std', 'median_duration', 'note_count', 'pitch_range',
        'track_duration', 'chord_frequency', 'tempo', 'avg_interval', 'silence_ratio',
        'upper_half_ratio', 'lower_half_ratio', 'avg_chord_size', 'chord_time_ratio',
        'note_variety', 'note_density', 'duration_skewness', 'duration_kurtosis',
        'duration_min', 'duration_max', 'duration_range', 'duration_iqr', 'short_long_ratio',
        'pitch_entropy'
    ])
    df['Cluster'] = labels

    # Selected features for a more manageable pair plot
    selected_features = [
        'avg_pitch', 'pitch_std', 'avg_velocity', 'velocity_std',
        'avg_duration', 'duration_std', 'note_count', 'pitch_range',
        'track_duration', 'tempo', 'pitch_entropy'
    ]

    sns.pairplot(df[selected_features + ['Cluster']], hue='Cluster', palette='viridis', height=1.0)
    plt.suptitle("Pairplot of Selected MIDI Features by Cluster", y=1.02)
    plt.show()

    # Plotting the clusters in PCA-reduced space using Plotly
    df_pca = pd.DataFrame(pca_result, columns=['PCA1', 'PCA2'])
    df_pca['Cluster'] = labels
    df_pca['instrument_name'] = [f['instrument_name'] for f in features]
    df_pca['file_name'] = [f['file_name'] for f in features]

    fig = px.scatter(df_pca, x='PCA1', y='PCA2', color='Cluster', 
                     hover_data=['instrument_name', 'file_name'])
    fig.update_traces(marker=dict(size=8, line=dict(width=1, color='DarkSlateGrey')), selector=dict(mode='markers'))
    fig.update_layout(title='MIDI Tracks Clustering Visualization (PCA)', title_x=0.5)
    fig.show()

    return kmeans, feature_vectors

def generate_report(features, labels, n_clusters, explained_variance, kmeans, feature_vectors, output_file='testing_tools/test_scripts/almaz_scripts/Clustering/clustering_report.txt'):
    with open(output_file, 'w') as report_file:
        report_file.write("----- Clustering Report -----\n")
        report_file.write(f"Number of Clusters: {n_clusters}\n")
        report_file.write("Explained Variance by PCA Components:\n")
        report_file.write(f"  PCA 1: {explained_variance[0] * 100:.2f}%\n")
        report_file.write(f"  PCA 2: {explained_variance[1] * 100:.2f}%\n\n")

        for cluster_id in range(n_clusters):
            report_file.write(f"  Cluster {cluster_id + 1}:\n")
            logging.info(f"  Cluster {cluster_id + 1}:")
            cluster_items = [features[idx] for idx in range(len(labels)) if labels[idx] == cluster_id]
            for idx, item in enumerate(cluster_items):
                track_info = f"    - {item['file_name']} (Instrument: {item['instrument_name']})"
                report_file.write(track_info + "\n")
                logging.info(track_info)
        
        report_file.write("\n----- List of All Analyzed Tracks with Their Clusters -----\n")
        for idx, feature in enumerate(features):
            track_info = f"{feature['file_name']} (Track: {feature['instrument_name']}), Cluster: {labels[idx] + 1}"
            report_file.write(track_info + "\n")
            logging.info(track_info)
        
        report_file.write("----- End of Report -----\n")
        logging.info("----- End of Report -----")

    # Save the cluster assignments separately if needed
    # save_cluster_assignments(features, labels, 'testing_tools/test_scripts/almaz_scripts/Clustering/track_cluster_assignments.csv')

def save_cluster_assignments(features, labels, output_file):
    assignments = [{'instrument_name': f['instrument_name'], 'cluster': labels[i]} for i, f in enumerate(features)]
    df = pd.DataFrame(assignments)
    df.to_csv(output_file, index=False)
    logging.info(f"Track-cluster assignments saved to {output_file}")

def predict_cluster_for_new_midi(file_path, kmeans_model_path='testing_tools/test_scripts/almaz_scripts/Clustering/kmeans_model.pkl'):
    # load the k-means model
    with open(kmeans_model_path, 'rb') as model_file:
        kmeans = pickle.load(model_file)

    track_features = extract_features_from_midi(file_path)

    if not track_features:
        logging.error(f"No valid features extracted from {file_path}.")
        return

    for idx, feature in enumerate(track_features):
        feature_vector = np.array([[
            feature['avg_pitch'], feature['pitch_std'], feature['median_pitch'], feature['avg_velocity'], feature['velocity_std'],
            feature['avg_duration'], feature['duration_std'], feature['median_duration'], feature['note_count'], feature['pitch_range'],
            feature['track_duration'], feature['chord_frequency'], feature['tempo'], feature['avg_interval'], feature['silence_ratio'],
            feature['upper_half_ratio'], feature['lower_half_ratio'], feature['avg_chord_size'], feature['chord_time_ratio'],
            feature['note_variety'], feature['note_density'], feature['duration_skewness'], feature['duration_kurtosis'],
            feature['duration_min'], feature['duration_max'], feature['duration_range'], feature['duration_iqr'], feature['short_long_ratio'],
            feature['pitch_entropy']
        ]])

        # Predict the cluster
        cluster = kmeans.predict(feature_vector)[0]
        logging.info(f"The track '{feature['instrument_name']}' in MIDI file '{file_path}' belongs to cluster {cluster + 1}.")
        print(f"The track '{feature['instrument_name']}' in MIDI file '{file_path}' belongs to cluster {cluster + 1}.")

def analyze_midi_folder(folder_path):
    features = load_midi_files(folder_path)
    if not features:
        logging.error(f"No valid features extracted from folder {folder_path}")
        return

    kmeans, feature_vectors = cluster_and_visualize(features, max_clusters=10)
    if kmeans and feature_vectors is not None:
        generate_report(features, kmeans.labels_, kmeans.n_clusters, PCA(n_components=2).fit(feature_vectors).explained_variance_ratio_, kmeans, feature_vectors)

# usage
if __name__ == "__main__":
    analyze_midi_folder('testing_tools/test_scripts/almaz_scripts/Clustering/midi_files/not_actual_dataset')
    predict_cluster_for_new_midi('testing_tools/test_scripts/almaz_scripts/Clustering/midi_files/random_midi/Riders_on_the_Storm.4.mid')
