import numpy as np
import sys
import os

from miditoolkit.midi import parser as mid_parser  
from miditoolkit.midi import containers as ct


def segment_tracks(input_path: str, start_bar: int, end_bar: int):
    # Check if the input file exists
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"The input file {input_path} does not exist.")
    
    # Load MIDI file
    try:
        mido_obj = mid_parser.MidiFile(input_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load MIDI file: {e}")

    
    beat_resol = mido_obj.ticks_per_beat

    # Define interval: from start to 8th end
    st = beat_resol * 4 * start_bar
    ed = beat_resol * 4 * end_bar

    
    # Export
    try:
        print("Enter file name: ")
        output_path_input = input()
        output_path = "type in dir"+ output_path_input + ".mid"
        mido_obj.dump(output_path ,segment=(st, ed))
        print("file has been saved as", output_path )
    except Exception as e:
        raise RuntimeError(f"Failed to dump MIDI file: {e}")



input_path = "some midi file"
print("Enter the start bar: ")
start_bar = int(input())
print("Enter the end bar:")
end_bar = int(input())
print("Segment from" ,start_bar , "to" , end_bar)
segment_tracks(input_path, start_bar, end_bar)

