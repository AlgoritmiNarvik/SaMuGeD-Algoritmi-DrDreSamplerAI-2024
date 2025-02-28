import os
import numpy as np
import pickle
from typing import List, Dict, Tuple
import faiss
import logging
from sklearn.preprocessing import StandardScaler
from config import DEFAULT_FEATURE_WEIGHTS, DATASET_PATH, MAX_RESULTS, CACHE_DIR
from feature_calculator import FeatureCalculator

class MIDIDatabase:
    def __init__(self):
        self.index = None
        self.scaler = StandardScaler()
        self.file_paths = []
        self.feature_matrix = None
        self.calculator = FeatureCalculator()
        self.cache_dir = CACHE_DIR
        self._setup_logging()
        
    def _setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)

    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            self.logger.info(f"Created cache directory: {self.cache_dir}")

    def _get_cache_path(self, dataset_path: str) -> str:
        """Get cache file path for dataset with better handling"""
        # Use absolute path for more reliable caching
        abs_path = os.path.abspath(dataset_path)
        # Use a more stable identifier for the cache file
        # We'll use just the last directory name since we know it's stable
        dir_name = os.path.basename(abs_path)
        # Use a simple deterministic string instead of hash
        cache_file = f'stable_dataset_cache_{dir_name}.pkl'
        cache_path = os.path.join(self.cache_dir, cache_file)
        self.logger.info(f"Cache path: {cache_path}")
        return cache_path

    def _save_to_cache(self, dataset_path: str):
        """Save processed data to cache"""
        self._ensure_cache_dir()
        cache_path = self._get_cache_path(dataset_path)
        
        cache_data = {
            'file_paths': self.file_paths,
            'feature_matrix': self.feature_matrix,
            'scaler': self.scaler
        }
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(cache_data, f)
            self.logger.info(f"Saved dataset cache to: {cache_path}")
        except Exception as e:
            self.logger.error(f"Failed to save cache: {str(e)}")

    def _load_from_cache(self, dataset_path: str) -> bool:
        """Load processed data from cache if available"""
        cache_path = self._get_cache_path(dataset_path)
        
        if not os.path.exists(cache_path):
            self.logger.info("No cache file found")
            return False
            
        try:
            self.logger.info(f"Attempting to load cache from: {cache_path}")
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)
                
            self.file_paths = cache_data['file_paths']
            self.feature_matrix = cache_data['feature_matrix']
            self.scaler = cache_data['scaler']
            
            # Basic cache validation
            if len(self.file_paths) == 0 or self.feature_matrix is None:
                self.logger.warning("Cache data is invalid")
                return False

            # Verify at least one file still exists (basic integrity check)
            if not any(os.path.exists(path) for path in self.file_paths[:5]):
                self.logger.warning("Cache validation failed - files no longer exist")
                return False
                
            self.logger.info(f"Successfully loaded {len(self.file_paths)} files from cache")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load cache: {str(e)}")
            return False
        
    def initialize(self, dataset_path: str = DATASET_PATH) -> None:
        """Preprocess and index entire dataset"""
        self.logger.info(f"Initializing database from: {dataset_path}")

        # Check if dataset path exists
        if not os.path.exists(dataset_path):
            self.logger.warning(f"Dataset directory does not exist: {dataset_path}")
            os.makedirs(dataset_path, exist_ok=True)
            self.logger.info(f"Created dataset directory: {dataset_path}")
            self._initialize_empty_database()
            return

        # First try to load from cache
        if self._load_from_cache(dataset_path):
            self.logger.info(f"Successfully loaded dataset from cache with {len(self.file_paths)} files")
            if len(self.file_paths) > 0:
                # Create FAISS index from cached data
                dimension = len(DEFAULT_FEATURE_WEIGHTS)
                self.index = faiss.IndexFlatL2(dimension)
                scaled_features = self.scaler.transform(self.feature_matrix)
                self.index.add(scaled_features.astype('float32'))
                self.logger.info("Successfully initialized index from cache")
                return
            else:
                self.logger.warning("Cache was empty, will scan for new files")
        
        # If no cache or empty cache, check for MIDI files in all subdirectories
        total_midi_files = []
        for root, _, files in os.walk(dataset_path):
            midi_files = [os.path.join(root, f) for f in files if f.lower().endswith(('.mid', '.midi'))]
            total_midi_files.extend(midi_files)
        
        if not total_midi_files:
            self.logger.warning(f"No MIDI files found in {dataset_path} or its subdirectories")
            self._initialize_empty_database()
            return
        
        self.logger.info(f"Found {len(total_midi_files)} MIDI files in dataset")
        
        # Process dataset
        self.logger.info("Processing dataset (this may take a while)...")
        features, paths = self._process_dataset(dataset_path)
        
        if len(features) == 0:
            self.logger.warning("No valid MIDI files could be processed")
            self._initialize_empty_database()
        else:
            self.logger.info(f"Successfully processed {len(features)} MIDI files")
            self.file_paths = paths
            self.feature_matrix = np.array(features, dtype='float32')
            self.logger.info("Fitting StandardScaler...")
            self.scaler.fit(self.feature_matrix)
            
            # Save processed data to cache
            self._save_to_cache(dataset_path)
            
            # Create FAISS index
            dimension = len(DEFAULT_FEATURE_WEIGHTS)
            self.logger.info(f"Creating FAISS index with dimension {dimension}")
            self.index = faiss.IndexFlatL2(dimension)
            scaled_features = self.scaler.transform(self.feature_matrix)
            self.index.add(scaled_features.astype('float32'))
            
        self.logger.info("Database initialization complete")

    def _initialize_empty_database(self):
        """Initialize an empty database with proper structure"""
        self.file_paths = []
        self.feature_matrix = np.array([], dtype='float32').reshape(0, len(DEFAULT_FEATURE_WEIGHTS))
        self.index = faiss.IndexFlatL2(len(DEFAULT_FEATURE_WEIGHTS))
        self.logger.info("Initialized empty database - ready for new files")

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
        