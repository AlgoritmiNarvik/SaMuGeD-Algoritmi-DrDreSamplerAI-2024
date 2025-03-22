from flask import Flask, request, render_template, jsonify, send_file, after_this_request
import os
import sys
import logging
import tempfile
import json
import base64
import pretty_midi
from io import BytesIO
import matplotlib.pyplot as plt
import numpy as np
import subprocess
import time

# Add the parent directory to the path so we can import the existing modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import existing functionality
from database import MIDIDatabase
from feature_calculator import FeatureCalculator
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH, MAX_RESULTS

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize the database once at startup
db = MIDIDatabase()
try:
    db.initialize()
except Exception as e:
    logger.error(f"Failed to initialize database: {str(e)}")

# In-memory storage for uploaded files
uploaded_files = {}
# Store piano roll info
piano_roll_cache = {}

# Path to soundfont file
SOUNDFONT_PATH = "/app/soundfonts/FluidR3_GM.sf2"

# Check if soundfont exists
if not os.path.exists(SOUNDFONT_PATH):
    logger.warning(f"Soundfont not found at {SOUNDFONT_PATH}, using system default if available")
    # Try to find a system soundfont
    if os.path.exists("/usr/share/sounds/sf2/FluidR3_GM.sf2"):
        SOUNDFONT_PATH = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
    else:
        logger.error("No soundfont found. Audio playback may not work.")


@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html', feature_weights=DEFAULT_FEATURE_WEIGHTS)


