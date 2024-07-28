import pretty_midi
import numpy as np
from hmmlearn import hmm
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

# Function to normalize data
def normalize_data(data):
    mean = np.mean(data, axis=0)
    std = np.std(data, axis=0)
    return (data - mean) / std

# Function to fit HMM and predict states
def fit_hmm(note_array, n_states=2):
    normalized_notes = normalize_data(note_array)
    model = hmm.GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=1000, init_params="cmw")
    
    # Initialize startprob and transmat to avoid NaN issues
    model.startprob_ = np.full(n_states, 1/n_states)
    model.transmat_ = np.full((n_states, n_states), 1/n_states)
    
    # Fit model
    model.fit(normalized_notes)
    hidden_states = model.predict(normalized_notes)
    return hidden_states

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

# Fit HMM to the note data
try:
    hidden_states = fit_hmm(note_array, n_states=2)
    print(f"Hidden states: {hidden_states}")
    print(f"Found {len(np.unique(hidden_states))} unique states.")
    
    # Plotting the results
    plot_segments(note_array, hidden_states)
except ValueError as e:
    print(f"An error occurred while fitting the HMM: {e}")
