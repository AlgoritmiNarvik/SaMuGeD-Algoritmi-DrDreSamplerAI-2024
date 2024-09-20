import tkinter as tk
#from tkinter import RAISED, SUNKEN, filedialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from miditoolkit.midi.parser import MidiFile
import pygame


pygame.init()
pygame.mixer.init()

def open_midi_file():
    filepath = tk.filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid *.midi")])
    if not filepath:
        return
    current_midi_path = filepath
    midi_file = MidiFile(filepath)
    notes = extract_notes(midi_file)
    plot_piano_roll_original(notes)
    print(canvas_frame.winfo_geometry())

def open_midi_file_similar():
    filepath = tk.filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid *.midi")])
    if not filepath:
        return
    current_midi_path = filepath
    midi_file = MidiFile(filepath)
    notes = extract_notes(midi_file)
    plot_piano_roll_similar(notes)

def play_midi():
    #play_button.config(relief=tk.SUNKEN)
    if current_midi_path:
        print(pygame.mixer.music.get_busy())
        pygame.mixer.music.stop()
        pygame.mixer.music.load(current_midi_path)
        pygame.mixer.music.play()
        #print(pygame.mixer.music.get_busy())
        #a = pygame.mixer.music.get_endevent()
        #print(f'{a=}')

def stop_midi():
    pygame.mixer.music.stop()
    #play_button.config(relief=tk.RAISED)

def music_ended(): # currently unused, was intended to make play button clickable again after music has stopped playing
    play_button.config(relief=tk.RAISED)

def extract_notes(midi_file):
    notes = midi_file.instruments[0].notes
    #print(f'{notes=}')
    return notes

def plot_piano_roll_original(notes):
    figwidth = canvas_original.figure.get_figwidth()
    figheight = canvas_original.figure.get_figheight()
    fig = Figure(figsize=(figwidth, figheight))
    axis = fig.add_subplot(111)
    offset = notes[0].start
    for note in notes:
        axis.barh(note.pitch, (note.end - note.start), left=(note.start - offset), height=0.8, color='blue' if note.velocity > 0 else 'red')
    axis.set_xlabel('Ticks')
    axis.set_ylabel('Note')
    axis.set_title('Original')
    canvas_original.figure = fig
    canvas_original.draw()

def plot_piano_roll_similar(notes):
    figwidth = canvas_similar.figure.get_figwidth()
    figheight = canvas_similar.figure.get_figheight()
    fig = Figure(figsize=(figwidth, figheight))
    axis = fig.add_subplot(111)
    offset = notes[0].start
    for note in notes:
        axis.barh(note.pitch, (note.end - note.start), left=(note.start - offset), height=0.8, color='blue' if note.velocity > 0 else 'red')
    axis.set_xlabel('Ticks')
    axis.set_ylabel('Note')
    axis.set_title('Similar')
    canvas_similar.figure = fig
    canvas_similar.draw()


def build_scrollbar():
    scrollbar_frame = tk.Frame()
    scroll_bar = tk.Scrollbar(scrollbar_frame) 
    scroll_bar.pack( side = tk.RIGHT, fill = tk.Y ) 
    mylist = tk.Listbox(scrollbar_frame, yscrollcommand = scroll_bar.set ) 

    for line in range(1, 26): 
        mylist.insert(tk.END, "temp" + str(line)) 
    mylist.pack(side = tk.RIGHT, fill = tk.BOTH, expand=1) 
    scroll_bar.config(command = mylist.yview ) 
    scrollbar_frame.pack(side=tk.LEFT, fill=tk.BOTH)

def build_buttons():
    global load_button, play_button, stop_button, temp_similar_button
    load_button = tk.Button(window, text="Load MIDI", command=open_midi_file)
    load_button.pack(side=tk.BOTTOM)

    play_button = tk.Button(window, text="Play MIDI", command=play_midi)
    play_button.pack(side=tk.BOTTOM)

    stop_button = tk.Button(window, text="Stop MIDI", command=stop_midi)
    stop_button.pack(side=tk.BOTTOM)

    temp_similar_button = tk.Button(window, text="temp Similar button", command=open_midi_file_similar)
    temp_similar_button.pack(side=tk.BOTTOM)

def build_canvas():
    global canvas_original, canvas_similar, canvas_frame
    canvas_frame = tk.Frame()
    canvas_original = FigureCanvasTkAgg(None, master=canvas_frame)
    canvas_original.get_tk_widget().pack(side=tk.BOTTOM, fill=tk.BOTH, expand=1)

    canvas_similar = FigureCanvasTkAgg(None, master=canvas_frame)
    canvas_similar.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
    canvas_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=1)

def main():
    global window, current_midi_path
    current_midi_path = None

    window = tk.Tk()
    window.title("MIDI Piano Roll Viewer")

    
    build_canvas()
    build_buttons()
    build_scrollbar() # build scrollbar


    window.mainloop()


if __name__ == "__main__":
    main()

#two canvases, one for user sample, one for returned sample
#List
#Label that shows status of midi player
#Make play midi unclickable if midi is playing
#double check that the length of notes being plotted is correct
#nice to have: line that shows where the player is in the pianoroll
#buttons to navigate the list
#save button that puts the selected sample into a folder in downloads


#problem, need to wait for sounds because samples are saved with original note timings. Maybe make temporary midis with the offset removed? or render an mp3 file and input start time