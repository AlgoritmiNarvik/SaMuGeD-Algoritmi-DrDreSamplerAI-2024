# this down in line 2 is kind of like req.txt, it is for now, run this before evrth
# pip install flask sf_segmenter numpy matplotlib midiutil setuptools

import os
import io
import base64
import zipfile
from flask import Flask, render_template_string, request, jsonify, send_file
import sf_segmenter
import numpy as np
import tempfile
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import logging
import pretty_midi

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MIDI Segmentation Interface</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.18.2/plotly.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 10px; }
        .container { display: flex; flex-wrap: wrap; }
        .column { flex: 1; padding: 10px; }
        .column-1 { width: 20%; }
        .column-2 { width: 60%; } /* Adjust this width to control the scaling of the plot */
        .column-3 { width: 20%; }
        h1, h2 { text-align: center; }
        .section { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; }
        input[type="file"], input[type="number"], select, button {
            width: 90%; /* Adjusted to make input boxes narrower */
            padding: 10px;
            margin-bottom: 10px;
        }
        .plot { width: 100%; margin-bottom: 20px; }
        .description { 
            background-color: #f0f0f0; 
            padding: 15px; 
            border-radius: 5px; 
            margin-bottom: 20px;
        }
        .segmentation-output { font-size: 0.9em; }
        .segment-text { font-size: 0.8em; } /* Control the font size of segment descriptions */
        #saveButton { 
            display: none; 
            background-color: lightgreen; 
            border: none; 
            padding: 10px; 
            font-size: 16px; 
            cursor: pointer; 
            border-radius: 5px; 
            width: 110%;
            margin-top: 10px;
        }
        #updateButton { 
            background-color: lightpink; 
            border: none; 
            padding: 10px; 
            font-size: 16px; 
            cursor: pointer; 
            border-radius: 5px; 
        }
        .row { display: flex; width: 100%; margin-top: 10px; }
        .row img { width: 50%; }
        .plot img { width: 110%; } /* Ensure the plot image fills the width of the column */
    </style>
