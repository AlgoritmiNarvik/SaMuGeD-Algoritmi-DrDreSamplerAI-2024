import os
import platform
import pygame
import pygame.midi
from typing import Optional, Callable
import logging
import pretty_midi
import tempfile
from enum import Enum

class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"

class MIDIPlayer:
    def __init__(self):
        try:
            # Initialize pygame with better audio settings
            pygame.mixer.pre_init(44100, -16, 2, 2048)
            pygame.mixer.init()
            pygame.init()
            pygame.mixer.set_num_channels(32)  # Support more simultaneous sounds
            
            self.current_file = None
            self.temp_file = None  # For storing modified MIDI
            self.state = PlaybackState.STOPPED
            self.on_playback_error: Optional[Callable[[str], None]] = None
            self.on_state_change: Optional[Callable[[PlaybackState], None]] = None
            self.volume = 0.7  # Default volume
            self.loop_enabled = True  # Enable looping by default
            self._setup_logging()
            
            # Set up event handler for end of music
            pygame.mixer.music.set_endevent(pygame.USEREVENT)
            pygame.time.set_timer(pygame.USEREVENT, 100)  # Check every 100ms
            
            # Test MIDI system
            if not pygame.mixer.get_init():
                raise RuntimeError("Failed to initialize audio system")
                
        except Exception as e:
            logging.error(f"Failed to initialize MIDI player: {str(e)}")
            raise

    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            filename='midi_player.log',
            level=logging.DEBUG,  # More detailed logging
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def set_error_callback(self, callback: Callable[[str], None]):
        """Set callback for playback errors"""
        self.on_playback_error = callback

    def set_state_callback(self, callback: Callable[[PlaybackState], None]):
        """Set callback for state changes"""
        self.on_state_change = callback

    def _update_state(self, new_state: PlaybackState):
        """Update playback state and notify listeners"""
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)
        self.logger.debug(f"Playback state changed to: {new_state.value}")

    def _create_trimmed_midi(self, midi_file: str, start_time: float = None) -> Optional[str]:
        """Create a new MIDI file with empty bars removed
        
        Args:
            midi_file: Original MIDI file path
            start_time: Start time to use (if None, will detect automatically)
            
        Returns:
            Path to the temporary trimmed MIDI file
        """
        try:
            # Load MIDI
            midi_data = pretty_midi.PrettyMIDI(midi_file)
            
            # Find start time if not provided
            if start_time is None:
                start_time = float('inf')
                for instrument in midi_data.instruments:
                    if not instrument.is_drum and instrument.notes:
                        first_note = min(instrument.notes, key=lambda x: x.start)
                        start_time = min(start_time, first_note.start)
                if start_time == float('inf'):
                    start_time = 0
            
            # Shift all notes to remove empty space
            for instrument in midi_data.instruments:
                for note in instrument.notes:
                    note.start -= start_time
                    note.end -= start_time
            
            # Save to temporary file
            if self.temp_file:
                try:
                    os.remove(self.temp_file)
                except:
                    pass
                    
            fd, temp_path = tempfile.mkstemp(suffix='.mid')
            os.close(fd)
            midi_data.write(temp_path)
            self.temp_file = temp_path
            
            return temp_path
            
        except Exception as e:
            self.logger.error(f"Error creating trimmed MIDI: {str(e)}")
            return None

    def play(self, midi_file: str, start_time: float = None) -> bool:
        """Play a MIDI file
        
        Args:
            midi_file: Path to the MIDI file
            start_time: Start time to begin playback from (if None, will detect automatically)
        """
        try:
            # Always stop current playback first
            self.stop()
            self.logger.debug(f"Platform: {platform.system()}, mixer init: {pygame.mixer.get_init()}, volume: {self.volume}")
                
            if not os.path.exists(midi_file):
                error_msg = f"MIDI file not found: {midi_file}"
                self.logger.error(error_msg)
                if self.on_playback_error:
                    self.on_playback_error(error_msg)
                return False

            # Create trimmed version
            trimmed_file = self._create_trimmed_midi(midi_file, start_time)
            if not trimmed_file:
                error_msg = "Failed to process MIDI file"
                self.logger.error(error_msg)
                if self.on_playback_error:
                    self.on_playback_error(error_msg)
                return False

            # Load and play the trimmed file
            pygame.mixer.music.load(trimmed_file)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play(-1 if self.loop_enabled else 0)  # -1 for infinite loop
            
            # Verify playback started
            if pygame.mixer.music.get_busy():
                self.current_file = midi_file
                self._update_state(PlaybackState.PLAYING)
                self.logger.info(f"Started playing: {midi_file} (loop: {self.loop_enabled})")
                return True
            else:
                error_msg = "Failed to start playback"
                self.logger.error(error_msg)
                if self.on_playback_error:
                    self.on_playback_error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error playing MIDI file {midi_file}: {str(e)}"
            self.logger.error(error_msg)
            if self.on_playback_error:
                self.on_playback_error(error_msg)
            return False

    def pause(self):
        """Pause playback"""
        if self.state == PlaybackState.PLAYING:
            pygame.mixer.music.pause()
            self._update_state(PlaybackState.PAUSED)
            self.logger.debug("Playback paused")

    def resume(self):
        """Resume playback"""
        if self.state == PlaybackState.PAUSED and self.current_file:
            pygame.mixer.music.unpause()
            self._update_state(PlaybackState.PLAYING)
            self.logger.debug("Playback resumed")

    def stop(self):
        """Stop playback"""
        if self.state != PlaybackState.STOPPED:
            pygame.mixer.music.stop()
            self.current_file = None
            self._update_state(PlaybackState.STOPPED)
            self.logger.debug("Playback stopped")

    def set_volume(self, volume: float):
        """Set playback volume (0.0 to 1.0)"""
        self.volume = max(0.0, min(1.0, volume))
        pygame.mixer.music.set_volume(self.volume)
        self.logger.debug(f"Volume set to: {self.volume}")

    def get_position(self) -> float:
        """Get current playback position in seconds"""
        if self.state == PlaybackState.PLAYING:
            return pygame.mixer.music.get_pos() / 1000.0
        return 0.0

    def is_busy(self) -> bool:
        """Check if currently playing"""
        return self.state == PlaybackState.PLAYING

    def get_state(self) -> PlaybackState:
        """Get current playback state"""
        return self.state

    def cleanup(self):
        """Clean up resources"""
        try:
            self.stop()
            pygame.mixer.quit()
            pygame.midi.quit()
            
            # Clean up temporary file
            if self.temp_file and os.path.exists(self.temp_file):
                try:
                    os.remove(self.temp_file)
                except:
                    pass
                    
            self.logger.info("MIDI player cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}") 
        