from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import differential_evolution, minimize, minimize_scalar
from scipy.stats import qmc
from scipy.spatial.distance import cdist
from itertools import product


class SSBO:
    """Sequential Surrogate-Based Optimization (SSBO).

    Based on the paper:
    'Global optimization of expensive black-box models
     based on asynchronous hybrid-criterion with interval reduction'
    """

    def __init__(
        self,
        evaluation_callback: Callable[[np.ndarray], tuple[float, np.ndarray]],
        bounds: list[tuple[float, float]],
        constraints: list | None = None,
        kmax: int = 30,
        epsilon: float = 1e-3,
        lhs_candidates: int = 1500,
        random_state: int = 42,
        batch_size: int = 1,
        progress_callback: Callable[[int, list[dict]], None] | None = None,
    ) -> None:
        self.evaluation_callback = evaluation_callback
        self.progress_callback = progress_callback
        self.bounds = np.array(bounds)
        self.dim = len(bounds)
        self.constraints = constraints if constraints else []
        self.kmax = kmax
        self.epsilon = epsilon
        self.lhs_candidates = lhs_candidates
        self.rng = np.random.default_rng(random_state)
        self.n0 = 2 * self.dim + 1
        self.batch_size = batch_size

        self.X: np.ndarray | None = None
        self.y: np.ndarray | None = None
        self.g: np.ndarray | None = None

        self.best_x: np.ndarray | None = None
        self.best_y: float = np.inf
        self.current_iteration: int = 0

    def set_initial_samples(self, X: np.ndarray, y: np.ndarray) -> None:
        self.X = np.asarray(X, dtype=float)
        self.y = np.asarray(y, dtype=float)

    def evaluate(self, x: np.ndarray) -> tuple[float, np.ndarray]:
        y, gvals = self.evaluation_callback(x)
        return y, gvals

    def build_surrogates(self) -> None:
        self.obj_model = RBFInterpolator(self.X, self.y, kernel="thin_plate_spline")
        self.constraint_models = []
        for i in range(len(self.constraints)):
            model = RBFInterpolator(self.X, self.g[:, i], kernel="thin_plate_spline")
            self.constraint_models.append(model)

    def feasible(self, gvals: np.ndarray) -> bool:
        if len(gvals) == 0:
            return True
        return bool(np.all(gvals <= 0))

    def update_best(self) -> None:
        if len(self.constraints) == 0:
            idx = np.argmin(self.y)
            self.best_x = self.X[idx].copy()
            self.best_y = float(self.y[idx])
            return

        feasible_indices = [i for i in range(len(self.y)) if self.feasible(self.g[i])]
        feasible_indices = np.array(feasible_indices, dtype=int)

        if len(feasible_indices) > 0:
            feasible_values = self.y[feasible_indices]
            local_best_idx = np.argmin(feasible_values)
            global_best_idx = feasible_indices[local_best_idx]
        else:
            global_best_idx = np.argmin(self.y)

        self.best_x = self.X[global_best_idx].copy()
        self.best_y = float(self.y[global_best_idx])

    def criterion1(self) -> np.ndarray:
        def surrogate_obj(x: np.ndarray) -> float:
            return float(self.obj_model(np.array([x]))[0])

        result = differential_evolution(
            surrogate_obj, bounds=self.bounds, polish=True, seed=0
        )
        return result.x

    def criterion2(self, j: int = 1) -> np.ndarray:
        sampler = qmc.LatinHypercube(d=self.dim, seed=self.rng)
        unit_samples = sampler.random(self.lhs_candidates)
        lower = self.bounds[:, 0]
        upper = self.bounds[:, 1]
        candidates = qmc.scale(unit_samples, lower, upper)

        selected_points: list[np.ndarray] = []
        temp_X = self.X.copy()

        for _ in range(j):
            distances = cdist(candidates, temp_X)
            min_dist = np.min(distances, axis=1)
            idx = np.argmax(min_dist)
            best_candidate = candidates[idx]
            selected_points.append(best_candidate)
            temp_X = np.vstack([temp_X, best_candidate])

        return np.array(selected_points)

    def criterion3(self) -> np.ndarray:
        p = self.n0

        distances = np.linalg.norm(self.X - self.best_x, axis=1)

        idx = np.argsort(distances)[:p]

        local_X = self.X[idx]
        local_y = self.y[idx]

        local_model = RBFInterpolator(local_X, local_y, kernel="thin_plate_spline")

        lower = np.min(local_X, axis=0)
        upper = np.max(local_X, axis=0)

        x0 = self.best_x.copy()

        def surrogate_obj(z: np.ndarray) -> float:
            return float(local_model(np.array([z]))[0])

        bounds = list(zip(lower, upper))

        result = minimize(
            surrogate_obj,
            x0=x0,
            bounds=bounds,
            method="SLSQP",
        )

        return result.x

    def criterion4(self) -> np.ndarray:
        low = self.bounds[:, 0]
        high = self.bounds[:, 1]
        center = (low + high) / 2.0

        points: list[np.ndarray] = [center.copy()]

        for corner in product([0, 1], repeat=self.dim):
            p = np.empty(self.dim)
            for i, bit in enumerate(corner):
                p[i] = low[i] if bit == 0 else high[i]
            points.append(p)

        for varying_dim in range(self.dim):
            fixed_dims = [i for i in range(self.dim) if i != varying_dim]
            for configuration in product([0, 1], repeat=len(fixed_dims)):
                p = np.empty(self.dim)
                p[varying_dim] = center[varying_dim]
                for idx, dim in enumerate(fixed_dims):
                    p[dim] = low[dim] if configuration[idx] == 0 else high[dim]
                points.append(p)

        return np.unique(np.asarray(points), axis=0)

    def criterion5(self) -> np.ndarray:
        current = self.best_x.copy()
        best_candidate = current.copy()
        best_prediction = float(self.obj_model(current.reshape(1, -1))[0])

        for dim in range(self.dim):

            def objective_1d(value: float, d: int = dim) -> float:
                x = current.copy()
                x[d] = value
                return float(self.obj_model(x.reshape(1, -1))[0])

            result = minimize_scalar(
                objective_1d,
                bounds=(self.bounds[dim, 0], self.bounds[dim, 1]),
                method="bounded",
            )

            candidate = current.copy()
            candidate[dim] = result.x
            prediction = float(self.obj_model(candidate.reshape(1, -1))[0])

            if prediction < best_prediction:
                best_prediction = prediction
                best_candidate = candidate

        return best_candidate.reshape(1, -1)

    def filter_too_close(self, x_batch: np.ndarray) -> np.ndarray:
        x_batch = np.asarray(x_batch)
        if x_batch.ndim == 1:
            x_batch = np.array([x_batch])

        valid_points: list[np.ndarray] = []
        temp_X = self.X.copy()

        for candidate in x_batch:
            distances = np.linalg.norm(temp_X - candidate, axis=1)
            min_distance = np.min(distances)
            if min_distance >= self.epsilon:
                valid_points.append(candidate)
                temp_X = np.vstack([temp_X, candidate])

        return np.array(valid_points)

    def optimize(
        self,
    ) -> tuple[np.ndarray, float, list[dict]]:
        if self.X is None or self.y is None:
            raise RuntimeError(
                "Initial samples not set. Call set_initial_samples() first."
            )

        self.g = np.zeros((len(self.X), len(self.constraints)))
        history: list[dict] = []

        self.build_surrogates()
        self.update_best()

        for k in range(0, self.kmax + 1):
            self.current_iteration = k

            if k == 0:
                x_new = self.criterion4()
            elif k % 4 == 1:
                x_new = self.criterion1()
            elif k % 4 == 2:
                x_new = self.criterion5()
            elif k % 4 == 3:
                x_new = self.criterion2(j=self.batch_size)
            else:
                x_new = self.criterion3()

            x_new = self.filter_too_close(x_new)

            if len(x_new) == 0:
                history.append(
                    {
                        "iteration": k,
                        "best_value": self.best_y,
                        "best_x": self.best_x.copy(),
                        "skipped": True,
                    }
                )
                self._publish_progress(k, history)
                continue

            x_new = np.asarray(x_new)
            if x_new.ndim == 1:
                x_new = np.array([x_new])

            y_new = 0.0
            y_values: list[float] = []
            for x_candidate in x_new:
                y_new, g_new = self.evaluate(x_candidate)
                y_values.append(float(y_new))

                self.X = np.vstack([self.X, x_candidate])
                self.y = np.append(self.y, y_new)

                if len(self.constraints):
                    self.g = np.vstack([self.g, g_new])
                else:
                    self.g = np.zeros((len(self.X), len(self.constraints)))

            self.build_surrogates()
            self.update_best()

            history.append(
                {
                    "iteration": k,
                    "best_value": self.best_y,
                    "best_x": self.best_x.copy(),
                    # Parallel point/value lists for this iteration's batch, so
                    # consumers can pair every candidate with its objective
                    # value. new_point/new_value are kept for compatibility and
                    # only describe the last candidate.
                    "new_points": [np.asarray(p).ravel().tolist() for p in x_new],
                    "new_values": y_values,
                    "new_point": x_new,
                    "new_value": y_new,
                    "skipped": False,
                }
            )
            self._publish_progress(k, history)

        return self.best_x, self.best_y, history

    def _publish_progress(self, iteration: int, history: list[dict]) -> None:
        """Report the iteration just completed, if the caller wants progress."""
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(iteration, history)
        except Exception:
            # Progress reporting must never break the optimization itself.
            pass
