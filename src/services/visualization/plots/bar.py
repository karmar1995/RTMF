import pandas as pd
import plotly.graph_objects as go

from .plot import Plot
from .tools.get_columns_names import get_columns_names
from .tools.traits_parser import TraitsParser
from services.visualization.core.errors import BadAggregation


DEFAULT_HOVER_TEMPLATE = "<b>%{x}</b><br>Value: %{y:.2f}<extra></extra>"


class Bar(Plot):
    def description(self) -> str:
        return "The chart shows the average values of outputs for different values of each input. Hover over the bars for more information."

    def fill_figure(self, data, fig, traits):
        # Split data into x vs multiple Ys
        x_name, y_names = get_columns_names(data)

        config = self.get_config_values(
            traits, "bar", {"agg_type": "mean", "n_bins": 5}
        )
        agg_type = config["agg_type"]
        n_bins = config["n_bins"]

        # Aggregate
        try:
            bins = pd.cut(data[x_name], bins=n_bins)
            groups_mean = data.groupby(bins, observed=True).agg(
                {y: agg_type for y in y_names}
            )
        except (ValueError, TypeError) as e:
            raise BadAggregation(f"Can't aggregate with {agg_type}") from e

        labels = groups_mean.index.astype(str)
        styles = self.series_styles(traits, "series")

        # Create a bar trace for each output
        for y in y_names:
            trace_options, style = self.resolve_series(
                styles,
                y,
                TraitsParser.BAR_STYLE_TRAITS,
                default_hovertemplate=DEFAULT_HOVER_TEMPLATE,
                trace_traits=TraitsParser.TRACE_TRAITS - {"mode"},
            )
            name = trace_options.pop("name", y)
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=groups_mean[y],
                    name=name,
                    marker=style,
                    **trace_options,
                )
            )

        fig.update_layout(
            title=f"Mean values of outputs for {x_name}",
            xaxis_title=x_name,
            yaxis_title="<br>".join(y_names),
            barmode="group",
            template="plotly_white",
            legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
        )
