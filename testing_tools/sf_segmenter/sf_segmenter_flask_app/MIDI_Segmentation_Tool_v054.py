# this down in line 2 is kind of like req.txt, it is for now, run this before evrth
# pip install flask sf_segmenter numpy matplotlib midiutil setuptools

"""
changes made, v054
- names of the output files include the original MIDI file name followed by the relevant suffix
- zip file is named based on the original MIDI file name
- original MIDI file information is displayed in the HTML
- running Python file name is included in the "About This Tool" section
- added detailed titles for each plot from sf_segmenter
- adjusted HTML and CSS to ensure plots fill maximum width and are not cramped
"""

import os
import io
import base64
import zipfile
from flask import Flask, render_template_string, request, jsonify, send_file
import sf_segmenter
import numpy as np
import tempfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import logging
import pretty_midi
import shutil

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

HTML_TEMPLATE = """
<!DOCTYPE html>
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
        .column-2 { width: 60%; }
        .column-3 { width: 20%; }
        h1, h2 { text-align: center; }
        .section { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; }
        input[type="file"], input[type="number"], select, button {
            width: 90%;
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
        .segment-text { font-size: 0.8em; }
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
        .row { display: flex; flex-wrap: wrap; width: 100%; margin-top: 10px; }
        .plot-container { flex: 1; padding: 10px; }
        .plot img { width: 110%; }
    </style>
</head>
<body>
    <div class="container">
        <div class="column column-1">
            <h1>MIDI Segmentation Interface</h1>
            <div class="description">
                <h2>About This Tool</h2>
                <p>This interface allows you to segment a MIDI file using the SF segmenter algorithm. Upload a MIDI file, adjust the segmentation parameters, and visualize the resulting plots and segment boundaries.</p>
                <p>CAREFUL! sf_segmenter just takes 1st track of your midi (midi_obj.instruments[0]) for processing and segmentation!</p>
                <p>Python file running now: {{ python_file_name }}</p>
            </div>
            <div class="section">
                <h2>Configuration Settings</h2>
                <label for="gaussianWindow">Gaussian Window Size (M_gaussian):</label>
                <input type="number" id="gaussianWindow" value="27" min="1">
                <label for="embeddedDimensions">Embedded Dimensions (m_embedded):</label>
                <input type="number" id="embeddedDimensions" value="3" min="1">
                <label for="kNearest">K Nearest Neighbors (k_nearest):</label>
                <input type="number" id="kNearest" value="0.04" step="0.01" min="0">
                <label for="adaptiveWindow">Adaptive Window Size (Mp_adaptive):</label>
                <input type="number" id="adaptiveWindow" value="28" min="1">
                <label for="offsetThreshold">Offset Threshold (offset_thres):</label>
                <input type="number" id="offsetThreshold" value="0.05" step="0.01" min="0">
                <label for="boundNormFeats">Boundary Normalization Features (bound_norm_feats):</label>
                <select id="boundNormFeats">
                    <option value="Infinity" selected>Infinity (Default)</option>
                    <option value="-Infinity">-Infinity</option>
                    <option value="min_max">min_max</option>
                    <option value="log">log</option>
                    <option value="none">None</option>
                </select>
            </div>
            <div class="section">
                <label for="midiFile"><b>Upload MIDI File:</b></label>
                <input type="file" id="midiFile" accept=".mid,.midi">
            </div>
            <button id="updateButton">Segment/Update</button>
        </div>
        <div class="column column-2">
            <div class="section">
                <h2>Novelty Curve for <span id="midiFileName"></span></h2>
                <div id="plotArea" class="plot"></div>
                <div class="description">
                    <h3>MIDI Information</h3>
                    <p>Tempo: <span id="midiTempo"></span> BPM</p>
                    <p>Duration: <span id="midiDuration"></span> seconds</p>
                    <p>Number of Tracks: <span id="numTracks"></span></p>
                    <p>Track Names: <span id="trackNames"></span></p>
                    <p>Contains Drum Tracks: <span id="drumTracks"></span></p>
                    <p>Contains Silent Tracks: <span id="silentTracks"></span></p>
                    <p>Time Signature Changes: <span id="timeSignatureChanges"></span></p>
                    <p>(Changes in the beats per measure, useful for understanding rhythmic complexity)</p>
                    <p>Key Signature Changes: <span id="keySignatureChanges"></span></p>
                    <p>(Changes in the key signature, useful for understanding harmonic complexity)</p>
                </div>
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
    <div id="plotsContainer" class="row"></div>
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
                updateMidiInfo(segmentationResult.midi_info);
                document.getElementById('midiFileName').textContent = segmentationResult.midi_file_name;
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
                a.download = segmentationResult.midi_file_name.replace('.mid', '_Output_segments_and_plots.zip');
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
            plotArea.innerHTML = `<img src="data:image/png;base64,${noveltyCurve}" alt="Novelty Curve" title="Novelty Curve with Segment Boundaries">`;
            const plotsContainer = document.getElementById('plotsContainer');
            plotsContainer.innerHTML = '';

            const plotTitles = {
                'L.png': 'Laplacian Eigenmaps Plot',
                'R.png': 'Recurrence Plot',
                'SF.png': 'Self-Similarity Matrix Plot',
                'lab_S.png': 'Labelling Matrix (S)',
                'lab_S_final.png': 'Final Labelling Matrix (S)',
                'lab_S_trans.png': 'Transition Labelling Matrix (S)',
                'input.png': 'Input Feature Matrix',
                'nc.png': 'Normalized Novelty Curve'
            };

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
                        img.title = plotTitles[imgName] || imgName.replace('.png', '').replace('_', ' ').toUpperCase();
                        const imgDiv = document.createElement('div');
                        imgDiv.className = 'plot-container';
                        const title = document.createElement('p');
                        title.innerHTML = plotTitles[imgName] || imgName.replace('.png', '').replace('_', ' ').toUpperCase();
                        imgDiv.appendChild(title);
                        imgDiv.appendChild(img);
                        rowDiv.appendChild(imgDiv);
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

        function updateMidiInfo(info) {
            document.getElementById('midiTempo').textContent = info.tempo.toFixed(2);
            document.getElementById('midiDuration').textContent = info.duration.toFixed(2);
            document.getElementById('numTracks').textContent = info.num_tracks;
            document.getElementById('trackNames').textContent = info.track_names.join(', ');
            document.getElementById('drumTracks').textContent = info.drum_tracks ? 'Yes' : 'No';
            document.getElementById('silentTracks').textContent = info.silent_tracks ? 'Yes' : 'No';
            document.getElementById('timeSignatureChanges').textContent = info.time_signature_changes.join(', ');
            document.getElementById('keySignatureChanges').textContent = info.key_signature_changes.join(', ');
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, python_file_name=os.path.basename(__file__))

@app.route('/segment', methods=['POST'])
def segment_midi():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    original_midi_name = os.path.splitext(file.filename)[0]
    temp_dir = tempfile.mkdtemp()
    try:
        temp_path = os.path.join(temp_dir, file.filename)
        file.save(temp_path)
        app.logger.debug(f"Temporary file saved at: {temp_path}")

        config = {
            "M_gaussian": int(request.form.get('M_gaussian', 27)),
            "m_embedded": int(request.form.get('m_embedded', 3)),
            "k_nearest": float(request.form.get('k_nearest', 0.04)),
            "Mp_adaptive": int(request.form.get('Mp_adaptive', 28)),
            "offset_thres": float(request.form.get('offset_thres', 0.05)),
            "bound_norm_feats": request.form.get('bound_norm_feats', 'Infinity')
        }
    
        if config['bound_norm_feats'] == 'Infinity':
            config['bound_norm_feats'] = np.inf
        elif config['bound_norm_feats'] == '-Infinity':
            config['bound_norm_feats'] = -np.inf
        elif config['bound_norm_feats'] == 'none':
            config['bound_norm_feats'] = None

        app.logger.debug(f"Configuration: {config}")

        segmenter = sf_segmenter.Segmenter(config=config)
        app.logger.debug(f"Segmenter initialized with config: {config}")
        
        app.logger.debug(f"Processing MIDI file: {temp_path}")
        try:
            segmenter.proc_midi(temp_path) # CAREFUL HERE, sf_segmenter just takes midi_obj.instruments[0] for processing
        except Exception as e:
            app.logger.error(f"Error processing MIDI file: {str(e)}", exc_info=True)
            return jsonify({'error': f"Error processing MIDI file: {str(e)}"}), 500

        app.logger.debug("MIDI processing completed")
        
        plot_dir = os.path.join(temp_dir, 'plots')
        os.makedirs(plot_dir, exist_ok=True)
        segmenter.plot(plot_dir)
        
        plots = {}
        for filename in os.listdir(plot_dir):
            if filename.endswith('.png'):
                with open(os.path.join(plot_dir, filename), 'rb') as f:
                    plots[filename] = base64.b64encode(f.read()).decode('utf-8')
        
        segment_boundaries = segmenter.boundaries
        segments = [{"start": float(start), "end": float(end)} 
                    for start, end in zip(segment_boundaries[:-1], segment_boundaries[1:])]

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

        midi_segments_base64 = []
        for segment in midi_segments:
            midi_io = io.BytesIO()
            segment.write(midi_io)
            midi_io.seek(0)
            midi_segments_base64.append(base64.b64encode(midi_io.read()).decode('utf-8'))

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

        with open(novelty_curve_path, 'rb') as f:
            novelty_curve_base64 = base64.b64encode(f.read()).decode('utf-8')

        # extracting more MIDI information
        time_signature_changes = [(f"{ts.time:.2f} seconds: {ts.numerator}/{ts.denominator}") for ts in midi_data.time_signature_changes]
        key_signature_changes = [(f"{ks.time:.2f} seconds: {pretty_midi.key_number_to_key_name(ks.key_number)}") for ks in midi_data.key_signature_changes]

        midi_info = {
            'tempo': midi_data.estimate_tempo(),
            'duration': midi_data.get_end_time(),
            'num_tracks': len(midi_data.instruments),
            'track_names': [instr.name for instr in midi_data.instruments],
            'drum_tracks': any(instr.is_drum for instr in midi_data.instruments),
            'silent_tracks': any(len(instr.notes) == 0 for instr in midi_data.instruments),
            'time_signature_changes': time_signature_changes,
            'key_signature_changes': key_signature_changes
        }

        return jsonify({
            'plots': plots,
            'novelty_curve': novelty_curve_base64,
            'segments': segments,
            'midi_segments': midi_segments_base64,
            'midi_info': midi_info,
            'midi_file_name': file.filename
        })
    
    except Exception as e:
        app.logger.error(f"Error during segmentation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            app.logger.error(f"Failed to remove temp_dir: {temp_dir}. Reason: {e}")

@app.route('/save_results', methods=['POST'])
def save_results():
    data = request.json
    
    try:
        temp_dir = tempfile.mkdtemp()
        
        original_midi_name = os.path.splitext(data['midi_file_name'])[0]
        
        for name, plot_data in data['plots'].items():
            img_data = base64.b64decode(plot_data)
            with open(os.path.join(temp_dir, f"{original_midi_name}_{name}"), 'wb') as f:
                f.write(img_data)

        novelty_curve_data = base64.b64decode(data['novelty_curve'])
        with open(os.path.join(temp_dir, f'{original_midi_name}_novelty_curve_with_segments.png'), 'wb') as f:
            f.write(novelty_curve_data)
        
        with open(os.path.join(temp_dir, f'{original_midi_name}_segments_summary.txt'), 'w') as f:
            for i, segment in enumerate(data['segments']):
                f.write(f"Segment {i+1}: Start: {segment['start']:.2f} beats, End: {segment['end']:.2f} beats, Duration: {segment['end']-segment['start']:.2f} beats\n")
        
        for i, midi_data in enumerate(data['midi_segments']):
            midi_bytes = base64.b64decode(midi_data)
            with open(os.path.join(temp_dir, f'{original_midi_name}_segment_{i+1}.mid'), 'wb') as f:
                f.write(midi_bytes)
        
        zip_path = os.path.join(temp_dir, f'{original_midi_name}_Output_segments_and_plots.zip')
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in os.listdir(temp_dir):
                if file != f'{original_midi_name}_Output_segments_and_plots.zip':
                    zipf.write(os.path.join(temp_dir, file), file)
        
        return send_file(zip_path, as_attachment=True, download_name=f'{original_midi_name}_Output_segments_and_plots.zip')
    
    except Exception as e:
        app.logger.error(f"Error saving results: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            app.logger.error(f"Failed to remove temp_dir: {temp_dir}. Reason: {e}")

if __name__ == '__main__':
    app.run(debug=True)
