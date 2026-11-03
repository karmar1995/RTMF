import os
import sys
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from scipy.signal import medfilt

import config
from preprocessor import TimeSeriesPreprocessor

class ResiliencyAnalyzer:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.model = None
        self.preprocessor = TimeSeriesPreprocessor()
        self._load_model()
    
    def _load_model(self):
        """Loads the trained model from disk."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found at {self.model_path}")
        self.model = joblib.load(self.model_path)

    def process(self, df: pd.DataFrame):
        """Main entry point for self-contained processing."""
        if config.METRIC_COLUMN not in df.columns:
            raise ValueError(f"DataFrame must contain a '{config.METRIC_COLUMN}' column.")
            
        # 1. Preprocessing (Normalization and Windowing)
        # Using the object-oriented preprocessor
        X = self.preprocessor.transform(df[config.METRIC_COLUMN].values)
        
        if X.size == 0:
            return []

        # 2. Predict Raw
        y_pred_raw = self.model.predict(X)
        
        # 3. Filter (Median)
        y_pred_med = self._median_filter(y_pred_raw)
        
        # 4. State Machine Logic
        y_pred_final = self._postprocessing(y_pred_med)
        
        # 5. Convert to Index-based Phases
        return self._generate_phases(y_pred_final)

    def _median_filter(self, predictions: np.ndarray) -> np.ndarray:
        """Applies median filtering to remove noise."""
        if len(predictions) == 0:
            return predictions
        k = config.MEDIAN_FILTER_WINDOW if config.MEDIAN_FILTER_WINDOW % 2 == 1 else config.MEDIAN_FILTER_WINDOW + 1
        return medfilt(predictions, kernel_size=k)

    def _postprocessing(self, predictions: np.ndarray) -> np.ndarray:
        """State Machine Logic (Normal -> Shock -> Recovery -> Normal)."""
        if len(predictions) == 0:
            return predictions

        final_states = []
        current_state = predictions[0] 
        
        for pred in predictions:
            next_state = current_state
            
            # State 1: Normal
            if current_state == 1.0:
                if pred == 2.0: next_state = 2.0
            
            # State 2: Shock (Failure/Drop)
            elif current_state == 2.0:
                if pred == 3.0: next_state = 3.0 
                elif pred == 1.0: next_state = 1.0 # Short-circuit
                
            # State 3: Recovery (Rise)
            elif current_state == 3.0:
                if pred == 1.0: next_state = 1.0 
                elif pred == 2.0: next_state = 2.0 # Relapse
                
            current_state = next_state
            final_states.append(current_state)
            
        return np.array(final_states)

    def _generate_phases(self, predictions: np.ndarray) -> list:
        """Converts prediction sequence into (start, end, label) segments based on indices."""
        if len(predictions) == 0:
            return []

        phases = []
        current_label = predictions[0]
        # Start from 0 to cover the initial window period
        start_idx = 0 
        
        label_map = {1.0: "Normal", 2.0: "Shock", 3.0: "Recovery"}

        for i in range(1, len(predictions)):
            if predictions[i] != current_label:
                # End of current phase
                # Prediction i-1 corresponds to sample index (config.WINDOW_SIZE - 1) + (i - 1)
                end_idx = (config.WINDOW_SIZE - 1) + (i - 1)
                phases.append([int(start_idx), int(end_idx), label_map.get(current_label, str(current_label))])
                
                # Start of next phase
                current_label = predictions[i]
                start_idx = end_idx + 1
        
        # Final phase reaching the end of the total samples
        total_samples = (config.WINDOW_SIZE - 1) + len(predictions)
        phases.append([int(start_idx), int(total_samples - 1), label_map.get(current_label, str(current_label))])
        return phases
