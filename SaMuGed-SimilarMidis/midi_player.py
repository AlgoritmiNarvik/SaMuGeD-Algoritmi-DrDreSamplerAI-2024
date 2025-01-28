import os
import pygame
import pygame.midi
from typing import Optional
import logging

class MIDIPlayer:
    def __init__(self):
        try:
            pygame.mixer.pre_init(44100, -16, 2, 2048)
            pygame.mixer.init()
            pygame.init()
            self.current_file = None
            self.is_playing = False
            self._setup_logging()
        except Exception as e:
            logging.error(f"Failed to initialize MIDI player: {str(e)}")
            raise

    def _setup_logging(self):
        logging.basicConfig(
            filename='midi_player.log',
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

    def play(self, midi_file: str) -> bool:
        """Play a MIDI file"""
        try:
            if self.is_playing:
                self.stop()
                
            if not os.path.exists(midi_file):
                logging.error(f"MIDI file not found: {midi_file}")
                return False

            pygame.mixer.music.load(midi_file)
            pygame.mixer.music.play()
            self.current_file = midi_file
            self.is_playing = True
            return True
        except Exception as e:
            logging.error(f"Error playing MIDI file {midi_file}: {str(e)}")
            return False

    def pause(self):
        """Pause playback"""
        if self.is_playing:
            pygame.mixer.music.pause()
            self.is_playing = False

    def resume(self):
        """Resume playback"""
        if not self.is_playing and self.current_file:
            pygame.mixer.music.unpause()
            self.is_playing = True

    def stop(self):
        """Stop playback"""
        if self.current_file:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.current_file = None

    def set_volume(self, volume: float):
        """Set playback volume (0.0 to 1.0)"""
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))

    def get_position(self) -> float:
        """Get current playback position in seconds"""
        if self.is_playing:
            return pygame.mixer.music.get_pos() / 1000.0
        return 0.0

    def cleanup(self):
        """Clean up resources"""
        self.stop()
        pygame.midi.quit() 
        