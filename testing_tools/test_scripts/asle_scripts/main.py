import tkinter as tk
from tkinter.filedialog import askopenfilenames, askdirectory

def single_file():

    filetypes = (
        ("Midi files", "*.MID"),
        ("All files", "*.*")
    )
    root.withdraw()
    filename = askopenfilenames(title="Select a midi file...", filetypes=filetypes)
    print(filename)
    root.deiconify()

def folder():
    root.withdraw()
    filename = askdirectory(title="Select a folder...")
    print(filename)
    root.deiconify()


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("200x100")

    button = tk.Button(root, text="single file", command=single_file)
    button2 = tk.Button(root, text="folder", command=folder)
    button.pack()
    button2.pack()

    root.mainloop()
