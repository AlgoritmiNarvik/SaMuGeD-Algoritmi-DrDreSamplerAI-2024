import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Tuple
import os
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH
from database import MIDIDatabase
from midi_player import MIDIPlayer

class MIDISearchApp:
    def __init__(self, root):
        self.root = root
        self.db = MIDIDatabase()
        self.player = MIDIPlayer()
        self.weights = DEFAULT_FEATURE_WEIGHTS.copy()
        self._setup_logging()
        
        try:
            self.db.initialize()
            self._init_ui()
            
            # Show helpful message if no MIDI files found
            if len(self.db.file_paths) == 0:
                messagebox.showinfo(
                    "No MIDI Files",
                    f"No MIDI files found in the dataset directory:\n{DATASET_PATH}\n\n"
                    "You can:\n"
                    "1. Add MIDI files to this directory\n"
                    "2. Use 'Load MIDI File' to analyze individual files"
                )
        except Exception as e:
            self.logger.error(f"Initialization error: {str(e)}")
            messagebox.showerror("Initialization Error", 
                               f"Failed to initialize database: {str(e)}")
            self.root.destroy()

    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)

    def _init_ui(self):
        """Initialize user interface"""
        self.root.title("MIDI Pattern Finder")
        self.root.geometry("800x600")  # Set window size
        
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=tk.NSEW)
        
        # Weight controls frame
        weights_frame = ttk.LabelFrame(main_frame, text="Feature Weights", padding="10")
        weights_frame.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, 10))
        
        self.weight_vars = {}
        for idx, (feat, val) in enumerate(DEFAULT_FEATURE_WEIGHTS.items()):
            ttk.Label(weights_frame, text=f"{feat.replace('_', ' ').title()}:").grid(row=idx, column=0, sticky=tk.W)
            self.weight_vars[feat] = tk.DoubleVar(value=val)
            ttk.Scale(weights_frame, from_=0, to=3, variable=self.weight_vars[feat],
                     command=lambda v, f=feat: self._update_weight(f, v)).grid(row=idx, column=1, sticky=tk.EW)
            ttk.Label(weights_frame, textvariable=self.weight_vars[feat]).grid(row=idx, column=2, padx=5)
        
        # File controls
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=1, column=0, columnspan=3, pady=10)
        ttk.Button(file_frame, text="Load MIDI File", command=self._load_midi).pack(side=tk.LEFT, padx=5)
        
        # Current file label
        self.current_file_var = tk.StringVar(value="No file loaded")
        ttk.Label(file_frame, textvariable=self.current_file_var).pack(side=tk.LEFT, padx=5)
        
        # Playback controls
        playback_frame = ttk.LabelFrame(main_frame, text="Playback Controls", padding="10")
        playback_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=5)
        
        ttk.Button(playback_frame, text="▶", width=3, command=self._play_current).pack(side=tk.LEFT, padx=2)
        ttk.Button(playback_frame, text="⏸", width=3, command=self.player.pause).pack(side=tk.LEFT, padx=2)
        ttk.Button(playback_frame, text="⏹", width=3, command=self.player.stop).pack(side=tk.LEFT, padx=2)
        
        # Volume control
        volume_frame = ttk.Frame(playback_frame)
        volume_frame.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        ttk.Label(volume_frame, text="Volume:").pack(side=tk.LEFT)
        volume_scale = ttk.Scale(volume_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                               command=lambda v: self.player.set_volume(float(v)/100))
        volume_scale.set(70)
        volume_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Results frame
        results_frame = ttk.LabelFrame(main_frame, text="Similar MIDI Files", padding="10")
        results_frame.grid(row=3, column=0, columnspan=3, sticky=tk.NSEW, pady=5)
        
        # Results tree
        self.results_tree = ttk.Treeview(results_frame, columns=('similarity', 'path'), show='headings')
        self.results_tree.heading('similarity', text='Similarity')
        self.results_tree.heading('path', text='File Path')
        self.results_tree.column('similarity', width=100)
        self.results_tree.column('path', width=500)
        self.results_tree.grid(row=0, column=0, sticky=tk.NSEW)
        self.results_tree.bind('<Double-1>', self._play_selected)
        
        # Scrollbar for results
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.results_tree.yview)
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.results_tree.configure(yscrollcommand=scrollbar.set)
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(10, 0))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

    def _update_weight(self, feature: str, value: str):
        try:
            self.weights[feature] = float(value)
        except ValueError as e:
            self.logger.error(f"Error updating weight: {str(e)}")

    def _load_midi(self):
        try:
            filetypes = (
                ('MIDI files', '*.mid'),
                ('MIDI files', '*.midi'),
                ('All files', '*.*')
            )
            path = filedialog.askopenfilename(
                title="Select MIDI File",
                initialdir=os.path.expanduser("~"),
                filetypes=filetypes
            )
            
            if path:  # Only proceed if a file was selected
                self.logger.info(f"Loading MIDI file: {path}")
                self.current_file_var.set(os.path.basename(path))
                self._run_search(path)
                self.player.play(path)
        except Exception as e:
            self.logger.error(f"Error loading MIDI file: {str(e)}")
            messagebox.showerror("Error", f"Failed to load MIDI file: {str(e)}")

    def _play_current(self):
        try:
            if not self.player.is_playing and self.player.current_file:
                self.player.resume()
            elif not self.player.current_file and self.results_tree.selection():
                self._play_selected(None)
        except Exception as e:
            self.logger.error(f"Error playing file: {str(e)}")
            messagebox.showerror("Error", f"Failed to play file: {str(e)}")

    def _play_selected(self, event):
        try:
            selection = self.results_tree.selection()
            if selection:
                item = self.results_tree.item(selection[0])
                file_path = item['values'][1]
                self.current_file_var.set(os.path.basename(file_path))
                self.player.play(file_path)
        except Exception as e:
            self.logger.error(f"Error playing selected file: {str(e)}")
            messagebox.showerror("Error", f"Failed to play selected file: {str(e)}")

    def _run_search(self, query_path: str):
        try:
            self.progress['value'] = 0
            self.root.update_idletasks()
            
            results = self.db.find_similar(query_path, self.weights)
            self._display_results(results)
            
            self.progress['value'] = 100
            self.root.update_idletasks()
        except Exception as e:
            self.logger.error(f"Search error: {str(e)}")
            messagebox.showerror("Search Error", str(e))
            self.progress['value'] = 0

    def _display_results(self, results: List[Tuple[str, float]]):
        try:
            self.results_tree.delete(*self.results_tree.get_children())
            for path, score in sorted(results, key=lambda x: x[1], reverse=True):
                self.results_tree.insert('', 'end', values=(f"{score:.2%}", path))
        except Exception as e:
            self.logger.error(f"Error displaying results: {str(e)}")
            messagebox.showerror("Error", f"Failed to display results: {str(e)}")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = MIDISearchApp(root)
        root.mainloop()
    except Exception as e:
        logging.error(f"Application error: {str(e)}")
        messagebox.showerror("Error", f"Application error: {str(e)}")
    finally:
        if 'app' in locals():
            app.player.cleanup()  # Clean up MIDI resources on exit
