import os
from tkinter.filedialog import askopenfilename, askdirectory


def remove_empty_folders(path):
    if not os.path.isdir(path):
        print(f"Error: {path} is not a directory or does not exist.")
        return

    files = os.listdir(path)
    if len(files):
        for f in files:
            fullpath = os.path.join(path, f)
            if os.path.isdir(fullpath):
                remove_empty_folders(fullpath)

    files = os.listdir(path)
    if len(files) == 0:
        print(f"Removing empty folder: {path}")
        os.rmdir(path)

def main():
    directory = askdirectory(title="Select a folder...")
    if os.path.exists(directory):
        remove_empty_folders(directory)
    else:
        print("The specified directory does not exist.")

if __name__ == "__main__":
    main()