from pathlib import Path
import os


from miditoolkit.midi.parser import MidiFile
from miditoolkit.midi.containers import Instrument, Note
from miditoolkit.midi import parser as mid_parser

#dirx = input("Enter folder/directory with dataset: ")
dirx = "C:\\Users\\asle1\\Downloads\\Lakh MIDI Clean"

dirx = os.walk(dirx, topdown=True)
#print(f'{dirx=}')




for i, path in enumerate(dirx):
    if i == 0: #Ignore the repo files in base dir
        continue
    if i == 20:
        quit()

    print(f'\nContents in {path[0]}: ')
    for file in path[2]:
        print(f'{file=}')
        try:
            temp = MidiFile(path[0] + '\\' + file)
            #print(temp.tempo_changes)
            print(f'{temp.ticks_per_beat=}')
            
            if len(temp.time_signature_changes) > 1:
                #print('Yes')
                #print(path[0])
                print(f'{temp.time_signature_changes=}')
        except Exception as e:
            #print(f'{e}')
            pass


#number of songs with more than one time signature
#histogram of used time signatures
#time signatures used within band
#number of songs with each time signature
#Index of timesignatures in each song?