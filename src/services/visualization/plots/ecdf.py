import pandas as pd
import plotly.graph_objects as go

from .plot import Plot


class Ecdf(Plot):
    def description(self) -> str:
        return (
            "Empirical cumulative distribution functions of behavioural and "
            "non-behavioural samples, one plot per input parameter."
        )

    def fill_figure(self, data, fig, traits):
        # Figures are built per parameter in build_figures().
        return

    def build_figures(self, data, traits) -> list[go.Figure]:
        if data is None or data.empty or "parameter" not in data.columns:
            return [go.Figure()]

        parameters = list(dict.fromkeys(data["parameter"].astype(str)))
        return [
            self._build_parameter_figure(data, parameter)
            for parameter in parameters
        ]

    def _build_parameter_figure(self, data, parameter: str) -> go.Figure:
        param_data = data[data["parameter"].astype(str) == parameter]

        d_statistic = None
        available_d = param_data["d_statistic"].dropna()
        if not available_d.empty:
            d_statistic = float(available_d.iloc[0])

        fig = go.Figure()
        for group, label in (
            ("behavioural", "Behavioural"),
            ("non_behavioural", "Non-behavioural"),
        ):
            group_data = param_data[
                param_data["group"].astype(str).str.strip().str.lower() == group
            ].sort_values("cdf")
            if group_data.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=group_data["x"],
                    y=group_data["cdf"],
                    mode="lines",
                    line=dict(shape="hv", dash="dot" if group == "behavioural" else "solid"),
                    name=label,
                    hovertemplate=(
                        f"<b>{parameter}</b><br>"
                        "x: %{x:.4g}<br>CDF: %{y:.3f}"
                        "<extra></extra>"
                    ),
                )
            )

        if d_statistic is None:
            title = parameter
        else:
            title = f"{parameter}<br><sup>D-stat = {d_statistic:.4f}</sup>"

        fig.update_layout(
            title=title,
            height=400,
            showlegend=True,
            template="plotly_white",
            margin=dict(l=60, r=30, t=70, b=50),
        )
        fig.update_xaxes(title_text=parameter)
        fig.update_yaxes(title_text="CDF", range=[0, 1])
        return fig
