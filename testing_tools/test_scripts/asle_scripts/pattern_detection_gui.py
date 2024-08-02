import os
import tkinter as tk
from tkinter.filedialog import askopenfilename, askdirectory
from pattern_detection import asle

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
            asle(input_path, output_location)
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
                    asle(os.path.join(rootdir, file), temp_path)
                         
            if i == 10: #limit amount of subfolders to iterate through
                break
            i+=1
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

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("400x150")

    overwrite = False
    
    info_text = tk.Label(root, text='Open a singular midi file with the "single file" button \n or run the program on midis inside a whole folder with the "folder" button')
    toggle_frame = tk.Frame()
    toggle_button = tk.Button(toggle_frame, text="Overwrite existing patterns?", relief="raised", command= lambda:toggle(toggle_button))
    toggle_label = tk.Label(toggle_frame, text="No")
    button = tk.Button(root, text="single file", command=single_file)
    button2 = tk.Button(root, text="folder", command=folder)


    info_text.pack(fill="both")
    toggle_button.grid(row=0, column=0, padx=5)
    toggle_label.grid(row=0, column=1, padx=5)
    toggle_frame.pack(padx=5, pady=10)
    button.pack(padx=5)
    button2.pack(padx=5)

    root.mainloop()
