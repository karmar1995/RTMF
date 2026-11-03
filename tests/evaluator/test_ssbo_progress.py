from __future__ import annotations

import numpy as np
import pytest

from services.evaluator.core.ssbo.optimizer import SSBO


# The optimum sits away from the initial samples so the optimizer does real
# work instead of terminating on the first iteration.
_INITIAL_SAMPLES = np.array([[0.0], [0.2], [0.4]])
_INITIAL_VALUES = np.array([0.81, 0.49, 0.25])


def _quadratic_callback(x: np.ndarray) -> tuple[float, np.ndarray]:
    return float(np.sum((np.asarray(x) - 0.9) ** 2)), np.array([])


def _initial_samples() -> tuple[np.ndarray, np.ndarray]:
    return _INITIAL_SAMPLES.copy(), _INITIAL_VALUES.copy()


class TestSSBOProgressCallback:
    def test_callback_receives_every_completed_iteration(self) -> None:
        seen: list[tuple[int, int]] = []

        ssbo = SSBO(
            evaluation_callback=_quadratic_callback,
            bounds=[(0.0, 1.0)],
            kmax=4,
            lhs_candidates=64,
            progress_callback=lambda iteration, history: seen.append(
                (iteration, len(history))
            ),
        )
        ssbo.set_initial_samples(*_initial_samples())

        ssbo.optimize()

        assert seen, "progress callback was never invoked"
        # History grows monotonically; kmax is inclusive, so kmax=4 yields
        # iterations 0..4 and therefore five published snapshots.
        lengths = [length for _, length in seen]
        assert lengths == sorted(lengths)
        assert lengths == list(range(1, 6))
        assert lengths[-1] == seen[-1][0] + 1

    def test_callback_receives_history_with_best_values(self) -> None:
        captured: list[list[dict]] = []

        ssbo = SSBO(
            evaluation_callback=_quadratic_callback,
            bounds=[(0.0, 1.0)],
            kmax=3,
            lhs_candidates=64,
            progress_callback=lambda iteration, history: captured.append(
                list(history)
            ),
        )
        ssbo.set_initial_samples(*_initial_samples())

        _, _, history = ssbo.optimize()

        assert len(captured) == len(history)
        for published in captured:
            prefix = history[: len(published)]
            assert [entry["iteration"] for entry in published] == [
                entry["iteration"] for entry in prefix
            ]
            assert all(entry["best_value"] is not None for entry in published)
        assert [entry["iteration"] for entry in captured[-1]] == [
            entry["iteration"] for entry in history
        ]

    def test_history_pairs_every_evaluated_candidate(self) -> None:
        evaluated: list[float] = []

        def _recording_callback(x: np.ndarray) -> tuple[float, np.ndarray]:
            value, gradient = _quadratic_callback(x)
            evaluated.append(value)
            return value, gradient

        ssbo = SSBO(
            evaluation_callback=_recording_callback,
            bounds=[(0.0, 1.0)],
            kmax=2,
            lhs_candidates=64,
        )
        ssbo.set_initial_samples(*_initial_samples())

        _, _, history = ssbo.optimize()

        # Every iteration must pair each point it tried with that point's own
        # objective value, so the explored-points plot stays correct.
        recorded = [
            point
            for entry in history
            if not entry["skipped"]
            for point in entry["new_points"]
        ]
        recorded_values = [
            value
            for entry in history
            if not entry["skipped"]
            for value in entry["new_values"]
        ]
        assert recorded, "no evaluated points recorded"
        assert len(recorded) == len(recorded_values)
        for point, value in zip(recorded, recorded_values):
            assert isinstance(point, list)
            assert value == pytest.approx(
                float(np.sum((np.asarray(point) - 0.9) ** 2))
            )

    def test_history_falls_back_to_single_candidate_keys(self) -> None:
        ssbo = SSBO(
            evaluation_callback=_quadratic_callback,
            bounds=[(0.0, 1.0)],
            kmax=1,
            lhs_candidates=64,
        )
        ssbo.set_initial_samples(*_initial_samples())

        _, _, history = ssbo.optimize()

        for entry in history:
            if entry["skipped"]:
                continue
            # Legacy keys stay present for consumers that only read them.
            assert "new_point" in entry
            assert "new_value" in entry

    def test_omitting_callback_is_allowed(self) -> None:
        ssbo = SSBO(
            evaluation_callback=_quadratic_callback,
            bounds=[(0.0, 1.0)],
            kmax=2,
            lhs_candidates=64,
        )
        ssbo.set_initial_samples(*_initial_samples())

        best_x, best_y, history = ssbo.optimize()

        assert best_x is not None
        assert best_y < 0.25
        assert len(history) == 3

    def test_failing_callback_does_not_break_optimization(self) -> None:
        calls: list[int] = []

        def _boom(iteration: int, history: list[dict]) -> None:
            calls.append(iteration)
            raise RuntimeError("progress reporting is broken")

        ssbo = SSBO(
            evaluation_callback=_quadratic_callback,
            bounds=[(0.0, 1.0)],
            kmax=2,
            lhs_candidates=64,
            progress_callback=_boom,
        )
        ssbo.set_initial_samples(*_initial_samples())

        best_x, best_y, history = ssbo.optimize()

        assert calls
        assert len(history) == 3
        assert best_y < 0.25
