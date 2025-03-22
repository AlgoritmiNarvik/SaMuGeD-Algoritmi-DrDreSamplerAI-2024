# SaMuGed Web - MIDI Pattern Finder Web Application

This is a web-based version of the SaMuGed (Similar MIDI Generator & Editor) application, allowing for cross-platform access to MIDI pattern similarity search functionality.

## Features

- Web-based interface accessible from any device with a browser
- MIDI file upload and analysis
- Feature-based similarity search with adjustable weights
- Piano roll visualization of MIDI patterns
- In-browser MIDI playback
- Dockerized deployment for cross-platform compatibility

## Requirements

To run the containerized web application, you need:

- Docker
- Docker Compose

Or to run it directly:

- Python 3.9+
- FluidSynth and its development libraries
- Python dependencies (see requirements.txt)

## Getting Started with Docker

The easiest way to run SaMuGed Web is through Docker:

1. Make sure you have Docker and Docker Compose installed

2. Navigate to the project root directory:
   ```bash
   cd SaMuGed-SimilarMidis
   ```

3. Build and start the container:
   ```bash
   docker-compose up -d
   ```

4. Access the application in your browser:
   ```
   http://localhost:5000
   ```

## Getting Started without Docker

1. Install system dependencies (example for Ubuntu/Debian):
   ```bash
   sudo apt-get update
   sudo apt-get install -y fluidsynth libfluidsynth-dev
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Navigate to the project directory and run:
   ```bash
   cd SaMuGed-SimilarMidis
   PYTHONPATH=. flask --app web/app.py run
   ```

4. Access the application in your browser:
   ```
   http://localhost:5001
   ```

## Dataset Setup

The application requires a MIDI dataset for similarity search. Place your MIDI dataset in:

```
SaMuGed-SimilarMidis/datasets/Lakh_MIDI_Clean_Patterns_v1/
```

For best results, use the Lakh MIDI Clean Patterns v1 dataset.

## Soundfont Setup

For proper MIDI playback, you need a soundfont. Place it in:

```
SaMuGed-SimilarMidis/soundfonts/FluidR3_GM.sf2
```

## Usage

1. **Upload a MIDI File**: Click the "Load MIDI" button to upload a query MIDI file.

2. **Adjust Feature Weights**: Use the sliders to adjust the importance of different musical features.

3. **Search**: Click the "Search Again" button after adjusting weights to find similar patterns.

4. **View Results**: Browse through similar MIDI patterns in the results panel.

5. **Playback**: Use the playback controls to listen to the query MIDI or any similar pattern.

## Development

To modify the web application:

1. Edit the Flask application code in `web/app.py`
2. Modify templates in `web/templates/`
3. Restart the application to apply changes

## Troubleshooting

- **No sound**: Make sure your browser supports HTML5 audio and MIDI playback
- **Search not working**: Verify that your MIDI dataset is properly placed in the datasets directory
- **Docker issues**: Check Docker logs with `docker-compose logs`

## License

This project is maintained under the same license as the original SaMuGed application. 