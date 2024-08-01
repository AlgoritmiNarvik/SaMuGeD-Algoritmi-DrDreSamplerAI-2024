import mido
from collections import defaultdict

# Define constants for note names
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def note_name(note_number):
    return NOTE_NAMES[note_number % 12]

def is_chord(notes):
    # Check if the notes form a chord by ensuring there are at least 3 unique notes
    return len(set(notes)) >= 3

def analyze_midi(file_path):
    mid = mido.MidiFile(file_path)
    
    # Variables to hold musical elements
    motifs = defaultdict(int)
    ostinatos = defaultdict(int)
    sequences = defaultdict(int)
    arpeggios = []
    cadences = []
    
    # Load all notes from the MIDI file
    notes = []
    for track in mid.tracks:
        current_notes = set()
        time = 0
        for msg in track:
            time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                current_notes.add(note_name(msg.note))
                notes.append((msg.note, time))  # Add the note to the notes list
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                if note_name(msg.note) in current_notes:
                    current_notes.remove(note_name(msg.note))
            if is_chord(current_notes):
                # Identify chords and potential cadences
                chord = tuple(sorted(current_notes))
                if chord == ('G', 'B', 'D') or chord == ('C', 'E', 'G'):  # Simplified V-I cadence detection
                    cadences.append((chord, time))

    # Identify motifs and ostinatos
    for i in range(len(notes) - 3):
        motif = tuple(note_name(note[0]) for note in notes[i:i + 4])
        motifs[motif] += 1
        if motifs[motif] > 2:
            ostinatos[motif] += 1

    # Identify arpeggios
    for i in range(len(notes) - 3):
        arpeggio = tuple(note_name(note[0]) for note in notes[i:i + 3])
        if is_chord(arpeggio):
            arpeggios.append(arpeggio)

    # Identify sequences (simple example)
    for i in range(len(notes) - 3):
        seq1 = notes[i:i + 3]
        for j in range(i + 3, len(notes) - 3):
            seq2 = notes[j:j + 3]
            if [n[0] for n in seq1] == [n[0] for n in seq2]:
                sequences[tuple(note_name(n[0]) for n in seq1)] += 1

    return {
        'motifs': motifs,
        'ostinatos': ostinatos,
        'arpeggios': arpeggios,
        'cadences': cadences,
        'sequences': sequences,
    }

# Example usage
file_path = 'testing_tools/test_scripts/take_on_me_midi/take_on_me.mid'
analysis = analyze_midi(file_path)

print("Motifs:", analysis['motifs'])
print("Ostinatos:", analysis['ostinatos'])
print("Arpeggios:", analysis['arpeggios'])
print("Cadences:", analysis['cadences'])
print("Sequences:", analysis['sequences'])
