import multiprocessing.process
import os
import tkinter as tk
from tkinter.filedialog import askopenfilename, askdirectory
from pattern_detection import asle
import multiprocessing

def single_file():
    filetypes = (
        ("Midi files", "*.MID"),
        ("All files", "*.*")
    )
    root.withdraw()
    input_path = askopenfilename(title="Select a midi file...", filetypes=filetypes)
    try:
        print(f'{input_path=}')
        if input_path != "":
            output_location = input_path[:input_path.find(".mid")] + "_Patterns"
            if not os.path.exists(output_location):
                os.mkdir(output_location)
            asle(input_path, output_location, one_file_per_pattern)
    except Exception as e:
        print(f'{e=}')
    root.deiconify()

def folder():
    root.withdraw()
    input_path = askdirectory(title="Select a folder...")
    print(f'{input_path=}')
    if input_path != "":
        output_location = input_path + "_Patterns"
        if not os.path.exists(output_location):
            os.mkdir(output_location)
        i = 0
        process_queue = []
        for rootdir, dirs, files in os.walk(input_path):
            for dir in dirs:
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


def toggle(button: tk.Button):
    global overwrite
    if button.config('relief')[-1] == 'sunken':
        button.config(relief="raised")
        toggle_label.config(text="No")
        overwrite = False
    else:
        button.config(relief="sunken")
        toggle_label.config(text="Yes")
        overwrite = True

def toggle2(button: tk.Button):
    global overwrite
    if button.config('relief')[-1] == 'sunken':
        button.config(relief="raised")
        toggle_label2.config(text="No")
        one_file_per_pattern = False
    else:
        button.config(relief="sunken")
        toggle_label2.config(text="Yes")
        one_file_per_pattern = True

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("400x150")

    overwrite = False
    one_file_per_pattern = False
    
    info_text = tk.Label(root, text='Open a singular midi file with the "single file" button \n or run the program on midis inside a whole folder with the "folder" button')
    toggle_frame = tk.Frame()
    toggle_button = tk.Button(toggle_frame, text="Overwrite existing patterns?", relief="raised", command= lambda:toggle(toggle_button))
    toggle_button2 = tk.Button(toggle_frame, text="One file per pattern?", relief="raised", command= lambda:toggle2(toggle_button2))
    toggle_label = tk.Label(toggle_frame, text="No")
    toggle_label2 = tk.Label(toggle_frame, text="No")
    button = tk.Button(root, text="single file", command=single_file)
    button2 = tk.Button(root, text="folder", command=folder)


    info_text.pack(fill="both")
    toggle_button.grid(row=0, column=0, padx=5)
    toggle_button2.grid(row=1, column=0, padx=5)
    toggle_label.grid(row=0, column=1, padx=5)
    toggle_label2.grid(row=1, column=1, padx=5)
    toggle_frame.pack(padx=5, pady=10)
    button.pack(padx=5)
    button2.pack(padx=5)

    root.mainloop()
