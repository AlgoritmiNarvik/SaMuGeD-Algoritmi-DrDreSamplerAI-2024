import os
import pygame
import pygame.midi
from typing import Optional, Callable
import logging
import pretty_midi
import tempfile

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
            self.is_playing = False
            self.on_playback_error: Optional[Callable[[str], None]] = None
            self.volume = 0.7  # Default volume
            self._setup_logging()
            
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
            if self.is_playing:
                self.stop()
                
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
            pygame.mixer.music.play()
            
            # Verify playback started
            if pygame.mixer.music.get_busy():
                self.current_file = midi_file
                self.is_playing = True
                self.logger.info(f"Started playing: {midi_file}")
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
        if self.is_playing:
            pygame.mixer.music.pause()
            self.is_playing = False
            self.logger.debug("Playback paused")

    def resume(self):
        """Resume playback"""
        if not self.is_playing and self.current_file:
            pygame.mixer.music.unpause()
            self.is_playing = True
            self.logger.debug("Playback resumed")

    def stop(self):
        """Stop playback"""
        if self.current_file:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.current_file = None
            self.logger.debug("Playback stopped")

    def set_volume(self, volume: float):
        """Set playback volume (0.0 to 1.0)"""
        self.volume = max(0.0, min(1.0, volume))
        pygame.mixer.music.set_volume(self.volume)
        self.logger.debug(f"Volume set to: {self.volume}")

    def get_position(self) -> float:
        """Get current playback position in seconds"""
        if self.is_playing:
            return pygame.mixer.music.get_pos() / 1000.0
        return 0.0

    def is_busy(self) -> bool:
        """Check if currently playing"""
        return pygame.mixer.music.get_busy()

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
        