</head>
<body>
    <div class="container">
        <div class="column column-1">
            <h1>MIDI Segmentation Interface</h1>
            <div class="description">
                <h2>About This Tool</h2>
                <p>This interface allows you to segment a MIDI file using the SF segmenter algorithm. Upload a MIDI file, adjust the segmentation parameters, and visualize the resulting plots and segment boundaries.</p>
            </div>
            <div class="section">
                <label for="midiFile">Upload MIDI File:</label>
                <input type="file" id="midiFile" accept=".mid,.midi">
            </div>
            <div class="section">
                <h2>Configuration Settings</h2>
                <label for="gaussianWindow">Gaussian Window Size (M_gaussian):</label>
                <input type="number" id="gaussianWindow" value="10" min="1">
                <label for="embeddedDimensions">Embedded Dimensions (m_embedded):</label>
                <input type="number" id="embeddedDimensions" value="2" min="1">
                <label for="kNearest">K Nearest Neighbors (k_nearest):</label>
                <input type="number" id="kNearest" value="0.02" step="0.01" min="0">
                <label for="adaptiveWindow">Adaptive Window Size (Mp_adaptive):</label>
                <input type="number" id="adaptiveWindow" value="10" min="1">
                <label for="offsetThreshold">Offset Threshold (offset_thres):</label>
                <input type="number" id="offsetThreshold" value="0.02" step="0.01" min="0">
                <label for="boundNormFeats">Boundary Normalization Features (bound_norm_feats):</label>
                <select id="boundNormFeats">
                    <option value="Infinity" selected>Infinity (Default)</option>
                    <option value="-Infinity">-Infinity</option>
                    <option value="min_max">min_max</option>
                    <option value="log">log</option>
                    <option value="none">None</option>
                </select>
                <button id="updateButton">Segment/Update</button>
            </div>
        </div>
        <div class="column column-2">
            <div class="section">
                <h2>Novelty Curve</h2>
                <div id="plotArea" class="plot"></div>
            </div>
        </div>
        <div class="column column-3">
            <div class="section segmentation-output">
                <h2>Segmentation Output</h2>
                <div id="segmentOutput" class="segment-text"></div>
                <button id="saveButton">Save/Download Results</button>
            </div>
        </div>
    </div>
    <div id="plotsContainer"></div>
    <script>
        let segmentationResult = null;

        document.getElementById('updateButton').addEventListener('click', async () => {
            const file = document.getElementById('midiFile').files[0];
            if (!file) {
                alert('Please upload a MIDI file first.');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);
            formData.append('M_gaussian', document.getElementById('gaussianWindow').value);
            formData.append('m_embedded', document.getElementById('embeddedDimensions').value);
            formData.append('k_nearest', document.getElementById('kNearest').value);
            formData.append('Mp_adaptive', document.getElementById('adaptiveWindow').value);
            formData.append('offset_thres', document.getElementById('offsetThreshold').value);
            formData.append('bound_norm_feats', document.getElementById('boundNormFeats').value);

            try {
                const response = await fetch('/segment', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                segmentationResult = await response.json();
                if (segmentationResult.error) {
                    throw new Error(segmentationResult.error);
                }

                displayPlots(segmentationResult.plots, segmentationResult.novelty_curve);
                updateSegmentOutput(segmentationResult.segments);
                document.getElementById('saveButton').style.display = 'block';
            } catch (error) {
                console.error('Error:', error);
                alert('Error during segmentation: ' + error.message);
            }
        });

        document.getElementById('saveButton').addEventListener('click', async () => {
            if (!segmentationResult) {
                alert('Please perform segmentation first.');
                return;
            }

            try {
                const response = await fetch('/save_results', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(segmentationResult)
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = 'segmentation_results.zip';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
            } catch (error) {
                console.error('Error:', error);
                alert('Error saving results: ' + error.message);
            }
        });

        function displayPlots(plots, noveltyCurve) {
            const plotArea = document.getElementById('plotArea');
            plotArea.innerHTML = `<img src="data:image/png;base64,${noveltyCurve}" alt="Novelty Curve">`;
            const plotsContainer = document.getElementById('plotsContainer');
            plotsContainer.innerHTML = '';

            // Add rows of images dynamically
            const rows = [['L.png', 'R.png', 'SF.png'], 
                          ['lab_S.png', 'lab_S_final.png', 'lab_S_trans.png'], 
                          ['input.png', 'nc.png']];

            rows.forEach((row) => {
                const rowDiv = document.createElement('div');
                rowDiv.className = 'row';
                row.forEach((imgName) => {
                    if (plots[imgName]) {
                        const img = document.createElement('img');
                        img.src = `data:image/png;base64,${plots[imgName]}`;
                        img.alt = imgName;
                        rowDiv.appendChild(img);
                    }
                });
                plotsContainer.appendChild(rowDiv);
            });
        }

        function updateSegmentOutput(segments) {
            const outputDiv = document.getElementById('segmentOutput');
            outputDiv.innerHTML = '<h3>Segments:</h3>';
            segments.forEach((seg, index) => {
                outputDiv.innerHTML += `<p>Segment ${index + 1}: Start: ${seg.start.toFixed(2)} beats, End: ${seg.end.toFixed(2)} beats, Duration: ${(seg.end - seg.start).toFixed(2)} beats</p>`;
            });
        }
    </script>
</body>
</html>
"""
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/segment', methods=['POST'])
def segment_midi():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    temp_dir = tempfile.mkdtemp()
    try:
        # Save the uploaded file temporarily
        temp_path = os.path.join(temp_dir, file.filename)
        file.save(temp_path)
        app.logger.debug(f"Temporary file saved at: {temp_path}")

        # Get configuration from form data
        config = {
            "M_gaussian": int(request.form.get('M_gaussian', 10)),
            "m_embedded": int(request.form.get('m_embedded', 2)),
            "k_nearest": float(request.form.get('k_nearest', 0.02)),
            "Mp_adaptive": int(request.form.get('Mp_adaptive', 10)),
            "offset_thres": float(request.form.get('offset_thres', 0.02)),
            "bound_norm_feats": request.form.get('bound_norm_feats', 'Infinity')
        }

        # Convert bound_norm_feats to appropriate type
        if config['bound_norm_feats'] == 'Infinity':
            config['bound_norm_feats'] = np.inf
        elif config['bound_norm_feats'] == '-Infinity':
            config['bound_norm_feats'] = -np.inf
        elif config['bound_norm_feats'] == 'none':
            config['bound_norm_feats'] = None

        app.logger.debug(f"Configuration: {config}")

        # Perform segmentation
        segmenter = sf_segmenter.Segmenter(config=config)
        app.logger.debug(f"Segmenter initialized with config: {config}")
        
        app.logger.debug(f"Processing MIDI file: {temp_path}")
        segmenter.proc_midi(temp_path)
        app.logger.debug("MIDI processing completed")
        
        # Generate plots using sf_segmenter's built-in method
        plot_dir = os.path.join(temp_dir, 'plots')
        os.makedirs(plot_dir, exist_ok=True)
        segmenter.plot(plot_dir)
        
        # Read generated plots and convert to base64
        plots = {}
        for filename in os.listdir(plot_dir):
            if filename.endswith('.png'):
                with open(os.path.join(plot_dir, filename), 'rb') as f:
                    plots[filename] = base64.b64encode(f.read()).decode('utf-8')
        
        # Extract segments
        segment_boundaries = segmenter.boundaries
        segments = [{"start": float(start), "end": float(end)} 
                    for start, end in zip(segment_boundaries[:-1], segment_boundaries[1:])]

        # Extract MIDI segments
        midi_data = pretty_midi.PrettyMIDI(temp_path)
        midi_segments = []
        for i, (start, end) in enumerate(zip(segment_boundaries[:-1], segment_boundaries[1:])):
            segment = pretty_midi.PrettyMIDI()
            for instrument in midi_data.instruments:
                new_instrument = pretty_midi.Instrument(
                    program=instrument.program,
                    is_drum=instrument.is_drum,
                    name=instrument.name
                )
                for note in instrument.notes:
                    if start <= note.start < end:
                        new_note = pretty_midi.Note(
                            velocity=note.velocity,
                            pitch=note.pitch,
                            start=max(0, note.start - start),
                            end=min(note.end - start, end - start)
                        )
                        new_instrument.notes.append(new_note)
                if new_instrument.notes:
                    segment.instruments.append(new_instrument)
            midi_segments.append(segment)

        # Convert MIDI segments to base64
        midi_segments_base64 = []
        for segment in midi_segments:
            midi_io = io.BytesIO()
            segment.write(midi_io)
            midi_io.seek(0)
            midi_segments_base64.append(base64.b64encode(midi_io.read()).decode('utf-8'))

        # Generate and save the novelty curve plot with segment boundaries
        novelty_curve_path = os.path.join(temp_dir, 'novelty_curve_with_segments.png')
        plt.figure(figsize=(12, 6))
        plt.plot(segmenter.nc, label='Novelty Curve')
        for start in segment_boundaries:
            plt.axvline(x=start, color='r', linestyle='--', label='Segment Boundary' if start == segment_boundaries[0] else "")
        plt.title('Novelty Curve with Segment Boundaries')
        plt.xlabel('Time (beats)')
        plt.ylabel('Novelty')
        plt.legend()
        plt.savefig(novelty_curve_path)
        plt.close()

        # Convert the novelty curve plot to base64
        with open(novelty_curve_path, 'rb') as f:
            novelty_curve_base64 = base64.b64encode(f.read()).decode('utf-8')

        # Clean up temporary files
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(file_path)
            except Exception as e:
                app.logger.error(f'Failed to delete {file_path}. Reason: {e}')
        
        return jsonify({
            'plots': plots,
            'novelty_curve': novelty_curve_base64,
            'segments': segments,
            'midi_segments': midi_segments_base64
        })
    
    except Exception as e:
        app.logger.error(f"Error during segmentation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    
    finally:
        try:
            os.rmdir(temp_dir)
        except OSError as e:
            app.logger.error(f"Failed to remove temp_dir: {temp_dir}. Reason: {e}")

@app.route('/save_results', methods=['POST'])
def save_results():
    data = request.json
    
    try:
        # Create a temporary directory to store files
        temp_dir = tempfile.mkdtemp()
        
        # Save plots
        for name, plot_data in data['plots'].items():
            img_data = base64.b64decode(plot_data)
            with open(os.path.join(temp_dir, name), 'wb') as f:
                f.write(img_data)

        # Save novelty curve plot
        novelty_curve_data = base64.b64decode(data['novelty_curve'])
        with open(os.path.join(temp_dir, 'novelty_curve_with_segments.png'), 'wb') as f:
            f.write(novelty_curve_data)
        
        # Save segments summary
        with open(os.path.join(temp_dir, 'segments_summary.txt'), 'w') as f:
            for i, segment in enumerate(data['segments']):
                f.write(f"Segment {i+1}: Start: {segment['start']:.2f} beats, End: {segment['end']:.2f} beats, Duration: {segment['end']-segment['start']:.2f} beats\n")
        
        # Save MIDI segments
        for i, midi_data in enumerate(data['midi_segments']):
            midi_bytes = base64.b64decode(midi_data)
            with open(os.path.join(temp_dir, f'segment_{i+1}.mid'), 'wb') as f:
                f.write(midi_bytes)
        
        # Create a zip file containing all results
        zip_path = os.path.join(temp_dir, 'segmentation_results.zip')
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in os.listdir(temp_dir):
                if file != 'segmentation_results.zip':
                    zipf.write(os.path.join(temp_dir, file), file)
        
        return send_file(zip_path, as_attachment=True, download_name='segmentation_results.zip')
    
    except Exception as e:
        app.logger.error(f"Error saving results: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        # Clean up temporary files
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(file_path)
            except Exception as e:
                app.logger.error(f'Failed to delete {file_path}. Reason: {e}')
        
        try:
            os.rmdir(temp_dir)
        except OSError as e:
            app.logger.error(f"Failed to remove temp_dir: {temp_dir}. Reason: {e}")

if __name__ == '__main__':
    app.run(debug=True)
