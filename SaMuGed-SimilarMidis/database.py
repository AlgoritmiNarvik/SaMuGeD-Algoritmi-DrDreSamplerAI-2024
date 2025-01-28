import os
import numpy as np
from typing import List, Dict, Tuple
import faiss
import logging
from sklearn.preprocessing import StandardScaler
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH, MAX_RESULTS
from feature_calculator import FeatureCalculator

class MIDIDatabase:
    def __init__(self):
        self.index = None
        self.scaler = StandardScaler()
        self.file_paths = []
        self.feature_matrix = None
        self.calculator = FeatureCalculator()
        self._setup_logging()
        
    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)
        
    def initialize(self, dataset_path: str = DATASET_PATH) -> None:
        """Preprocess and index entire dataset"""
        self.logger.info(f"Initializing database from: {dataset_path}")
        features, paths = self._process_dataset(dataset_path)
        if len(features) == 0:
            self.logger.error("No valid MIDI files found in dataset")
            raise ValueError("No valid MIDI files found in dataset")
            
        self.logger.info(f"Found {len(features)} valid MIDI files")
        self.file_paths = paths
        self.feature_matrix = np.array(features, dtype='float32')
        self.logger.info("Fitting StandardScaler...")
        self.scaler.fit(self.feature_matrix)
        scaled_features = self.scaler.transform(self.feature_matrix)
        
        # Create FAISS index
        dimension = len(DEFAULT_FEATURE_WEIGHTS)
        self.logger.info(f"Creating FAISS index with dimension {dimension}")
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(scaled_features.astype('float32'))
        self.logger.info("Database initialization complete")

    def _process_dataset(self, dataset_path: str) -> Tuple[List, List]:
        features = []
        paths = []
        
        self.logger.info("Starting dataset processing...")
        total_files = 0
        processed_files = 0
        
        for root, _, files in os.walk(dataset_path):
            midi_files = [f for f in files if f.lower().endswith(('.mid', '.midi'))]
            total_files += len(midi_files)
            
            for file in midi_files:
                path = os.path.join(root, file)
                try:
                    self.logger.debug(f"Processing: {path}")
                    feat = self.calculator.extract_features(path)
                    if feat is not None:
                        feat_vector = self._feature_vector(feat)
                        if len(feat_vector) == len(DEFAULT_FEATURE_WEIGHTS):
                            features.append(feat_vector)
                            paths.append(path)
                            processed_files += 1
                            if processed_files % 10 == 0:  # Log progress every 10 files
                                self.logger.info(f"Processed {processed_files}/{total_files} files")
                    else:
                        self.logger.warning(f"No features extracted from: {path}")
                except Exception as e:
                    self.logger.error(f"Error processing {path}: {str(e)}")
                    continue
        
        self.logger.info(f"Dataset processing complete. Successfully processed {processed_files}/{total_files} files")
        return features, paths

    def _feature_vector(self, features: Dict) -> List[float]:
        """Convert feature dictionary to vector in correct order"""
        return [features.get(key, 0.0) for key in DEFAULT_FEATURE_WEIGHTS.keys()]

    def find_similar(self, query_path: str, weights: Dict, k: int = MAX_RESULTS) -> List[Tuple[str, float]]:
        """Find similar MIDI files with weighted features"""
        self.logger.info(f"Searching for similar files to: {query_path}")
        query_feats = self.calculator.extract_features(query_path)
        if query_feats is None:
            self.logger.error(f"Failed to extract features from query file: {query_path}")
            return []

        # Apply feature weights
        self.logger.debug("Applying feature weights...")
        weighted_query = np.array([query_feats.get(key, 0.0) * weights.get(key, 1.0)
                                 for key in DEFAULT_FEATURE_WEIGHTS.keys()], dtype='float32')
        weighted_db = self.feature_matrix * np.array([weights.get(key, 1.0) 
                                                    for key in DEFAULT_FEATURE_WEIGHTS.keys()], dtype='float32')

        # Scale weighted features
        self.logger.debug("Scaling features...")
        scaled_query = self.scaler.transform(weighted_query.reshape(1, -1))
        scaled_db = self.scaler.transform(weighted_db)

        # Update index with current weights
        self.logger.debug("Performing similarity search...")
        temp_index = faiss.IndexFlatL2(scaled_db.shape[1])
        temp_index.add(scaled_db.astype('float32'))

        # Perform search
        k = min(k, len(self.file_paths))
        distances, indices = temp_index.search(scaled_query.astype('float32'), k)
        
        results = [(self.file_paths[i], float(1/(1+d))) 
                  for d, i in zip(distances[0], indices[0]) if i < len(self.file_paths)]
        
        self.logger.info(f"Found {len(results)} similar files")
        return results
        