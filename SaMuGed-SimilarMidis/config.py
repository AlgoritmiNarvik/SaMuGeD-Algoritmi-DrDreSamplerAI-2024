import os
import sys

# Try to import the Windows helper, but don't fail if it's not available
try:
    from windows_helper import setup_windows_environment, is_windows
    if is_windows() or getattr(sys, 'frozen', False):
        paths = setup_windows_environment()
        DATASET_PATH = paths['dataset_path']
        SOUNDFONT_PATH = paths['soundfont_path']
        CACHE_DIR = paths['cache_dir']
    else:
        DATASET_PATH = "datasets/Lakh_MIDI_Clean_Patterns_v1"
        SOUNDFONT_PATH = os.path.join(os.path.dirname(__file__), "soundfonts", "FluidR3_GM.sf2")
        CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
except ImportError:
    # Fallback to default paths
    DATASET_PATH = "datasets/Lakh_MIDI_Clean_Patterns_v1"
    SOUNDFONT_PATH = os.path.join(os.path.dirname(__file__), "soundfonts", "FluidR3_GM.sf2")
    CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')

DEFAULT_FEATURE_WEIGHTS = {
    'pitch_mean': 0.7,
    'pitch_std': 2.0,
    'duration_mean': 1.0,
    'duration_std': 1.0,
    'ioi_mean': 1.5,
    'ioi_std': 2.0,
    'syncopation_ratio': 2.0,
    'tempo': 0.5,
    'interval_std': 1.8,
    'contour_slope': 1.2
}

MAX_RESULTS = 100