@app.route('/upload', methods=['POST'])
def upload_midi():
    """Handle MIDI file upload"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not file.filename.lower().endswith(('.mid', '.midi')):
            return jsonify({'error': 'Only MIDI files are supported'}), 400

        # Save the file temporarily
        temp_file = tempfile.NamedTemporaryFile(suffix='.mid', delete=False)
        file.save(temp_file.name)
        temp_file.close()
        
        # Store the file path with a unique ID
        file_id = str(hash(file.filename + str(os.path.getsize(temp_file.name))))
        uploaded_files[file_id] = {
            'path': temp_file.name,
            'name': file.filename
        }
        
        # Generate piano roll visualization with metadata
        piano_roll_data = generate_piano_roll_data(temp_file.name)
        piano_roll_cache[file_id] = piano_roll_data
        
        return jsonify({
            'file_id': file_id, 
            'filename': file.filename,
            'piano_roll': piano_roll_data['image']
        })
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/search', methods=['POST'])
def search_similar():
    """Search for similar MIDI patterns"""
    try:
        data = request.json
        file_id = data.get('file_id')
        weights = data.get('weights', DEFAULT_FEATURE_WEIGHTS)
        
        if file_id not in uploaded_files:
            return jsonify({'error': 'File not found'}), 404
            
        # Get the file path
        file_path = uploaded_files[file_id]['path']
        
        # Perform the search
        results = db.find_similar(file_path, weights)
        
        # Format results
        formatted_results = []
        for path, score in sorted(results, key=lambda x: x[1], reverse=True)[:MAX_RESULTS]:
            # Generate piano roll data for each result
            if path not in piano_roll_cache:
                piano_roll_data = generate_piano_roll_data(path)
                piano_roll_cache[path] = piano_roll_data
            else:
                piano_roll_data = piano_roll_cache[path]
            
            formatted_results.append({
                'path': os.path.basename(path),
                'full_path': path,
                'score': f"{score:.2%}",
                'piano_roll': piano_roll_data['image'],
                'duration': piano_roll_data['duration'],
                'min_pitch': piano_roll_data['min_pitch'],
                'max_pitch': piano_roll_data['max_pitch']
            })
            
        # Add query file data to response
        query_data = {
            'file_id': file_id,
            'piano_roll_data': piano_roll_cache[file_id]
        }
            
        return jsonify({
            'results': formatted_results,
            'query': query_data
        })
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify({'error': str(e)}), 500


def create_trimmed_midi(midi_file):
    """Create a trimmed version of a MIDI file by removing silence at the beginning
    
    Args:
        midi_file: Path to the original MIDI file
        
    Returns:
        Path to the temporary trimmed MIDI file or None if error
    """
    try:
        # Load MIDI
        midi_data = pretty_midi.PrettyMIDI(midi_file)
        
        # Find start time automatically
        start_time = float('inf')
        for instrument in midi_data.instruments:
            if not instrument.is_drum and instrument.notes:
                first_note = min(instrument.notes, key=lambda x: x.start)
                start_time = min(start_time, first_note.start)
        
        if start_time == float('inf'):
            start_time = 0
        
        if start_time > 0:
            logger.info(f"Trimming MIDI file, removing {start_time:.2f}s of silence from beginning")
            
            # Shift all notes to remove empty space
            for instrument in midi_data.instruments:
                for note in instrument.notes:
                    note.start -= start_time
                    note.end -= start_time
        
        # Save to temporary file
        fd, temp_path = tempfile.mkstemp(suffix='.mid')
        os.close(fd)
        midi_data.write(temp_path)
        
        return temp_path
        
    except Exception as e:
        logger.error(f"Error creating trimmed MIDI: {str(e)}")
        return None


def midi_to_wav(midi_path):
    """Convert a MIDI file to WAV using FluidSynth
    
    Args:
        midi_path: Path to the MIDI file
        
    Returns:
        Path to the temporary WAV file or None if error
    """
    try:
        # First, create a trimmed MIDI file without silence
        trimmed_midi = create_trimmed_midi(midi_path)
        if not trimmed_midi:
            return None
            
        # Create a temporary WAV file
        fd, wav_path = tempfile.mkstemp(suffix='.wav')
        os.close(fd)
        
        # Use FluidSynth to convert MIDI to WAV
        cmd = [
            'fluidsynth',
            '-ni',
            '-g', '0.7',  # gain (volume)
            '-F', wav_path,
            SOUNDFONT_PATH,
            trimmed_midi
        ]
        
        logger.info(f"Converting MIDI to WAV: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Check if conversion was successful
        if result.returncode != 0:
            logger.error(f"FluidSynth error: {result.stderr}")
            os.remove(trimmed_midi)
            os.remove(wav_path)
            return None
            
        # Clean up the trimmed MIDI file
        os.remove(trimmed_midi)
        
        return wav_path
        
    except Exception as e:
        logger.error(f"MIDI to WAV conversion error: {str(e)}")
        return None


@app.route('/play/<file_id>')
def play_midi(file_id):
    """Serve a MIDI file for playback with silence removed"""
    try:
        logger.info(f"Requested playback for file ID: {file_id}")
        
        if file_id not in uploaded_files:
            logger.error(f"File ID not found in uploaded files: {file_id}")
            return jsonify({'error': 'File not found'}), 404
            
        file_path = uploaded_files[file_id]['path']
        logger.info(f"Found file at path: {file_path}")
        
        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"File does not exist at path: {file_path}")
            return jsonify({'error': 'File not found on disk'}), 404
        
        # Convert MIDI to WAV
        logger.info(f"Converting MIDI to WAV: {file_path}")
        wav_path = midi_to_wav(file_path)
        if not wav_path:
            logger.error(f"Failed to convert MIDI to WAV: {file_path}")
            return jsonify({'error': 'Failed to process MIDI file'}), 500
        
        logger.info(f"Successfully converted to WAV: {wav_path}")
        
        # Set up a callback to remove the temp file after sending
        @after_this_request
        def cleanup(response):
            try:
                os.remove(wav_path)
                logger.info(f"Temporary WAV file removed: {wav_path}")
            except Exception as e:
                logger.error(f"Error removing temp file: {str(e)}")
            return response
            
        return send_file(wav_path, mimetype='audio/wav', conditional=True)
        
    except Exception as e:
        logger.error(f"Playback error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/play_result/<path:file_path>')
def play_result(file_path):
    """Serve a result MIDI file for playback with silence removed"""
    try:
        logger.info(f"Requested playback for result file: {file_path}")
        
        # Try to find file in dataset path
        full_paths = []
        
        # First check if the file exists with given path
        direct_path = os.path.join(DATASET_PATH, file_path)
        if os.path.exists(direct_path):
            full_paths.append(direct_path)
            logger.info(f"Found result file at direct path: {direct_path}")
        
        # If not found directly, search for it by basename
        if not full_paths:
            basename = os.path.basename(file_path)
            logger.info(f"Searching for file with basename: {basename}")
            
            for root, dirs, files in os.walk(DATASET_PATH):
                if basename in files:
                    found_path = os.path.join(root, basename)
                    full_paths.append(found_path)
                    logger.info(f"Found candidate file at: {found_path}")
        
        # If still no matching files, try to find by filename only
        if not full_paths:
            logger.error(f"No files found matching path: {file_path}")
            return jsonify({'error': 'File not found'}), 404
        
        # Use the first found path
        full_path = full_paths[0]
        logger.info(f"Using file at path: {full_path}")
        
        # Convert MIDI to WAV
        logger.info(f"Converting MIDI to WAV: {full_path}")
        wav_path = midi_to_wav(full_path)
        if not wav_path:
            logger.error(f"Failed to convert MIDI to WAV: {full_path}")
            return jsonify({'error': 'Failed to process MIDI file'}), 500
            
        logger.info(f"Successfully converted to WAV: {wav_path}")
        
        # Set up a callback to remove the temp file after sending
        @after_this_request
        def cleanup(response):
            try:
                os.remove(wav_path)
                logger.info(f"Temporary WAV file removed: {wav_path}")
            except Exception as e:
                logger.error(f"Error removing temp file: {str(e)}")
            return response
            
        return send_file(wav_path, mimetype='audio/wav', conditional=True)
            
    except Exception as e:
        logger.error(f"Result playback error: {str(e)}")
        return jsonify({'error': str(e)}), 500


def generate_piano_roll_data(midi_path):
    """Generate a piano roll visualization and extract key data"""
    try:
        midi_data = pretty_midi.PrettyMIDI(midi_path)
        
        # Extract key data
        min_pitch = 127
        max_pitch = 0
        start_time = float('inf')
        end_time = 0
        all_notes = []
        
        # Collect all notes from non-drum instruments
        for instrument in midi_data.instruments:
            if not instrument.is_drum:
                for note in instrument.notes:
                    all_notes.append(note)
                    min_pitch = min(min_pitch, note.pitch)
                    max_pitch = max(max_pitch, note.pitch)
                    start_time = min(start_time, note.start)
                    end_time = max(end_time, note.end)
        
        # Set defaults if no notes found
        if min_pitch == 127:
            min_pitch = 60
        if max_pitch == 0:
            max_pitch = 72
        if start_time == float('inf'):
            start_time = 0
        if end_time == 0:
            end_time = 4
            
        # Calculate duration
        duration = end_time - start_time
        
        # Add padding to the range, but ensure we include C and octave boundaries
        min_pitch_octave = (min_pitch // 12) * 12  # Find nearest C below
        max_pitch_octave = ((max_pitch // 12) + 1) * 12  # Find nearest C above
        
        min_pitch = max(0, min_pitch_octave - 3)
        max_pitch = min(127, max_pitch_octave + 3)
        
        # Create piano roll with proper styling
        plt.figure(figsize=(8, 3), dpi=100)
        ax = plt.axes()
        ax.set_facecolor('#2b2b2b')
        
        # Draw octave boundaries (horizontal lines)
        octave_min = min_pitch // 12
        octave_max = max_pitch // 12
        
        # Grid lines
        for octave in range(octave_min, octave_max + 1):
            c_pitch = octave * 12
            if min_pitch <= c_pitch <= max_pitch:
                plt.axhline(y=c_pitch, color='#505050', linestyle='-', linewidth=0.7)
        
        # Vertical grid lines (time markers)
        beat_duration = 0.5  # Adjust based on typical beat length
        for t in np.arange(0, duration + beat_duration, beat_duration):
            plt.axvline(x=t, color='#404040', linestyle='-', linewidth=0.5)
        
        # Plot notes
        if all_notes:
            for note in all_notes:
                # Calculate note position and size
                x = note.start - start_time
                y = note.pitch
                width = note.end - note.start
                height = 0.7
                
                # Draw the note rectangle
                rect = plt.Rectangle(
                    (x, y - height/2),
                    width,
                    height,
                    color='#00ff00',
                    ec='#00cc00',
                    linewidth=1
                )
                ax.add_patch(rect)
        
        # Set axis limits
        plt.xlim(0, duration)
        plt.ylim(min_pitch - 1, max_pitch + 1)
        
        # Add note labels on y-axis
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        y_ticks = []
        y_labels = []
        
        for octave in range(octave_min, octave_max + 1):
            for note_idx, note_name in enumerate(note_names):
                pitch = octave * 12 + note_idx
                if min_pitch <= pitch <= max_pitch:
                    if note_idx == 0:  # Only label 'C' notes with octave
                        y_ticks.append(pitch)
                        y_labels.append(f'{note_name}{octave}')
                    elif note_idx % 2 == 0:  # Label only natural notes (non-sharps)
                        y_ticks.append(pitch)
                        y_labels.append(note_name)
        
        plt.yticks(y_ticks, y_labels)
        
        # Add time markers on x-axis
        time_ticks = np.arange(0, duration + 1, 1.0)
        time_labels = [f"{start_time + t:.1f}" for t in time_ticks]
        plt.xticks(time_ticks, time_labels)
        
        # Save to bytesIO and convert to base64
        buffer = BytesIO()
        plt.tight_layout()
        plt.savefig(buffer, format='png', bbox_inches='tight')
        buffer.seek(0)
        plt.close()
        
        # Convert to base64 for embedding in HTML
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        # Return both image and metadata
        return {
            'image': f"data:image/png;base64,{img_str}",
            'min_pitch': min_pitch,
            'max_pitch': max_pitch,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration
        }
        
    except Exception as e:
        logger.error(f"Piano roll generation error: {str(e)}")
        return {
            'image': "",
            'min_pitch': 60,
            'max_pitch': 72,
            'start_time': 0,
            'end_time': 4,
            'duration': 4
        }


@app.route('/visualize_synchronized', methods=['POST'])
def visualize_synchronized():
    """Generate synchronized piano roll visualizations"""
    try:
        data = request.json
        query_file_id = data.get('query_file_id')
        result_path = data.get('result_path')
        
        logger.info(f"Visualize synchronized request with query_file_id: {query_file_id}, result_path: {result_path}")
        
        if query_file_id not in uploaded_files:
            logger.error(f"Query file not found: {query_file_id}")
            return jsonify({'error': 'Query file not found'}), 404
            
        query_path = uploaded_files[query_file_id]['path']
        logger.info(f"Query path: {query_path}")
        
        # First, try to use the result_path directly if it's a complete path
        if os.path.isabs(result_path) and os.path.exists(result_path):
            full_result_path = result_path
            logger.info(f"Using absolute path directly: {full_result_path}")
        # Then try using it with the dataset path
        elif os.path.exists(os.path.join(DATASET_PATH, result_path)):
            full_result_path = os.path.join(DATASET_PATH, result_path)
            logger.info(f"Found result file at dataset path: {full_result_path}")
        # If not found, try to search by basename as a fallback
        else:
            basename = os.path.basename(result_path)
            logger.info(f"Searching for file with basename: {basename}")
            
            found = False
            for root, dirs, files in os.walk(DATASET_PATH):
                if basename in files:
                    full_result_path = os.path.join(root, basename)
                    logger.info(f"Found result file at: {full_result_path}")
                    found = True
                    break
                    
            if not found:
                logger.error(f"Result file not found for path: {result_path}")
                return jsonify({'error': 'Result file not found'}), 404
        
        if not os.path.exists(full_result_path):
            logger.error(f"Result file not found at final path: {full_result_path}")
            return jsonify({'error': 'Result file not found'}), 404
            
        # Generate synchronized visualizations
        query_midi = pretty_midi.PrettyMIDI(query_path)
        result_midi = pretty_midi.PrettyMIDI(full_result_path)
        
        # Find the overall pitch range and time range
        min_pitch = 127
        max_pitch = 0
        query_start = float('inf')
        query_end = 0
        result_start = float('inf')
        result_end = 0
        
        # Process query file
        for instrument in query_midi.instruments:
            if not instrument.is_drum and instrument.notes:
                for note in instrument.notes:
                    min_pitch = min(min_pitch, note.pitch)
                    max_pitch = max(max_pitch, note.pitch)
                    query_start = min(query_start, note.start)
                    query_end = max(query_end, note.end)
                    
        # Process result file
        for instrument in result_midi.instruments:
            if not instrument.is_drum and instrument.notes:
                for note in instrument.notes:
                    min_pitch = min(min_pitch, note.pitch)
                    max_pitch = max(max_pitch, note.pitch)
                    result_start = min(result_start, note.start)
                    result_end = max(result_end, note.end)
        
        # Set defaults if no notes found
        if min_pitch == 127: min_pitch = 60
        if max_pitch == 0: max_pitch = 72
        if query_start == float('inf'): query_start = 0
        if query_end == 0: query_end = 4
        if result_start == float('inf'): result_start = 0
        if result_end == 0: result_end = 4
            
        # Calculate durations
        query_duration = query_end - query_start
        result_duration = result_end - result_start
        total_duration = max(query_duration, result_duration)
        
        # Add padding to pitch range
        min_pitch = max(0, min_pitch - 2)
        max_pitch = min(127, max_pitch + 2)
        
        # Generate visualizations with the same scale
        query_img = generate_unified_piano_roll(query_midi, query_start, min_pitch, max_pitch, total_duration)
        result_img = generate_unified_piano_roll(result_midi, result_start, min_pitch, max_pitch, total_duration)
        
        return jsonify({
            'query_piano_roll': query_img,
            'result_piano_roll': result_img,
            'min_pitch': min_pitch,
            'max_pitch': max_pitch,
            'total_duration': total_duration
        })
        
    except Exception as e:
        logger.error(f"Synchronized visualization error: {str(e)}")
        return jsonify({'error': str(e)}), 500


def generate_unified_piano_roll(midi_data, start_time, min_pitch, max_pitch, total_duration):
    """Generate a piano roll with unified scale for comparison"""
    try:
        # Create piano roll with proper styling
        plt.figure(figsize=(8, 3), dpi=100)
        ax = plt.axes()
        ax.set_facecolor('#2b2b2b')
        
        # Draw octave boundaries (horizontal lines)
        octave_min = min_pitch // 12
        octave_max = max_pitch // 12
        
        # Grid lines
        for octave in range(octave_min, octave_max + 1):
            c_pitch = octave * 12
            if min_pitch <= c_pitch <= max_pitch:
                plt.axhline(y=c_pitch, color='#505050', linestyle='-', linewidth=0.7)
        
        # Vertical grid lines (time markers)
        beat_duration = 0.5  # Adjust based on typical beat length
        for t in np.arange(0, total_duration + beat_duration, beat_duration):
            plt.axvline(x=t, color='#404040', linestyle='-', linewidth=0.5)
        
        # Plot notes
        has_notes = False
        for instrument in midi_data.instruments:
            if not instrument.is_drum:
                for note in instrument.notes:
                    has_notes = True
                    # Calculate note position and size
                    x = note.start - start_time
                    y = note.pitch
                    width = note.end - note.start
                    height = 0.7
                    
                    # Draw the note rectangle
                    rect = plt.Rectangle(
                        (x, y - height/2),
                        width,
                        height,
                        color='#00ff00',
                        ec='#00cc00',
                        linewidth=1
                    )
                    ax.add_patch(rect)
        
        # Set consistent axis limits
        plt.xlim(0, total_duration)
        plt.ylim(min_pitch - 1, max_pitch + 1)
        
        # Add note labels on y-axis
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        y_ticks = []
        y_labels = []
        
        for octave in range(octave_min, octave_max + 1):
            for note_idx, note_name in enumerate(note_names):
                pitch = octave * 12 + note_idx
                if min_pitch <= pitch <= max_pitch:
                    if note_idx == 0:  # Only label 'C' notes with octave
                        y_ticks.append(pitch)
                        y_labels.append(f'{note_name}{octave}')
                    elif note_idx % 2 == 0:  # Label only natural notes (non-sharps)
                        y_ticks.append(pitch)
                        y_labels.append(note_name)
        
        plt.yticks(y_ticks, y_labels)
        
        # Add time markers on x-axis
        time_ticks = np.arange(0, total_duration + 1, 1.0)
        time_labels = [f"{start_time + t:.1f}" for t in time_ticks]
        plt.xticks(time_ticks, time_labels)
        
        # Save to bytesIO and convert to base64
        buffer = BytesIO()
        plt.tight_layout()
        plt.savefig(buffer, format='png', bbox_inches='tight')
        buffer.seek(0)
        plt.close()
        
        # Convert to base64 for embedding in HTML
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
        
    except Exception as e:
        logger.error(f"Unified piano roll generation error: {str(e)}")
        return ""


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 