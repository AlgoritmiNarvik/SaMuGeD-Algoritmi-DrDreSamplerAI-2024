import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Tuple, Optional
import os
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH
from database import MIDIDatabase
from midi_player import MIDIPlayer
from piano_roll import PianoRollVisualizer
import sys

class MIDISearchApp:
    def __init__(self, root):
        self.root = root
        self.db = MIDIDatabase()
        self.player = MIDIPlayer()
        self.weights = DEFAULT_FEATURE_WEIGHTS.copy()
        self._setup_logging()
        
        # Set error callback for MIDI player
        self.player.set_error_callback(self._handle_playback_error)
        
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
        # Configure root window
        self.root.title("SaMuGed - MIDI Pattern Finder")
        self.root.geometry("1400x900")  # Larger window
        
        # Configure modern style
        style = ttk.Style()
        style.configure(".", font=('Helvetica', 10))
        style.configure("Treeview", rowheight=25)
        style.configure("Heading.TLabel", font=('Helvetica', 12, 'bold'))
        style.configure("Title.TLabel", font=('Helvetica', 14, 'bold'))
        
        # Configure dark theme colors
        style.configure(".", background='#2b2b2b', foreground='#ffffff')
        style.configure("TFrame", background='#2b2b2b')
        style.configure("TLabel", background='#2b2b2b', foreground='#ffffff')
        style.configure("TButton", background='#404040', foreground='#ffffff')
        style.configure("Treeview", background='#333333', foreground='#ffffff', fieldbackground='#333333')
        style.configure("TScale", background='#2b2b2b', troughcolor='#404040')
        style.configure("Vertical.TScrollbar", background='#404040', troughcolor='#2b2b2b')
        style.configure("Horizontal.TScrollbar", background='#404040', troughcolor='#2b2b2b')
        style.configure("TProgressbar", background='#404040', troughcolor='#2b2b2b')
        style.configure("TLabelframe", background='#2b2b2b', foreground='#ffffff')
        style.configure("TLabelframe.Label", background='#2b2b2b', foreground='#ffffff')
        
        # Configure grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        main_frame.grid_columnconfigure(1, weight=1)
        
        # Left panel (controls)
        left_panel = ttk.Frame(main_frame)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        
        # Query section
        query_frame = ttk.LabelFrame(left_panel, text="Input MIDI", padding=10)
        query_frame.pack(fill="x", pady=(0, 10))
        
        # Load button and current file
        ttk.Button(query_frame, text="Load MIDI File", command=self._load_midi).pack(fill="x", pady=(0, 5))
        self.current_file_var = tk.StringVar(value="No file loaded")
        current_file_label = ttk.Label(query_frame, textvariable=self.current_file_var, wraplength=250)
        current_file_label.pack(fill="x", pady=(0, 10))
        
        # Input piano roll
        piano_roll_frame = ttk.Frame(query_frame)
        piano_roll_frame.pack(fill="x", pady=(0, 10))
        self.input_piano_roll = PianoRollVisualizer(piano_roll_frame)
        
        # Input playback controls
        controls_frame = ttk.Frame(query_frame)
        controls_frame.pack(fill="x")
        
        ttk.Button(controls_frame, text="▶", width=3, command=self._play_current).pack(side="left", padx=2)
        ttk.Button(controls_frame, text="⏸", width=3, command=self.player.pause).pack(side="left", padx=2)
        ttk.Button(controls_frame, text="⏹", width=3, command=self.player.stop).pack(side="left", padx=2)
        
        # Feature weights
        weights_frame = ttk.LabelFrame(left_panel, text="Feature Weights", padding=10)
        weights_frame.pack(fill="x", pady=(0, 10))
        
        self.weight_vars = {}
        for idx, (feat, val) in enumerate(DEFAULT_FEATURE_WEIGHTS.items()):
            frame = ttk.Frame(weights_frame)
            frame.pack(fill="x", pady=2)
            
            label = ttk.Label(frame, text=f"{feat.replace('_', ' ').title()}:")
            label.pack(side="left")
            
            self.weight_vars[feat] = tk.DoubleVar(value=val)
            scale = ttk.Scale(frame, from_=0, to=3, variable=self.weight_vars[feat],
                            command=lambda v, f=feat: self._update_weight(f, v))
            scale.pack(side="left", fill="x", expand=True, padx=5)
            
            value_label = ttk.Label(frame, textvariable=self.weight_vars[feat], width=4)
            value_label.pack(side="right")
        
        # Volume control
        volume_frame = ttk.LabelFrame(left_panel, text="Volume", padding=10)
        volume_frame.pack(fill="x", pady=(0, 10))
        
        volume_scale = ttk.Scale(volume_frame, from_=0, to=100, orient="horizontal",
                               command=lambda v: self.player.set_volume(float(v)/100))
        volume_scale.set(70)
        volume_scale.pack(fill="x")
        
        # Right panel (results)
        right_panel = ttk.Frame(main_frame)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.grid_rowconfigure(2, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)
        
        # Results header
        results_header = ttk.Frame(right_panel)
        results_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(results_header, text="Similar Patterns", style="Title.TLabel").pack(side="left")
        
        # Selected pattern section
        selected_frame = ttk.LabelFrame(right_panel, text="Selected Pattern", padding=10)
        selected_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        
        # Selected pattern info
        self.selected_file_var = tk.StringVar(value="No pattern selected")
        ttk.Label(selected_frame, textvariable=self.selected_file_var, wraplength=600).pack(fill="x", pady=(0, 10))
        
        # Selected pattern piano roll
        selected_piano_roll_frame = ttk.Frame(selected_frame)
        selected_piano_roll_frame.pack(fill="x", pady=(0, 10))
        self.selected_piano_roll = PianoRollVisualizer(selected_piano_roll_frame)
        
        # Selected pattern playback controls
        selected_controls = ttk.Frame(selected_frame)
        selected_controls.pack(fill="x")
        ttk.Button(selected_controls, text="▶", width=3, command=lambda: self._play_selected(None)).pack(side="left", padx=2)
        ttk.Button(selected_controls, text="⏸", width=3, command=self.player.pause).pack(side="left", padx=2)
        ttk.Button(selected_controls, text="⏹", width=3, command=self.player.stop).pack(side="left", padx=2)
        
        # Results list
        results_frame = ttk.Frame(right_panel)
        results_frame.grid(row=2, column=0, sticky="nsew")
        results_frame.grid_rowconfigure(0, weight=1)
        results_frame.grid_columnconfigure(0, weight=1)
        
        # Results tree
        self.results_tree = ttk.Treeview(results_frame, columns=('similarity', 'path'), show='headings')
        self.results_tree.heading('similarity', text='Similarity')
        self.results_tree.heading('path', text='File Path')
        self.results_tree.column('similarity', width=100)
        self.results_tree.column('path', width=500)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        self.results_tree.bind('<<TreeviewSelect>>', self._on_result_selected)
        
        # Scrollbars
        y_scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_tree.yview)
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        x_scrollbar = ttk.Scrollbar(results_frame, orient="horizontal", command=self.results_tree.xview)
        x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.results_tree.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)
        
        # Status bar
        status_frame = ttk.Frame(right_panel)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side="left")
        
        self.progress = ttk.Progressbar(status_frame, mode='determinate', length=200)
        self.progress.pack(side="right", padx=(10, 0))

    def _handle_playback_error(self, error_msg: str):
        """Handle MIDI playback errors"""
        self.status_var.set(f"Playback error: {error_msg}")
        messagebox.showerror("Playback Error", error_msg)

    def _update_weight(self, feature: str, value: str):
        try:
            self.weights[feature] = float(value)
            if self.current_file_var.get() != "No file loaded":
                self._run_search(self.player.current_file)
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
                self.status_var.set("Analyzing MIDI file...")
        
                # Update input piano roll
                self.input_piano_roll.update(path)
                
                # Run search
                self._run_search(path)
                
                # Start playback with correct start time
                start_time = self.input_piano_roll.get_start_time()
                self.player.play(path, start_time)
        except Exception as e:
            self.logger.error(f"Error loading MIDI file: {str(e)}")
            messagebox.showerror("Error", f"Failed to load MIDI file: {str(e)}")

    def _play_current(self):
        try:
            if not self.player.is_playing and self.player.current_file:
                self.player.resume()
            elif not self.player.current_file and self.results_tree.selection():
                self._play_selected(None)
            else:
                # Get start time from piano roll
                start_time = self.input_piano_roll.get_start_time()
                self.player.play(self.player.current_file, start_time)
        except Exception as e:
            self.logger.error(f"Error playing file: {str(e)}")
            messagebox.showerror("Error", f"Failed to play file: {str(e)}")

    def _on_result_selected(self, event):
        """Handle result selection"""
        try:
            selection = self.results_tree.selection()
            if selection:
                item = self.results_tree.item(selection[0])
                file_path = item['values'][1]
                similarity = item['values'][0]
                
                # Update selected file info
                self.selected_file_var.set(f"Selected: {os.path.basename(file_path)} (Similarity: {similarity})")
                
                # Update piano roll
                self.selected_piano_roll.update(file_path)
        except Exception as e:
            self.logger.error(f"Error selecting result: {str(e)}")
            messagebox.showerror("Error", f"Failed to select result: {str(e)}")

    def _play_selected(self, event):
        try:
            selection = self.results_tree.selection()
            if selection:
                item = self.results_tree.item(selection[0])
                file_path = item['values'][1]
                # Get start time from selected piano roll
                start_time = self.selected_piano_roll.get_start_time()
                self.player.play(file_path, start_time)
        except Exception as e:
            self.logger.error(f"Error playing selected file: {str(e)}")
            messagebox.showerror("Error", f"Failed to play selected file: {str(e)}")

    def _run_search(self, query_path: str):
        try:
            self.progress['value'] = 0
            self.status_var.set("Searching for similar patterns...")
            self.root.update_idletasks()
            
            results = self.db.find_similar(query_path, self.weights)
            self._display_results(results)
            
            self.progress['value'] = 100
            self.status_var.set("Search complete")
            self.root.update_idletasks()
        except Exception as e:
            self.logger.error(f"Search error: {str(e)}")
            messagebox.showerror("Search Error", str(e))
            self.progress['value'] = 0
            self.status_var.set("Search failed")

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
