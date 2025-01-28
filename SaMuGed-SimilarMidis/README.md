# SaMuGed (Similar MIDI Generator & Editor)

A Python application for finding similar MIDI patterns using feature-based similarity search.

## Features

- MIDI feature extraction (pitch, rhythm, tempo analysis)
- Configurable feature weights for customized similarity search
- User-friendly GUI with interactive controls
- Real-time similarity search results
- Support for large MIDI datasets

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/SaMuGed-SimilarMidis.git
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
