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
        
        # Colors - Improved visibility
        self.bg_color = '#2b2b2b'      # Dark but not too dark background
        self.grid_color = '#404040'     # Visible grid
        self.note_color = '#00ff00'     # Bright green for high visibility
        self.note_border = '#00cc00'    # Slightly darker green for borders
        self.text_color = '#ffffff'     # White text
        self.octave_line_color = '#505050'  # More visible octave lines
        
        # Note appearance
        self.note_outline_width = 2     # Thicker outline
        self.note_min_width = 4         # Wider minimum width
        
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
        try:
            min_pitch, max_pitch = self._get_pitch_range()
            pitch_range = max_pitch - min_pitch + 1
            note_height = (self.height - 20) / pitch_range
            
            # Create labels for white keys
            for pitch in range(min_pitch, max_pitch + 1):
                if pitch % 12 in [0, 2, 4, 5, 7, 9, 11]:  # White keys
                    y = self.height - ((pitch - min_pitch) * note_height) - 10
                    note_name = ['C', 'D', 'E', 'F', 'G', 'A', 'B'][pitch % 12 // 2]
                    octave = pitch // 12 - 1
                    if pitch % 12 == 0:  # Show octave number for C notes
                        note_name = f"{note_name}{octave}"
                    self.canvas.create_text(
                        20, y,
                        text=note_name,
                        fill=self.text_color,
                        font=('Helvetica', 9, 'bold')
                    )
        except Exception as e:
            print(f"Warning: Could not create note labels: {str(e)}")

    def _on_resize(self, event):
        """Handle canvas resize"""
        self.width = event.width
        if self.current_midi:
            self._redraw()
    
    def _get_pitch_range(self) -> Tuple[int, int]:
        """Get the pitch range of the current MIDI file"""
        if not self.current_midi:
            return (21, 109)  # Default piano range
            
        min_pitch = float('inf')
        max_pitch = float('-inf')
        for instrument in self.current_midi.instruments:
            if not instrument.is_drum and instrument.notes:
                notes = instrument.notes
                min_pitch = min(min_pitch, min(note.pitch for note in notes))
                max_pitch = max(max_pitch, max(note.pitch for note in notes))
        
        if min_pitch == float('inf'):
            return (21, 109)
            
        # Add padding to the range
        min_pitch = max(0, min_pitch - 2)
        max_pitch = min(127, max_pitch + 2)
        return (int(min_pitch), int(max_pitch))

    def _get_note_coordinates(self, note: pretty_midi.Note, total_time: float, start_time: float) -> Tuple[int, int, int, int]:
        """Convert note to canvas coordinates with pitch normalization"""
        # Adjust note times relative to start_time
        note_start = note.start - start_time
        note_end = note.end - start_time
        
        # Time to x coordinate
        x_start = int((note_start / total_time) * (self.width - 40)) + 40
        x_end = int((note_end / total_time) * (self.width - 40)) + 40
        
        # Ensure minimum note width for visibility
        if x_end - x_start < self.note_min_width:
            x_end = x_start + self.note_min_width
        
        # Get pitch range for normalization
        min_pitch, max_pitch = self._get_pitch_range()
        pitch_range = max_pitch - min_pitch + 1
        
        # Normalize pitch to available height
        note_height = (self.height - 20) / pitch_range
        normalized_pitch = note.pitch - min_pitch
        y_top = self.height - (normalized_pitch * note_height) - 10
        y_bottom = y_top + note_height
        
        return x_start, y_top, x_end, y_bottom
    
    def _draw_grid(self, total_time: float, start_time: float):
        """Draw time grid with visible lines"""
        try:
            min_pitch, max_pitch = self._get_pitch_range()
            pitch_range = max_pitch - min_pitch + 1
            note_height = (self.height - 20) / pitch_range
            
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
                # Time label
                time = (i * total_time / num_lines) + start_time
                self.canvas.create_text(
                    x, self.height - 5,
                    text=f"{time:.1f}s",
                    fill=self.text_color,
                    font=('Helvetica', 9, 'bold')
                )
            
            # Horizontal pitch lines
            for pitch in range(min_pitch, max_pitch + 1):
                y = self.height - ((pitch - min_pitch) * note_height) - 10
                
                # Draw octave lines
                if pitch % 12 == 0:
                    self.canvas.create_line(
                        40, y, self.width, y,
                        fill=self.octave_line_color,
                        width=2
                    )
                
                # Draw subtle lines for other white keys
                elif pitch % 12 in [2, 4, 5, 7, 9, 11]:
                    self.canvas.create_line(
                        40, y, self.width, y,
                        fill=self.grid_color,
                        width=1
                    )
        except Exception as e:
            print(f"Warning: Could not draw grid: {str(e)}")

    def _redraw(self):
        """Redraw the entire piano roll"""
        try:
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
                
            # Draw grid first (behind notes)
            self._draw_grid(total_time, start_time)
            
            # Draw notes with high visibility
            for instrument in self.current_midi.instruments:
                if not instrument.is_drum and instrument.notes:
                    for note in instrument.notes:
                        try:
                            x1, y1, x2, y2 = self._get_note_coordinates(note, total_time, start_time)
                            # Draw note rectangle with thicker outline
                            self.canvas.create_rectangle(
                                x1, y1, x2, y2,
                                fill=self.note_color,
                                outline=self.note_border,
                                width=self.note_outline_width
                            )
                            
                            # Add a highlight effect
                            highlight_height = (y2 - y1) * 0.3
                            self.canvas.create_rectangle(
                                x1, y1, x2, y1 + highlight_height,
                                fill='#80ff80',  # Lighter green for highlight
                                outline='',  # No outline for highlight
                            )
                        except Exception as e:
                            print(f"Warning: Could not draw note: {str(e)}")
                            continue
            
            # Create labels
            self._create_note_labels()
            
        except Exception as e:
            print(f"Error in piano roll redraw: {str(e)}")
            # Try to recover by clearing the canvas
            self.canvas.delete('all')
            self._create_note_labels()

    def update(self, midi_file: str):
        """Update the piano roll visualization with a new MIDI file
        
        Args:
            midi_file: Path to the MIDI file to visualize
        """
        try:
            self.current_midi = pretty_midi.PrettyMIDI(midi_file)
            if not any(len(i.notes) > 0 for i in self.current_midi.instruments if not i.is_drum):
                print(f"Warning: No notes found in MIDI file: {midi_file}")
                self.clear()
                return
            self._redraw()
        except Exception as e:
            print(f"Error visualizing MIDI: {str(e)}")
            self.clear()  # Reset on error
            
    def clear(self):
        """Clear the piano roll visualization"""
        self.canvas.delete('all')
        self._create_note_labels()
        self.current_midi = None
        self.start_time = 0
        
    def get_start_time(self) -> float:
        """Get the start time of the first note (for playback sync)"""
        return self.start_time 