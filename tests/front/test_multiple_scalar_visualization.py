from __future__ import annotations

from services.front.main import app
from use_case_contracts.dtos import ParameterValues
from use_case_contracts.messages import VisualizeJob
from conftest import (
    _FakeUseCases,
    _installed,
)


def test_multiple_scalar_page_renders_with_range_controls() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Multiple Scalar Visualization" in body
    assert "Range" in body
    assert 'name="constant_K"' in body
    assert "Min" in body
    assert "Max" in body
    assert "Step" in body


def test_multiple_scalar_page_uses_repetition_as_x() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'name="x" value="repetition"' in body
    assert '<option value="repetition" selected>repetition</option>' in body


def test_multiple_scalar_page_hides_ts_outputs_guard() -> None:
    usecases = _FakeUseCases(output_params=[("outcome", "float_ts"), ("count", "float")])
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "const keepTimeSeries = false" in body
    assert "outcome" in body
    assert "count" in body


def test_multiple_scalar_page_has_no_repetition_selector() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'name="repetition"' not in body
    assert 'data-role="repetition-range-toggle"' not in body


def test_multiple_scalar_step_input_is_readonly() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert 'data-role="range-step"' in body
    assert 'type="text"' in body
    assert "readonly" in body


def test_multiple_scalar_no_range_checkbox_for_single_value() -> None:
    usecases = _FakeUseCases(constants=ParameterValues(name="K", value=[7]))
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-scalar"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-role="range-toggle"' not in body


def test_multiple_scalar_plot_expands_ranges_into_series() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=multiple-scalar&x=repetition&y=count&stat=none"
            "&plot_type=Line&constant_K=2"
            "&range_K=1&range_K=2&range_K=3"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert message.plot_type == "Line"
    assert len(message.series) == 3
    assert [series.y for series in message.series] == ["count"] * 3
    assert [series.constants["constant_K"] for series in message.series] == ["1", "2", "3"]
    for series in message.series:
        assert series.x == "repetition"
        assert series.statistic == "none"


def test_multiple_scalar_plot_without_ranges_falls_back_to_single_series() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=multiple-scalar&x=repetition&y=count&stat=none"
            "&plot_type=Line&constant_K=2"
        )

    assert response.status_code == 200
    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert len(message.series) == 1
    assert message.series[0].x == "repetition"
    assert message.series[0].constants["constant_K"] == "2"