# SaMuGed (Similar MIDI Generator & Editor)

A Python application for finding similar MIDI patterns using feature-based similarity search.

## Development Progress

The project maintains detailed progress tracking in `docs/PROGRESS.md`. Current version is v1.1.6 with the following major milestones achieved:

- Core MIDI feature extraction and similarity search ✓
- Feature weights system and GUI ✓
- MIDI playback with controls ✓
- Dataset caching system ✓
- Piano roll visualization ✓
- Advanced playback state management ✓

Upcoming planned versions:
- v1.1.7: Piano Roll Fine-tuning
- v1.2.0: Advanced Playback Features
- v1.3.0: Enhanced MIDI Processing
- v1.4.0: Advanced Features

For detailed progress tracking, feature status, and development plans, please refer to `docs/PROGRESS.md`.

## Features

- MIDI feature extraction (pitch, rhythm, tempo analysis)
- Configurable feature weights for customized similarity search
- User-friendly GUI with interactive controls
- Real-time similarity search results
- Support for large MIDI datasets

## Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/yourusername/SaMuGed-SimilarMidis.git](https://github.com/AlgoritmiNarvik/SaMuGeD-Algoritmi-DrDreSamplerAI-2024)
   cd SaMuGed-SimilarMidis
   ```

2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Place your MIDI dataset in `datasets/Lakh_MIDI_Clean_Patterns_v1/`
2. Run the application:
   ```bash
   python app.py
   ```
3. Use the interface to:
   - Adjust feature weights using sliders
   - Load a query MIDI file
   - View similarity search results

## Requirements

See `requirements.txt` for detailed dependencies.

## Project Structure

```
├── app.py              # Main application and GUI
├── config.py           # Configuration settings
├── database.py         # Dataset handling and search
├── feature_calculator.py # MIDI feature extraction
├── requirements.txt    # Project dependencies
├── docs/              # Documentation
│   ├── PROGRESS.md    # Development progress
│   └── ...
└── datasets/          # MIDI dataset directory
```
