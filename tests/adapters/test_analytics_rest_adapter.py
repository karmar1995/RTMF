from __future__ import annotations

from adapters.analytics_rest_adapter.config import AnalyticsConfig
from adapters.analytics_rest_adapter.rest_adapter import (
    RestAnalyticsAdapter,
    _monte_carlo_run_from_payload,
)


def test_monte_carlo_run_from_payload_maps_fields() -> None:
    run = _monte_carlo_run_from_payload(
        {
            "index": 3,
            "behavioural": True,
            "parameters": {"A": 1.0},
            "outputs": {"output": 2.5},
        }
    )

    assert run.index == 3
    assert run.behavioural is True
    assert run.parameters == {"A": 1.0}
    assert run.outputs == {"output": 2.5}


def test_monte_carlo_run_from_payload_defaults_to_empty() -> None:
    run = _monte_carlo_run_from_payload({"index": 0})

    assert run.behavioural is False
    assert run.parameters == {}
    assert run.outputs == {}


def test_monte_carlo_response_uses_internal_field_defaults(monkeypatch) -> None:
    adapter = RestAnalyticsAdapter(AnalyticsConfig(base_url="http://analytics"))
    request = {}
    response = {
        "output_column": "output",
        "threshold": 2.0,
        "direction": "greater",
        "aggregation": None,
        "behavioural_count": 2,
        "non_behavioural_count": 1,
        "runs": [
            {
                "index": 0,
                "behavioural": True,
                "parameters": {"A": 0.1},
                "outputs": {"output": 1.0},
            }
        ],
        "parameters": [],
    }

    def request_json(**kwargs):
        request.update(kwargs)
        return response

    monkeypatch.setattr(adapter, "_request_json", request_json)

    result = adapter.analyze_monte_carlo_filtering(
        csv_data="A;output\n0.1;1\n0.2;2\n0.9;3\n",
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        output_aggregations={"output": "max"},
        run_output_columns=["output"],
    )

    assert request["payload"]["output_aggregations"] == {"output": "max"}
    assert request["payload"]["run_output_columns"] == ["output"]
    assert result.runs[0].index == 0
    assert result.runs[0].behavioural is True
    assert result.runs[0].outputs == {"output": 1.0}
