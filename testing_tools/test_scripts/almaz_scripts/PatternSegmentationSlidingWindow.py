from music21 import converter, note, chord, stream
import matplotlib.pyplot as plt
import numpy as np

def read_midi_file(file_path):
    """
    Reads a MIDI file and extracts the pitch sequence and corresponding start and end ticks.

    Parameters:
    file_path (str): Path to the MIDI file.

    Returns:
    list: List of tuples containing MIDI pitches and their start and end ticks.
    """
    score = converter.parse(file_path)
    melody = score.parts[0].flat.notesAndRests
    ticks_per_quarter = score.metronomeMarkBoundaries()[0][-1].secondsPerQuarter() * 480
    pitch_sequence = []

    for n in melody:
        if n.isNote:
            pitch_sequence.append((n.pitch.midi, int(n.offset * ticks_per_quarter), int((n.offset + n.quarterLength) * ticks_per_quarter)))
        elif n.isChord:
            for pitch in n.pitches:
                pitch_sequence.append((pitch.midi, int(n.offset * ticks_per_quarter), int((n.offset + n.quarterLength) * ticks_per_quarter)))
                
    return pitch_sequence

def find_repeating_motifs(pitch_sequence, min_length=4, max_length=2000000):
    """
    Finds repeating motifs in a pitch sequence.

    Parameters:
    pitch_sequence (list): List of MIDI pitches and their start times.
    min_length (int): Minimum length of motifs to consider.
    max_length (int): Maximum length of motifs to consider.

    Returns:
    dict: Dictionary of repeating motifs and their positions.
    """
    motifs = {}
    pitches_only = [pitch for pitch, _, _ in pitch_sequence]
    motif_id = 0
    
    for length in range(min_length, max_length + 1):
        for i in range(len(pitches_only) - length + 1):
            motif = tuple(pitches_only[i:i+length])
            if motif in motifs:
                motifs[motif]['positions'].append(i)
            else:
                motifs[motif] = {'id': motif_id, 'positions': [i]}
                motif_id += 1
    
    repeating_motifs = {m: v for m, v in motifs.items() if len(v['positions']) > 1}
    return repeating_motifs

def segment_track(pitch_sequence, repeating_motifs, max_silence_ticks=1000):
    """
    Segments the track based on the most repeating and longest motifs.

    Parameters:
    pitch_sequence (list): List of MIDI pitches and their start times.
    repeating_motifs (dict): Dictionary of repeating motifs and their positions.
    max_silence_ticks (int): Maximum allowable silence between notes in a segment.

    Returns:
    list: List of tuples representing the start and end positions of segments in original times and count of repetitions.
    """
    segments = []
    used_indices = set()
    
    sorted_motifs = sorted(repeating_motifs.items(), key=lambda x: (len(x[0]), len(x[1]['positions'])), reverse=True)
    
    for motif, data in sorted_motifs:
        motif_id = data['id']
        positions = data['positions']
        for pos in positions:
            if all(i not in used_indices for i in range(pos, pos + len(motif))):
                start_tick = pitch_sequence[pos][1]
                end_tick = pitch_sequence[pos + len(motif) - 1][2]  # End time of the last note
                # Check for maximum silence
                is_valid_segment = True
                for i in range(pos, pos + len(motif) - 1):
                    if pitch_sequence[i + 1][1] - pitch_sequence[i][2] > max_silence_ticks:
                        is_valid_segment = False
                        break
                if is_valid_segment:
                    segments.append((start_tick, end_tick, len(positions), motif, motif_id))
                    used_indices.update(range(pos, pos + len(motif)))
    
    return sorted(segments)

