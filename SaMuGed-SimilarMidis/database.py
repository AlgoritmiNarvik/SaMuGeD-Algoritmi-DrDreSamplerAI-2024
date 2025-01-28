import os
import numpy as np
from typing import List, Dict, Tuple
import faiss
from sklearn.preprocessing import StandardScaler
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH
from feature_calculator import FeatureCalculator

class MIDIDatabase:
    def __init__(self):
        self.index = None
        self.scaler = StandardScaler()
        self.file_paths = []
        self.feature_matrix = None
        self.calculator = FeatureCalculator()
        
    def initialize(self, dataset_path: str = DATASET_PATH) -> None:
        """Preprocess and index entire dataset"""
        features, paths = self._process_dataset(dataset_path)
        if not features:
            raise ValueError("No valid MIDI files found in dataset")
            
        self.file_paths = paths
        self.feature_matrix = np.array(features, dtype='float32')
        self.scaler.fit(self.feature_matrix)
        scaled_features = self.scaler.transform(self.feature_matrix)
        
        # Create FAISS index
        self.index = faiss.IndexFlatL2(scaled_features.shape[1])
        self.index.add(scaled_features.astype('float32'))

    def _process_dataset(self, dataset_path: str) -> Tuple[List, List]:
        features = []
        paths = []
        
        for root, _, files in os.walk(dataset_path):
            for file in files:
                if file.lower().endswith(('.mid', '.midi')):
                    path = os.path.join(root, file)
                    feat = self.calculator.extract_features(path)
                    if feat:
                        features.append(self._feature_vector(feat))
                        paths.append(path)
                        
        return features, paths

    def _feature_vector(self, features: Dict) -> List[float]:
        return [features[key] for key in DEFAULT_FEATURE_WEIGHTS.keys()]

    def find_similar(self, query_path: str, weights: Dict, k: int = MAX_RESULTS) -> List[Tuple[str, float]]:
        """Find similar MIDI files with weighted features"""
        query_feats = self.calculator.extract_features(query_path)
        if not query_feats:
            return []

        # Apply feature weights
        weighted_query = np.array([query_feats[key] * weights[key] 
                                  for key in DEFAULT_FEATURE_WEIGHTS.keys()], dtype='float32')
        weighted_db = self.feature_matrix * np.array(list(weights.values()), dtype='float32')

        # Scale weighted features
        scaled_query = self.scaler.transform(weighted_query.reshape(1, -1))
        scaled_db = self.scaler.transform(weighted_db)

        # Update index with current weights
        temp_index = faiss.IndexFlatL2(scaled_db.shape[1])
        temp_index.add(scaled_db.astype('float32'))

        # Perform search
        distances, indices = temp_index.search(scaled_query.astype('float32'), k)
        
        return [(self.file_paths[i], float(1/(1+d))) 
                for d, i in zip(distances[0], indices[0]) if i < len(self.file_paths)]
        