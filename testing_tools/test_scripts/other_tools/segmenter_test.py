import sf_segmenter
import sys
import os
import matplotlib.pyplot as plt
import numpy as np

from miditoolkit.midi import parser as mid_parser  
from miditoolkit.midi import containers as ct

def extract_features(INPUT_PATH, save_plots = False, show_plots = True, CONFIG = None):
    if CONFIG == None:
        CONFIG = {
            "M_gaussian": 10,
            "m_embedded": 3,
            "k_nearest": 0.04,
            "Mp_adaptive": 28,
            "offset_thres": 0.05,
            "bound_norm_feats": np.inf  # min_max, log, np.inf,
                                        # -np.inf, float >= 0, None
            # For framesync features
            # "M_gaussian"    : 100,
            # "m_embedded"    : 3,
            # "k_nearest"     : 0.06,
            # "Mp_adaptive"   : 100,
            # "offset_thres"  : 0.01
        }

    project_directory = os.path.dirname(os.path.realpath(__file__))
    OS_TYPE = sys.platform

    if OS_TYPE == "win32":
        output_dir = project_directory + "\\plots\\" + INPUT_PATH[:-4]
        input_file_path = project_directory + "\\" + INPUT_PATH
    else:
        output_dir = project_directory + "/plots"
        input_file_path = project_directory + "/" + INPUT_PATH

    segmenter = sf_segmenter.Segmenter(config=CONFIG)

    if INPUT_PATH[-4:] == ".mid":
        segmenter.proc_midi(input_file_path)
    else:
        segmenter.proc_audio(input_file_path)

    if save_plots == True:
        segmenter.plot(output_dir)
        print(f'Plots have been saved to: {output_dir}')
    if show_plots == True:
        segmenter.plot("temp")
        plt.show()


def split_tracks(INPUT_PATH: str):
    # load midi file
    mido_obj = mid_parser.MidiFile(INPUT_PATH)
    print("Instruments: \n")
    for i, instrument in enumerate(mido_obj.instruments): #iterate over the instruments
        #print(f'{i}: {instrument.name} - Is drum: {instrument.is_drum}')
        if instrument.is_drum != True: #If the instrument is not drum

            if not os.path.isdir(INPUT_PATH[:-4]):
                os.mkdir(INPUT_PATH[:-4])

            # create a mid file for track i
            obj = mid_parser.MidiFile()
            obj.ticks_per_beat = mido_obj.ticks_per_beat
            obj.max_tick = mido_obj.max_tick
            obj.tempo_changes = mido_obj.tempo_changes
            obj.time_signature_changes = mido_obj.time_signature_changes
            obj.key_signature_changes = mido_obj.key_signature_changes
            obj.lyrics = mido_obj.lyrics
            obj.markers = mido_obj.markers
            obj.instruments = [instrument]
            
            # write to file
            OS_TYPE = sys.platform
            if OS_TYPE == "win32":
                obj.dump(f'{INPUT_PATH[:-4]}\\track{i}.mid')
            else:
                obj.dump(f'{INPUT_PATH[:-4]}/track{i}.mid')

        else:
            print("Skipped drum instrument")

    print(f'Each track has been saved to:')

#INPUT_PATH = "track_1_seg_02_intro2.mid"
#extract_features(INPUT_PATH,show_plots=True)


INPUT_PATH = "take_on_me.mid"
split_tracks(INPUT_PATH)

OUTPUT_DIR = INPUT_PATH[:-4]
# iterate over files in
# that directory
for filename in os.listdir(OUTPUT_DIR):
    f = os.path.join(OUTPUT_DIR, filename)
    # checking if it is a file
    if os.path.isfile(f):
        extract_features(f,save_plots=True)