def plot_piano_roll_with_segments(pitch_sequence, segments):
    """
    Plots the piano roll with original notes and segmented motifs.

    Parameters:
    pitch_sequence (list): List of MIDI pitches and their start and end ticks.
    segments (list): List of tuples representing the start and end positions of segments in original times.
    """
    max_pitch = max(pitch for pitch, _, _ in pitch_sequence)
    min_pitch = min(pitch for pitch, _, _ in pitch_sequence)
    max_tick = max(end for _, _, end in pitch_sequence)
    
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Plot the original notes as blue rectangles
    for pitch, start, end in pitch_sequence:
        rect = plt.Rectangle((start, pitch - 0.4), end - start, 0.8, color='blue', alpha=0.6)
        ax.add_patch(rect)
    
    # Define colors for motifs
    colors = [
        'red', 'green', 'orange', 'purple', 'yellow', 'pink', 'cyan', 'magenta',
        'brown', 'lime', 'olive', 'navy', 'teal', 'maroon', 'violet', 'gold', 
        'silver', 'gray', 'black', 'blue', 'indigo', 'coral', 'crimson', 'aqua',
        'azure', 'beige', 'bisque', 'blanchedalmond', 'blueviolet', 'burlywood',
        'cadetblue', 'chartreuse', 'chocolate', 'cornflowerblue', 'cornsilk', 
        'darkblue', 'darkcyan', 'darkgoldenrod', 'darkgray', 'darkgreen', 
        'darkkhaki', 'darkmagenta', 'darkolivegreen', 'darkorange', 'darkorchid',
        'darkred', 'darksalmon', 'darkseagreen', 'darkslateblue', 'darkslategray',
        'darkturquoise', 'darkviolet', 'deeppink', 'deepskyblue', 'dimgray', 
        'dodgerblue', 'firebrick', 'floralwhite', 'forestgreen', 'fuchsia', 
        'gainsboro', 'ghostwhite', 'goldenrod', 'greenyellow', 'honeydew', 'hotpink',
        'indianred', 'ivory', 'khaki', 'lavender', 'lavenderblush', 'lawngreen', 
        'lemonchiffon', 'lightblue', 'lightcoral', 'lightcyan', 'lightgoldenrodyellow',
        'lightgray', 'lightgreen', 'lightpink', 'lightsalmon', 'lightseagreen', 
        'lightskyblue', 'lightslategray', 'lightsteelblue', 'lightyellow', 
        'limegreen', 'linen', 'mediumaquamarine', 'mediumblue', 'mediumorchid', 
        'mediumpurple', 'mediumseagreen', 'mediumslateblue', 'mediumspringgreen',
        'mediumturquoise', 'mediumvioletred', 'midnightblue', 'mintcream', 'mistyrose',
        'moccasin', 'navajowhite', 'oldlace', 'olivedrab', 'orangered', 'orchid',
        'palegoldenrod', 'palegreen', 'paleturquoise', 'palevioletred', 'papayawhip', 
        'peachpuff', 'peru', 'plum', 'powderblue', 'rosybrown', 'royalblue', 
        'saddlebrown', 'salmon', 'sandybrown', 'seagreen', 'seashell', 'sienna', 
        'skyblue', 'slateblue', 'slategray', 'snow', 'springgreen', 'steelblue', 
        'tan', 'thistle', 'tomato', 'turquoise', 'wheat', 'whitesmoke', 'yellowgreen'
    ]
    motif_color_map = {}
    
    # Plot the segments with the same color for the same motifs
    for idx, segment in enumerate(segments):
        start, end, count, motif, motif_id = segment
        if motif not in motif_color_map:
            motif_color_map[motif] = colors[len(motif_color_map) % len(colors)]
        color = motif_color_map[motif]
        ax.add_patch(plt.Rectangle((start, min_pitch - 0.5), end - start, max_pitch - min_pitch + 1, color=color, alpha=0.3))
        ax.text((start + end) / 2, max_pitch + 1, f'Start: {start} ticks\nEnd: {end} ticks\nLength: {end - start} ticks\n Motif ID: {motif_id}\nRepetitions: {count}', 
                ha='center', va='bottom', fontsize=7, color='darkblue')
    
    ax.set_xlim(0, max_tick)
    ax.set_ylim(min_pitch - 1, max_pitch + 2)
    ax.set_xlabel('Time (ticks)')
    ax.set_ylabel('Pitch (MIDI)')
    
    plt.title('Piano Roll with Segmented Motifs')
    plt.show()

def generate_report(segments):
    """
    Generates a report of the found segments.

    Parameters:
    segments (list): List of tuples representing the start and end positions of segments.

    Returns:
    str: Formatted report of the segments.
    """
    report = "Segment Report:\n"
    for i, (start, end, count, motif, motif_id) in enumerate(segments):
        length = end - start
        report += f"Segment {i + 1}:\n"
        report += f"  Motif ID: {motif_id}\n"
        report += f"  Start: {start} ticks\n"
        report += f"  End: {end} ticks\n"
        report += f"  Length: {length} ticks\n"
        report += f"  Repetitions: {count}\n"
        report += f"  Motif: {motif}\n"
        report += "-" * 20 + "\n"
    return report
        
def main(file_path):
    """
    Main function to read MIDI file, find repeating motifs, segment the track, plot the piano roll, and generate a report.

    Parameters:
    file_path (str): Path to the MIDI file.
    """
    pitch_sequence = read_midi_file(file_path)
    repeating_motifs = find_repeating_motifs(pitch_sequence)
    segments = segment_track(pitch_sequence, repeating_motifs)
    plot_piano_roll_with_segments(pitch_sequence, segments)
    report = generate_report(segments)
    print(report)

# Path to your MIDI file
#file_path = 'testing_tools/Manual_seg/take_on_me/track1.mid'
file_path = 'C:\\Installerte program\\vscodeworkspaces\\SaMuGeD-Algoritmi-DrDreSamplerAI-2024\\testing_tools\\test_scripts\\pattern_output\\Beat_It4.mid'
#file_path = 'testing_tools/i_am_trying_sf_segmenter_a_bit/Something_in_the_Way.mid'
main(file_path)
