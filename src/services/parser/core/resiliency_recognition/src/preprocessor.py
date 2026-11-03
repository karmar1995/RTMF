import numpy as np
import config

class TimeSeriesPreprocessor:
    """
    Object-oriented handler for time series preprocessing,
    including standardization and windowing.
    """
    def __init__(self):
        self.window_size = config.WINDOW_SIZE
        self.mode = config.STANDARDIZATION_MODE

    def transform(self, data: np.ndarray) -> np.ndarray:
        """
        Executes the preprocessing pipeline.
        
        Args:
            data: 1D array of metric values.
            
        Returns:
            2D array of processed feature windows.
        """
        if len(data) < self.window_size:
            return np.array([])

        # 1. Standardization
        standardized_data = self._standardize(data)
        
        # 2. Windowing
        windows = self._windowing(standardized_data)
        
        return windows

    def _standardize(self, data: np.ndarray) -> np.ndarray:
        """Applies normalization according to the configuration."""
        if self.mode == 'global':
            series_mean = np.mean(data)
            series_std = np.std(data)
            if series_std != 0:
                return (data - series_mean) / series_std
            else:
                return np.zeros_like(data)
        return data # No standardization if mode is different

    def _windowing(self, data: np.ndarray) -> np.ndarray:
        """Splits the 1D series into overlapping sliding windows."""
        windows = []
        for i in range(len(data) - self.window_size + 1):
            windows.append(data[i:i + self.window_size])
        return np.array(windows)
