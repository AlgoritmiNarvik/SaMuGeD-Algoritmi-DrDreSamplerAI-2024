import pretty_midi
import numpy as np
import matplotlib.pyplot as plt
from dtaidistance import dtw
from sklearn.cluster import DBSCAN
from matplotlib.patches import Rectangle

# Шаг 1: Загрузка и чтение MIDI-файла
midi_data = pretty_midi.PrettyMIDI('testing_tools/test_scripts/take_on_me/track1.mid')

# Извлечение нот из первого инструмента
instrument = midi_data.instruments[0]
notes = instrument.notes

# Шаг 2: Преобразование нот в массив
note_sequences = [(note.start, note.end, note.pitch) for note in notes]
note_array = np.array([[note.start, note.end, note.pitch] for note in notes])

print("Шаг 2: Преобразование нот в массив завершено.")
print(f"Всего нот: {len(note_array)}")
print(f"note_array:\n{note_array}")

# Шаг 3: Найти последовательности нот с использованием DBSCAN
def find_sequences(note_array, eps=1.0, min_samples=2):
    dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='euclidean')
    clusters = dbscan.fit_predict(note_array[:, [0]])  # Используем только время начала нот
    return clusters

clusters = find_sequences(note_array)
print("Шаг 3: Кластеризация завершена.")
print(f"Уникальные кластеры: {np.unique(clusters)}")

# Шаг 4: Поиск повторяющихся последовательностей с использованием DTW
def find_repeated_sequences(note_array, clusters, threshold=0.8):
    repeated_sequences = []
    unique_clusters = np.unique(clusters)
    for i, cluster in enumerate(unique_clusters):
        if cluster == -1:
            continue
        cluster_notes = note_array[clusters == cluster]
        for j, other_cluster in enumerate(unique_clusters):
            if i >= j or other_cluster == -1:
                continue
            other_cluster_notes = note_array[clusters == other_cluster]
            distance = dtw.distance(cluster_notes[:, 2], other_cluster_notes[:, 2])
            similarity = 1 - (distance / max(len(cluster_notes), len(other_cluster_notes)))
            if similarity >= threshold:
                repeated_sequences.append((cluster_notes, other_cluster_notes))
    return repeated_sequences

repeated_sequences = find_repeated_sequences(note_array, clusters)
print("Шаг 4: Поиск повторяющихся последовательностей завершен.")
print(f"Найдено повторяющихся последовательностей: {len(repeated_sequences)}")
for seq_pair in repeated_sequences:
    print(f"Sequence 1:\n{seq_pair[0]}")
    print(f"Sequence 2:\n{seq_pair[1]}")

# Шаг 5: Визуализация сегментов с использованием прямоугольников
plt.figure(figsize=(14, 6))
ax = plt.gca()
unique_clusters = np.unique(clusters)
colors = plt.cm.tab20(np.linspace(0, 1, len(unique_clusters)))

for i, cluster_label in enumerate(unique_clusters):
    if cluster_label == -1:
        continue
    color = colors[i % len(colors)]
    cluster_notes = note_array[clusters == cluster_label]
    for note in cluster_notes:
        rect = Rectangle((note[0], note[2] - 0.5), note[1] - note[0], 1, color=color)
        ax.add_patch(rect)

# Визуализация повторяющихся последовательностей
for i, (seq1, seq2) in enumerate(repeated_sequences):
    color = colors[(i + len(unique_clusters)) % len(colors)]
    for note in seq1:
        rect = Rectangle((note[0], note[2] - 0.5), note[1] - note[0], 1, color=color, alpha=0.6)
        ax.add_patch(rect)
    for note in seq2:
        rect = Rectangle((note[0], note[2] - 0.5), note[1] - note[0], 1, color=color, alpha=0.6)
        ax.add_patch(rect)

plt.xlim(0, max(note_array[:, 1]) + 10)
plt.ylim(min(note_array[:, 2]) - 1, max(note_array[:, 2]) + 1)
plt.xlabel('Time (s)')
plt.ylabel('Pitch')
plt.title('Segmentation of MIDI Notes into Repeated Melodic Phrases')
plt.show()
