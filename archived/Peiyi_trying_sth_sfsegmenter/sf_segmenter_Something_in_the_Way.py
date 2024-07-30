import sf_segmenter
import os
import sys


INPUT_PATH = "Something_in_the_Way.mid"
project_directory = os.path.dirname(os.path.realpath(__file__))
OS_TYPE = sys.platform

if OS_TYPE == "win32":
    output_dir = project_directory + "\\plots"
    input_file_path = project_directory + "\\" + INPUT_PATH
else:
    output_dir = project_directory + "/plots"
    input_file_path = project_directory + "/" + INPUT_PATH

segmenter = sf_segmenter.Segmenter()

if INPUT_PATH[-4:] == ".mid":
    segmenter.proc_midi(input_file_path)
else:
    segmenter.proc_audio(input_file_path)

segmenter.plot(output_dir)

print(f'Plots have been saved to: {output_dir} \n Press enter to close this window')
input() #To prevent window from closing before being able to read text