import os
import platform
import tempfile
import threading
import logging
import pretty_midi
import fluidsynth
import time
from enum import Enum
from config import SOUNDFONT_PATH


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class FluidSynthPlayer:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.state = PlaybackState.STOPPED
        self.on_state_change = None
        self.on_playback_error = None
        self.volume = 0.7
        self.current_file = None
        self.play_thread = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.repeat = True  # Add repeat flag
        
        # Set up soundfont path
        self.soundfont_path = SOUNDFONT_PATH
        if not os.path.exists(self.soundfont_path):
            self.logger.error(f"Soundfont not found at {self.soundfont_path}")
            raise FileNotFoundError(f"Soundfont not found at {self.soundfont_path}")

        try:
            # Initialize FluidSynth with better audio settings
            self.synth = fluidsynth.Synth(gain=0.7)  # Set initial gain
            
            # Configure audio settings based on platform
            if platform.system() == 'Darwin':  # macOS
                self.synth.start(driver='coreaudio')
            elif platform.system() == 'Windows':
                self.synth.start(driver='dsound', period_size=64, periods=16)
            else:  # Linux
                self.synth.start(driver='alsa', period_size=64, periods=16)
            
            # Load and configure soundfont
            self.sfid = self.synth.sfload(self.soundfont_path)
            if self.sfid == -1:
                raise RuntimeError(f"Failed to load soundfont: {self.soundfont_path}")
            
            self.synth.program_select(0, self.sfid, 0, 0)
            self.synth.gain = self.volume  # Set initial volume
            
        except Exception as e:
            self.logger.error(f"FluidSynth initialization failed: {str(e)}")
            raise RuntimeError("FluidSynth initialization failed") from e

    def _create_trimmed_midi(self, midi_file, start_time=None):
        """
        Create a temporary MIDI file with empty bars removed by shifting notes based on the first note start time.
        """
        try:
            midi_data = pretty_midi.PrettyMIDI(midi_file)
            if start_time is None:
                start_time = float('inf')
                for instrument in midi_data.instruments:
                    if not instrument.is_drum and instrument.notes:
                        first_note = min(instrument.notes, key=lambda x: x.start)
                        start_time = min(start_time, first_note.start)
                if start_time == float('inf'):
                    start_time = 0
            
            for instrument in midi_data.instruments:
                for note in instrument.notes:
                    note.start -= start_time
                    note.end -= start_time
            fd, temp_path = tempfile.mkstemp(suffix='.mid')
            os.close(fd)
            midi_data.write(temp_path)
            return temp_path
        except Exception as e:
            self.logger.error("Error creating trimmed MIDI: " + str(e))
            return None

    def _play_async(self, midi_file):
        try:
            # Create trimmed version without silence
            temp_midi = self._create_trimmed_midi(midi_file)
            if not temp_midi:
                raise ValueError("Failed to process MIDI file")

            # Load and parse trimmed MIDI file
            midi_data = pretty_midi.PrettyMIDI(temp_midi)
            self.logger.info(f"Starting FluidSynth playback for: {midi_file}")
            
            while not self.stop_flag.is_set():  # Main repeat loop
                self._update_state(PlaybackState.PLAYING)
                
                # Rest of playback logic remains the same
                self.synth.gain = self.volume
                start_time = time.time()
                current_notes = {}
                
                for instrument in midi_data.instruments:
                    if not instrument.is_drum:
                        for note in instrument.notes:
                            while not self.stop_flag.is_set():
                                current_time = time.time() - start_time
                                
                                # Handle note offs
                                notes_to_remove = []
                                for note_key, note_end in current_notes.items():
                                    if current_time >= note_end:
                                        self.synth.noteoff(0, note_key)
                                        notes_to_remove.append(note_key)
                                for note_key in notes_to_remove:
                                    del current_notes[note_key]
                                
                                # Handle note on
                                if current_time >= note.start:
                                    self.synth.noteon(0, note.pitch, int(note.velocity))
                                    current_notes[note.pitch] = note.end
                                    break
                                
                                time.sleep(0.001)
                            
                            if self.stop_flag.is_set():
                                break
                    
                    if self.stop_flag.is_set():
                        break
                
                # Wait for final notes to finish
                while not self.stop_flag.is_set() and current_notes:
                    current_time = time.time() - start_time
                    notes_to_remove = []
                    for note_key, note_end in current_notes.items():
                        if current_time >= note_end:
                            self.synth.noteoff(0, note_key)
                            notes_to_remove.append(note_key)
                    for note_key in notes_to_remove:
                        del current_notes[note_key]
                    time.sleep(0.001)
                
                # Break the repeat loop if stopped or repeat is disabled
                if self.stop_flag.is_set() or not self.repeat:
                    break
                
                # Small pause between repeats
                time.sleep(0.5)

            if not self.stop_flag.is_set():
                self._update_state(PlaybackState.STOPPED)

        except Exception as e:
            self.logger.error(f"Playback failed: {str(e)}")
            if self.on_playback_error:
                self.on_playback_error(str(e))
        finally:
            # Ensure all notes are off
            for i in range(128):
                self.synth.noteoff(0, i)
            self.stop_flag.clear()
            # Clean up temporary file
            if temp_midi:
                try:
                    os.remove(temp_midi)
                except:
                    pass

    def play(self, midi_file, start_time=None):
        """Play a MIDI file from the given start time"""
        try:
            self.stop()
            self.current_file = midi_file
            self.stop_flag.clear()
            self.play_thread = threading.Thread(target=self._play_async, args=(midi_file,))
            self.play_thread.start()
            return True
        except Exception as e:
            error_msg = f"Error playing MIDI file {midi_file}: {str(e)}"
            self.logger.error(error_msg)
            if self.on_playback_error:
                self.on_playback_error(error_msg)
            return False

    def stop(self):
        if self.state != PlaybackState.STOPPED:
            self.stop_flag.set()
            if self.play_thread and self.play_thread.is_alive():
                self.play_thread.join(timeout=0.5)
            # Ensure all notes are off
            for i in range(128):
                self.synth.noteoff(0, i)
            self._update_state(PlaybackState.STOPPED)
            self.logger.debug("FluidSynth playback stopped")

    def set_volume(self, volume):
        """Set volume between 0.0 and 1.0"""
        self.volume = max(0.0, min(1.0, volume))
        self.synth.gain = self.volume
        self.logger.debug(f"Volume set to: {self.volume}")

    def cleanup(self):
        try:
            self.stop()
            if self.sfid:
                self.synth.sfunload(self.sfid)
            self.synth.delete()
            self.logger.info("FluidSynth player cleaned up")
        except Exception as e:
            self.logger.error(f"Error during FluidSynth cleanup: {str(e)}")

    def _update_state(self, new_state):
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)
        self.logger.debug(f"Playback state changed to: {new_state.value}")

    def set_error_callback(self, callback):
        self.on_playback_error = callback

    def set_state_callback(self, callback):
        self.on_state_change = callback

    def get_position(self):
        # Position tracking not supported in command-line mode
        return 0.0

    def is_busy(self):
        return self.state == PlaybackState.PLAYING

    def get_state(self):
        return self.state

    def _handle_sequencer_event(self, time, event, seq, data):
        """Required sequencer callback (even if unused)"""
        pass  # We don't need to handle events but must provide the callback 

    def pause(self):
        """Pause playback if playing"""
        if self.state == PlaybackState.PLAYING:
            self._update_state(PlaybackState.PAUSED)
            self.stop_flag.set()
            if self.play_thread and self.play_thread.is_alive():
                self.play_thread.join(timeout=0.5)
            # Don't clear notes, just stop processing new ones
            self.logger.debug("FluidSynth playback paused")

    def resume(self):
        """Resume playback if paused"""
        if self.state == PlaybackState.PAUSED and self.current_file:
            self.stop_flag.clear()
            self.play_thread = threading.Thread(target=self._play_async, args=(self.current_file,))
            self.play_thread.start()
            self.logger.debug("FluidSynth playback resumed")

    def set_repeat(self, enabled):
        """Enable or disable repeat playback"""
        self.repeat = enabled
        self.logger.debug(f"Repeat playback {'enabled' if enabled else 'disabled'}")
 