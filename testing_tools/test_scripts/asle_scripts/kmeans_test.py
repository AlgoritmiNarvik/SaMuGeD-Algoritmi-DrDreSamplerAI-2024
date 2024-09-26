import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from miditoolkit.midi.parser import MidiFile
from tkinter.filedialog import askopenfilename, askdirectory
import os

def folder():
    input_path = askdirectory(title="Select a folder...")
    print(f'{input_path=}')
    if input_path != "":
        output_location = input_path + "_sorted_patterns"
        if not os.path.exists(output_location):
            os.mkdir(output_location)
        i = 0
        process_queue = []
        for rootdir, dirs, files in os.walk(input_path):
            for dir in dirs: # might need to rewrite this loop
                if '_Patterns' in dir:
                    dirs.remove(dir) # don't visit pattern directories
            for file in files:
                if file[-4:] == ".mid":
                    temp_path = rootdir[len(output_location)+1-len("_Patterns"):] + "_Patterns"
                    save_dir = os.path.join(output_location, temp_path)
                    if not os.path.exists(save_dir):
                        os.mkdir(save_dir)
                    temp_path = os.path.join(save_dir, file)
                    if not os.path.exists(temp_path):
                        os.mkdir(temp_path)
                    elif not overwrite:
                        print(f'skipped {temp_path}, found existing pattern folder')
                        continue
                    #asle(os.path.join(rootdir, file), temp_path, one_file_per_pattern)
                    file = multiprocessing.Process(target=asle, args=(os.path.join(rootdir, file), temp_path, one_file_per_pattern))
                    process_queue.append(file)
                    
                         
            if i == 1200: #limit amount of subfolders to iterate through
                break
            i+=1

    system_cores = os.cpu_count() #System logical cores/threads
    max_thread_count = system_cores - 2 if system_cores <= 16 else system_cores - 4 #limit the amount of processes to have running at the same time. YOUR COMPUTER WILL CRASH IF YOU GO ABOVE THIS LIMIT!
    active_processes = []
    for process in process_queue:
        if len(active_processes) >= max_thread_count-2:
            for active_process in active_processes:
                active_process.join()
            active_processes = []
        process.start()
        active_processes.append(process)

    for process in active_processes:
        process.join()
        
    print(f'Done!')

    root.deiconify()

def feature_func(midi_obj): #Takes a midi file object as input, output list of features
    """
    Returns a list of features for the input midi file

    Parameters
    ----------- 
        midi_obj : MidiFile

    Returns
    -------
        List : features
    """
    #features to use
    #pitch range. Max pitch minus min pitch
    #largest pitch jump?
    #smallest pitch jump?
    #average pitch jump? maybe not a good feature
    #number of notes
    #max number of notes in one bar
    #min number of notes in one bar
    #Frequency of notes/notes per second

    min_pitch = 1000
    max_pitch = 0
    min_pitch_jump = 1000
    max_pitch_jump = 0
    number_of_notes = 0
    frequency_of_notes = 0 # currently not used

    previous_note = 0
    for note in midi_obj.instruments[0].notes:
        if note.pitch > max_pitch:
            max_pitch = note.pitch
        if note.pitch < min_pitch:
            min_pitch = note.pitch
        
        pitch_jump = note.pitch - previous_note.pitch
        if pitch_jump > max_pitch_jump:
            max_pitch_jump = pitch_jump
        if pitch_jump < min_pitch_jump:
            min_pitch_jump = pitch_jump

        previous_note = note

    number_of_notes = midi_obj.instruments[0].notes.__len__
    pitch_range = max_pitch - min_pitch

    data = [min_pitch, max_pitch, pitch_range, min_pitch_jump, max_pitch_jump, number_of_notes]
    return data


def kmeans_clustering(data:list, clusters=5, elbow=False) -> list:#input complete list of data with features, output correspoding grouping numbers
    """
    Set elbow=True to find the amount of clusters to use for your dataset.

    Parameters
    ----------- 
        data : List
        clusters : int
        elbow : bool

    Returns
    -------
        List : Fitted estimator number for each datapoint        
    """
    data_points = len(data)

    if elbow: #Elbow method to find n_clusters appropriate for dataset
        inertias = []
        for i in range(1,data_points):
            kmeans = KMeans(n_clusters=i)
            kmeans.fit(data)
            inertias.append(kmeans.inertia_)

        plt.plot(range(1,data_points), inertias, marker='o')
        plt.title('Elbow method')
        plt.xlabel('Number of clusters')
        plt.ylabel('Inertia')
        plt.show()
        return None 


    kmeans = KMeans(n_clusters=clusters)
    kmeans.fit(data)

    group_numbers = kmeans.labels_

    return group_numbers


def main():#Input folder with patterns, Output None(Makes folder with sorted patterns adjacent to input folder)
    #for all pattern midi files
        #get list of features
        #put list of features into one list

    #use aggregate list as input for kmeans_clustering

    #use output from kmeans to sort patterns into folders in an output folder

if __name__ == "__main__":
