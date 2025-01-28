import numpy as np
import pretty_midi
from typing import Optional, List, Tuple
import tkinter as tk
from PIL import Image, ImageTk

class PianoRollVisualizer:
    def __init__(self, frame: tk.Widget, height: int = 120):
        """Initialize piano roll visualizer
        
        Args:
            frame: Tkinter widget to embed the piano roll in
            height: Height of the piano roll in pixels
        """
        self.frame = frame
        self.height = height
        self.width = 600  # Default width
        self.current_midi: Optional[pretty_midi.PrettyMIDI] = None
        self.start_time = 0  # Start time after skipping empty bars
        
        # Colors
        self.bg_color = '#2b2b2b'
        self.grid_color = '#404040'
        self.note_color = '#4a9eff'
        self.text_color = '#ffffff'
        
        self._setup_canvas()
        
    def _setup_canvas(self):
        """Setup the Tkinter canvas"""
        # Create canvas
        self.canvas = tk.Canvas(
            self.frame,
            height=self.height,
            bg=self.bg_color,
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.X, expand=True)
        
        # Bind resize event
        self.canvas.bind('<Configure>', self._on_resize)
        
        # Create note name labels
        self._create_note_labels()
        
    def _find_first_note_time(self) -> float:
        """Find the start time of the first note"""
        if not self.current_midi:
            return 0.0
            
        first_note_time = float('inf')
        for instrument in self.current_midi.instruments:
            if not instrument.is_drum and instrument.notes:
                first_note = min(instrument.notes, key=lambda x: x.start)
                first_note_time = min(first_note_time, first_note.start)
        
        return first_note_time if first_note_time != float('inf') else 0.0

    def _find_last_note_time(self) -> float:
        """Find the end time of the last note"""
        if not self.current_midi:
            return 0.0
            
        last_note_time = 0.0
        for instrument in self.current_midi.instruments:
            if not instrument.is_drum and instrument.notes:
                last_note = max(instrument.notes, key=lambda x: x.end)
                last_note_time = max(last_note_time, last_note.end)
        
        return last_note_time
        
    def _create_note_labels(self):
        """Create piano key labels"""
        note_height = (self.height - 20) / 88  # 88 piano keys
        for i, note in enumerate(['C', 'D', 'E', 'F', 'G', 'A', 'B']):
            y = self.height - (i * note_height * 12) - 15
            self.canvas.create_text(
                20, y,
                text=note,
                fill=self.text_color,
                font=('Helvetica', 8)
            )
    
    def _on_resize(self, event):
        """Handle canvas resize"""
        self.width = event.width
        if self.current_midi:
            self._redraw()
    
    def _get_note_coordinates(self, note: pretty_midi.Note, total_time: float, start_time: float) -> Tuple[int, int, int, int]:
        """Convert note to canvas coordinates"""
        # Adjust note times relative to start_time
        note_start = note.start - start_time
        note_end = note.end - start_time
        
        # Time to x coordinate
        x_start = int((note_start / total_time) * (self.width - 40)) + 40
        x_end = int((note_end / total_time) * (self.width - 40)) + 40
        
        # Pitch to y coordinate (flip y-axis since canvas coordinates go down)
        note_height = (self.height - 20) / 88
        y_top = self.height - ((note.pitch - 21) * note_height) - 10
        y_bottom = y_top + note_height
        
        return x_start, y_top, x_end, y_bottom
    
    def _draw_grid(self, total_time: float, start_time: float):
        """Draw time grid"""
        # Vertical time lines
        num_lines = 10
        spacing = (self.width - 40) / num_lines
        for i in range(num_lines + 1):
            x = i * spacing + 40
            self.canvas.create_line(
                x, 0, x, self.height,
                fill=self.grid_color,
                width=1
            )
            # Time label (add start_time to show actual time)
            time = (i * total_time / num_lines) + start_time
            self.canvas.create_text(
                x, self.height - 5,
                text=f"{time:.1f}s",
                fill=self.text_color,
                font=('Helvetica', 8)
            )
        
        # Horizontal pitch lines
        note_height = (self.height - 20) / 88
        for i in range(0, 88, 12):  # Draw line for each octave
            y = self.height - (i * note_height) - 10
            self.canvas.create_line(
                40, y, self.width, y,
                fill=self.grid_color,
                width=1
            )
    
    def _redraw(self):
        """Redraw the entire piano roll"""
        self.canvas.delete('all')
        
        if not self.current_midi:
            return
            
        # Find start and end times
        start_time = self._find_first_note_time()
        end_time = self._find_last_note_time()
        total_time = end_time - start_time
        
        if total_time <= 0:
            return
            
        # Store start time for playback sync
        self.start_time = start_time
            
        # Draw grid
        self._draw_grid(total_time, start_time)
        
        # Draw notes
        for instrument in self.current_midi.instruments:
            if not instrument.is_drum:
                for note in instrument.notes:
                    x1, y1, x2, y2 = self._get_note_coordinates(note, total_time, start_time)
                    # Draw note rectangle
                    self.canvas.create_rectangle(
                        x1, y1, x2, y2,
                        fill=self.note_color,
                        outline='#2b2b2b',
                        width=1
                    )
        
        # Recreate labels
        self._create_note_labels()
            
    def update(self, midi_file: str):
        """Update the piano roll visualization with a new MIDI file
        
        Args:
            midi_file: Path to the MIDI file to visualize
        """
        try:
            self.current_midi = pretty_midi.PrettyMIDI(midi_file)
            self._redraw()
        except Exception as e:
            print(f"Error visualizing MIDI: {str(e)}")
            
    def clear(self):
        """Clear the piano roll visualization"""
        self.canvas.delete('all')
        self._create_note_labels()
        self.current_midi = None
        self.start_time = 0
        
    def get_start_time(self) -> float:
        """Get the start time of the first note (for playback sync)"""
        return self.start_time 