import logging
import numpy as np
from typing import Dict, List, Optional
from pretty_midi import PrettyMIDI

class FeatureCalculator:
    def __init__(self):
        self.required_notes = 2  # Minimum notes to process
        
    def extract_features(self, file_path: str) -> Optional[Dict]:
        try:
            midi = PrettyMIDI(file_path)
        except Exception as e:
            logging.error(f"Error loading {file_path}: {str(e)}")
            return None

        features = {
            'tempo': 120.0,
            'pitch_mean': 0.0,
            'pitch_std': 0.0,
            'duration_mean': 0.0,
            'duration_std': 0.0,
            'ioi_mean': 0.0,
            'ioi_std': 0.0,
            'syncopation_ratio': 0.0,
            'interval_std': 0.0,
            'contour_slope': 0.0
        }

        # Collect all notes from non-drum instruments
        all_notes = []
        for instrument in midi.instruments:
            if not instrument.is_drum:
                all_notes.extend(instrument.notes)
                
        if len(all_notes) < self.required_notes:
            return None

        # Basic features
        features['tempo'] = self._get_tempo(midi)
        pitches = [note.pitch for note in all_notes]
        durations = [note.end - note.start for note in all_notes]
        
        # Pitch statistics
        features.update(self._calculate_statistics(pitches, 'pitch'))
        
        # Duration statistics
        features.update(self._calculate_statistics(durations, 'duration'))
        
        # Rhythm features
        rhythm_features = self._calculate_rhythm_features(all_notes, features['tempo'])
        features.update(rhythm_features)
        
        # Interval features
        intervals = self._calculate_intervals(pitches)
        features['interval_std'] = np.std(intervals) if intervals else 0.0
        
        # Contour analysis
        features['contour_slope'] = self._calculate_contour_slope(pitches)
        
        return features

    def _get_tempo(self, midi: PrettyMIDI) -> float:
        try:
            return midi.estimate_tempo()
        except ValueError:
            tempo_changes = midi.get_tempo_changes()
            return tempo_changes[1][0] if len(tempo_changes[1]) > 0 else 120.0

    def _calculate_statistics(self, values: List[float], prefix: str) -> Dict:
        if not values:
            return {}
            
        arr = np.array(values)
        return {
            f'{prefix}_mean': float(np.mean(arr)),
            f'{prefix}_std': float(np.std(arr))
        }

    def _calculate_rhythm_features(self, notes: List, tempo: float) -> Dict:
        onsets = sorted([note.start for note in notes])
        iois = np.diff(onsets) if len(onsets) > 1 else []
        
        # Syncopation calculation
        beat_duration = 60.0 / tempo
        beat_positions = [(onset % (4 * beat_duration)) / beat_duration for onset in onsets]
        syncopation = [1 if not np.isclose(pos % 1, 0, atol=0.1) else 0 for pos in beat_positions]
        
        return {
            'ioi_mean': float(np.mean(iois)) if iois else 0.0,
            'ioi_std': float(np.std(iois)) if iois else 0.0,
            'syncopation_ratio': float(np.mean(syncopation)) if syncopation else 0.0
        }

    def _calculate_intervals(self, pitches: List[int]) -> List[int]:
        return [abs(pitches[i+1] - pitches[i]) 
                for i in range(len(pitches)-1)] if len(pitches) > 1 else []

    def _calculate_contour_slope(self, pitches: List[int]) -> float:
        if len(pitches) < 2:
            return 0.0
            
        ascents = sum(1 for i in range(len(pitches)-1) if pitches[i+1] > pitches[i])
        descents = sum(1 for i in range(len(pitches)-1) if pitches[i+1] < pitches[i])
        return (ascents - descents) / len(pitches)