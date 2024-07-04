# this down is req.txt for now, run this before evrth
# pip install flask sf_segmenter numpy matplotlib midiutil

import os
import io
import base64
import zipfile
from flask import Flask, render_template_string, request, jsonify, send_file
import sf_segmenter
import numpy as np
import tempfile
import matplotlib.pyplot as plt
from midiutil import MIDIFile

app = Flask(__name__)

# HTML template (updated with Save Results button)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MIDI Segmentation Interface</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.18.2/plotly.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1, h2 { text-align: center; }
        .section { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; }
        input[type="file"], input[type="number"], select, button {
            width: 100%;
            padding: 10px;
            margin-bottom: 10px;
        }
        #plotArea { width: 100%; height: 400px; }
        .description { 
            background-color: #f0f0f0; 
            padding: 15px; 
            border-radius: 5px; 
            margin-bottom: 20px;
        }
        #saveButton { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>MIDI Segmentation Interface</h1>
        
        <div class="description">
            <h2>About This Tool</h2>
            <p>This interface allows you to segment a MIDI file using the SF segmenter algorithm. You can upload a MIDI file, adjust the segmentation parameters, and visualize the resulting novelty curve and segment boundaries. Experiment with different settings to find the best segmentation for your music!</p>
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
        
        <div class="section">
            <h2>Visualization</h2>
            <div id="plotArea"></div>
        </div>
        
        <div class="section">
            <h2>Segmentation Output</h2>
            <div id="segmentOutput"></div>
        </div>
        
        <button id="saveButton">Save Results</button>
    </div>

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

            const response = await fetch('/segment', {
                method: 'POST',
                body: formData
            });

            segmentationResult = await response.json();
            plotNoveltyCurve(segmentationResult.noveltyData, segmentationResult.segments);
            updateSegmentOutput(segmentationResult.segments);
            document.getElementById('saveButton').style.display = 'block';
        });

        document.getElementById('saveButton').addEventListener('click', async () => {
            if (!segmentationResult) {
                alert('Please perform segmentation first.');
                return;
            }

            const response = await fetch('/save_results', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(segmentationResult)
            });

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = 'segmentation_results.zip';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
        });

        function plotNoveltyCurve(data, segments) {
            const trace = {
                x: Array.from({length: data.length}, (_, i) => i),
                y: data,
                type: 'scatter',
                mode: 'lines',
                name: 'Novelty Curve'
            };

            const segmentLines = segments.map(seg => ({
                type: 'line',
                x0: seg.start,
                y0: 0,
                x1: seg.start,
                y1: 1,
                line: {
                    color: 'red',
                    width: 2,
                    dash: 'dash'
                }
            }));

            const layout = {
                title: 'Novelty Curve with Segments',
                xaxis: {title: 'Time'},
                yaxis: {title: 'Novelty'},
                shapes: segmentLines
            };

            Plotly.newPlot('plotArea', [trace], layout);
        }

        function updateSegmentOutput(segments) {
            const outputDiv = document.getElementById('segmentOutput');
            outputDiv.innerHTML = '<h3>Segments:</h3>';
            segments.forEach((seg, index) => {
                outputDiv.innerHTML += `<p>Segment ${index + 1}: Start: ${seg.start}, End: ${seg.end}</p>`;
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

    # Save the uploaded file temporarily
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)

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

    # Perform segmentation
    segmenter = sf_segmenter.Segmenter(config=config)
    segmenter.proc_midi(temp_path)
    
    # Extract novelty curve and segments
    novelty_data = segmenter.S.transpose().tolist()[0]  # Assuming S is the novelty curve
    segments = [{"start": start, "end": end} for start, end in segmenter.boundaries]

    # Clean up temporary file
    os.remove(temp_path)
    os.rmdir(temp_dir)

    return jsonify({
        'noveltyData': novelty_data,
        'segments': segments,
        'original_midi_path': temp_path
    })

@app.route('/save_results', methods=['POST'])
def save_results():
    data = request.json
    
    # Create a temporary directory to store files
    temp_dir = tempfile.mkdtemp()
    
    # Save novelty curve plot
    plt.figure(figsize=(10, 6))
    plt.plot(data['noveltyData'])
    for segment in data['segments']:
        plt.axvline(x=segment['start'], color='r', linestyle='--')
    plt.title('Novelty Curve with Segments')
    plt.xlabel('Time')
    plt.ylabel('Novelty')
    plt.savefig(os.path.join(temp_dir, 'novelty_curve.png'))
    plt.close()
    
    # Save segments summary
    with open(os.path.join(temp_dir, 'segments_summary.txt'), 'w') as f:
        for i, segment in enumerate(data['segments']):
            f.write(f"Segment {i+1}: Start: {segment['start']}, End: {segment['end']}\n")
    
    # Create a zip file containing all results
    zip_path = os.path.join(temp_dir, 'segmentation_results.zip')
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.write(os.path.join(temp_dir, 'novelty_curve.png'), 'novelty_curve.png')
        zipf.write(os.path.join(temp_dir, 'segments_summary.txt'), 'segments_summary.txt')
        
        # Add segmented MIDI files (this part needs to be implemented based on how you want to split the original MIDI)
        # For demonstration, we're just adding a placeholder file
        with open(os.path.join(temp_dir, 'segmented_midi_placeholder.txt'), 'w') as f:
            f.write("Implement MIDI segmentation here")
        zipf.write(os.path.join(temp_dir, 'segmented_midi_placeholder.txt'), 'segmented_midi_placeholder.txt')
    
    return send_file(zip_path, as_attachment=True, download_name='segmentation_results.zip')

if __name__ == '__main__':
    app.run(debug=True)
