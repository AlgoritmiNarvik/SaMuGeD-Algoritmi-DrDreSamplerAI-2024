import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Tuple
from config import DEFAULT_FEATURE_WEIGHTS
from database import MIDIDatabase

class MIDISearchApp:
    def __init__(self, root):
        self.root = root
        self.db = MIDIDatabase()
        self.weights = DEFAULT_FEATURE_WEIGHTS.copy()
        
        try:
            self.db.initialize()
            self._init_ui()
            self._setup_logging()
        except Exception as e:
            messagebox.showerror("Initialization Error", 
                               f"Failed to initialize database: {str(e)}")
            self.root.destroy()

    def _init_ui(self):
        """Initialize user interface"""
        self.root.title("MIDI Pattern Finder")
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=tk.NSEW)
        
        # Weight controls
        self.weight_vars = {}
        for idx, (feat, val) in enumerate(DEFAULT_FEATURE_WEIGHTS.items()):
            ttk.Label(main_frame, text=f"{feat.replace('_', ' ').title()}:").grid(row=idx, column=0, sticky=tk.W)
            self.weight_vars[feat] = tk.DoubleVar(value=val)
            ttk.Scale(main_frame, from_=0, to=3, variable=self.weight_vars[feat],
                     command=lambda v, f=feat: self._update_weight(f, v)).grid(row=idx, column=1, sticky=tk.EW)
            ttk.Label(main_frame, textvariable=self.weight_vars[feat]).grid(row=idx, column=2, padx=5)
        
        # File controls
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=len(DEFAULT_FEATURE_WEIGHTS)+1, column=0, columnspan=3, pady=10)
        ttk.Button(file_frame, text="Load MIDI File", command=self._load_midi).pack(side=tk.LEFT, padx=5)
        
        # Results
        self.results_tree = ttk.Treeview(main_frame, columns=('similarity', 'path'), show='headings')
        self.results_tree.heading('similarity', text='Similarity Score')
        self.results_tree.heading('path', text='File Path')
        self.results_tree.grid(row=len(DEFAULT_FEATURE_WEIGHTS)+2, column=0, columnspan=3, sticky=tk.NSEW)
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.grid(row=len(DEFAULT_FEATURE_WEIGHTS)+3, column=0, columnspan=3, sticky=tk.EW)
        
        # Configure grid weights
        main_frame.rowconfigure(len(DEFAULT_FEATURE_WEIGHTS)+2, weight=1)
        main_frame.columnconfigure(1, weight=1)

    def _update_weight(self, feature: str, value: str):
        self.weights[feature] = float(value)

    def _load_midi(self):
        path = filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid;*.midi")])
        if path:
            self._run_search(path)

    def _run_search(self, query_path: str):
        try:
            self.progress['value'] = 0
            results = self.db.find_similar(query_path, self.weights)
            self._display_results(results)
            self.progress['value'] = 100
        except Exception as e:
            messagebox.showerror("Search Error", str(e))
            self.progress['value'] = 0

    def _display_results(self, results: List[Tuple[str, float]]):
        self.results_tree.delete(*self.results_tree.get_children())
        for path, score in sorted(results, key=lambda x: x[1], reverse=True):
            self.results_tree.insert('', 'end', values=(f"{score:.2%}", path))

    def _setup_logging(self):
        logging.basicConfig(
            filename='midi_search.log',
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

if __name__ == "__main__":
    root = tk.Tk()
    app = MIDISearchApp(root)
    root.mainloop()
