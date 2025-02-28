import os
import sys
import platform

def setup_windows_environment():
    """Set up environment variables for Windows compatibility"""
    # Get the base directory (either the PyInstaller temp directory or the script directory)
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        base_dir = sys._MEIPASS
    else:
        # Running as script
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Set environment variable for FluidSynth to find the soundfont
    os.environ['FLUID_SOUNDFONT'] = os.path.join(base_dir, 'soundfonts', 'FluidR3_GM.sf2')
    
    # Return paths that might need to be adjusted in the application
    return {
        'base_dir': base_dir,
        'soundfont_path': os.path.join(base_dir, 'soundfonts', 'FluidR3_GM.sf2'),
        'dataset_path': os.path.join(base_dir, 'datasets', 'Lakh_MIDI_Clean_Patterns_v1'),
        'cache_dir': os.path.join(base_dir, 'cache')
    }

def is_windows():
    """Check if running on Windows"""
    return platform.system() == 'Windows' 