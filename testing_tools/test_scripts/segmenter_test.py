import sf_segmenter
import sys
import os
import matplotlib.pyplot as plt
import numpy as np

INPUT_PATH = "take_on_me.mid"
CONFIG = {
    "M_gaussian": 27,
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
    output_dir = project_directory + "\\plots"
    input_file_path = project_directory + "\\" + INPUT_PATH
else:
    output_dir = project_directory + "/plots"
    input_file_path = project_directory + "/" + INPUT_PATH

segmenter = sf_segmenter.Segmenter(config=CONFIG)

if INPUT_PATH[-4:] == ".mid":
    segmenter.proc_midi(input_file_path)
else:
    segmenter.proc_audio(input_file_path)

segmenter.plot(output_dir)
#plt.show()

print(f'Plots have been saved to: {output_dir} \n Press enter to close this window')
#input() #To prevent window from closing before being able to read text
