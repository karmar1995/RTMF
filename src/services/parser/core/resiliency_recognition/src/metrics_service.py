import pandas as pd
import numpy as np
import config

class MetricsService:
    def calculate_metrics(self, df: pd.DataFrame, phases: list, baseline: float = None) -> dict:
        """
        Calculates resilience metrics based on identified phases.
        Returns only the requested metrics.
        """
        if not phases:
            return {}

        metric_values = df[config.METRIC_COLUMN].values
        metrics = {}
        
        # 1. Recovery Time (Longest recovery phase duration)
        metrics["recovery_time_in_steps"] = self._calculate_recovery_time(phases)
        
        # 2. Shock Duration (Longest shock phase duration)
        metrics["shock_time_in_steps"] = self._calculate_shock_time(phases)
        
        # 3. Shock drop and stage metrics for the longest Shock phase
        shock_metrics = self._calculate_shock_metrics(metric_values, phases, baseline)
        metrics.update(shock_metrics)
        
        return metrics

    def _calculate_recovery_time(self, phases: list) -> int:
        """
        Calculates recovery_time as the duration of the longest Recovery phase.
        This serves as a noise-resistant filter.
        """
        recovery_durations = [p[1] - p[0] + 1 for p in phases if p[2] == "Recovery"]
        if not recovery_durations:
            return 0
        return int(max(recovery_durations))

    def _calculate_shock_time(self, phases: list) -> int:
        """
        Calculates time_of_shock as the duration of the longest Shock phase.
        This serves as a noise-resistant filter.
        """
        shock_durations = [p[1] - p[0] + 1 for p in phases if p[2] == "Shock"]
        if not shock_durations:
            return 0
        return int(max(shock_durations))

    def _calculate_shock_metrics(self, metric_values: np.ndarray, phases: list, baseline: float = None) -> dict:
        """
        Calculates metrics for the longest Shock phase:
        - Average metric value during the phase.
        - Standard deviation of metric value during the phase.
        - Drop percentage relative to the immediately preceding Normal phase.
        - Drop percentage relative to the provided baseline (if any).
        """
        metrics = {}
        
        # Find all Shock phases and their indices
        shock_indices = [i for i, p in enumerate(phases) if p[2] == "Shock"]
        if not shock_indices:
            return metrics
            
        # Find the longest Shock phase
        longest_shock_idx = -1
        max_duration = -1
        
        for idx in shock_indices:
            duration = phases[idx][1] - phases[idx][0] + 1
            if duration > max_duration:
                max_duration = duration
                longest_shock_idx = idx
        
        if longest_shock_idx == -1:
            return metrics
            
        shock_phase = phases[longest_shock_idx]
        shock_values = metric_values[shock_phase[0]:shock_phase[1]+1]
        
        avg_shock_val = np.mean(shock_values)
        std_shock_val = np.std(shock_values)
        
        # 1. Drop relative to preceding Normal
        if longest_shock_idx > 0:
            prev_phase = phases[longest_shock_idx - 1]
            if prev_phase[2] == "Normal":
                normal_values = metric_values[prev_phase[0]:prev_phase[1]+1]
                avg_normal = np.mean(normal_values)
                if avg_normal > 0:
                    drop_pct = ((avg_normal - avg_shock_val) / avg_normal) * 100
                    metrics["shock_drop_pct_ref_normal"] = float(drop_pct)
        
        # 2. Drop relative to baseline
        if baseline is not None and baseline > 0:
            drop_pct_baseline = ((baseline - avg_shock_val) / baseline) * 100
            metrics["shock_drop_pct_ref_baseline"] = float(drop_pct_baseline)
        else:
            metrics["shock_drop_pct_ref_baseline"] = None
            
        metrics["shock_stage_avg"] = float(avg_shock_val)
        metrics["shock_stage_std"] = float(std_shock_val)
            
        return metrics

    # Helper methods kept for potential future use but not currently in main output
    def _calculate_durations(self, phases: list) -> dict:
        durations = {}
        total_duration = 0
        for start, end, label in phases:
            duration = end - start + 1
            total_duration += duration
            key = f"{label.lower()}_duration"
            durations[key] = durations.get(key, 0) + int(duration)
        durations["total_duration"] = int(total_duration)
        return durations

    def _calculate_baseline_value(self, metric_values: np.ndarray, phases: list) -> float:
        normal_phases = [p for p in phases if p[2] == "Normal"]
        if normal_phases:
            first_normal = normal_phases[0]
            return float(np.mean(metric_values[first_normal[0]:first_normal[1]+1]))
        return None

    def _calculate_min_value_during_shock(self, metric_values: np.ndarray, phases: list) -> float:
        shock_phases = [p for p in phases if p[2] == "Shock"]
        if shock_phases:
            all_shock_values = []
            for start, end, _ in shock_phases:
                all_shock_values.extend(metric_values[start:end+1])
            return float(np.min(all_shock_values))
        return None

    def _calculate_average_recovery_speed(self, metric_values: np.ndarray, phases: list) -> float:
        recovery_phases = [p for p in phases if p[2] == "Recovery"]
        speeds = []
        for start, end, _ in recovery_phases:
            s_val = metric_values[start]
            e_val = metric_values[end]
            dur = end - start + 1
            if dur > 1:
                speeds.append((e_val - s_val) / dur)
        return float(np.mean(speeds)) if speeds else None

    def _calculate_resilience_loss(self, metric_values: np.ndarray, phases: list, baseline_val: float) -> dict:
        if baseline_val is None:
            return {}
        shock_indices = [i for i, p in enumerate(phases) if p[2] == "Shock"]
        if not shock_indices:
            return {}
        first_shock_phase_idx = shock_indices[0]
        start_affected = phases[first_shock_phase_idx][0]
        end_affected = phases[-1][1]
        for i in range(first_shock_phase_idx + 1, len(phases)):
            if phases[i][2] == "Normal":
                end_affected = phases[i][0] - 1
                break
        affected_values = metric_values[start_affected:end_affected+1]
        loss_area = np.sum(np.maximum(0, baseline_val - affected_values))
        res_metrics = {"resilience_loss_area": float(loss_area)}
        total_potential_area = baseline_val * (end_affected - start_affected + 1)
        if total_potential_area > 0:
            res_metrics["robustness_index"] = float(1 - (loss_area / total_potential_area))
        return res_metrics
