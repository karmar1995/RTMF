import pandas as pd
import plotly.graph_objects as go

from .plot import Plot
from .tools.get_columns_names import get_columns_names
from .tools.traits_parser import TraitsParser


DEFAULT_HOVER_TEMPLATE = (
    "<b>%{fullData.name}</b><br>"
    "bin: %{x}<br>"
    "value: %{y:.2f}<extra></extra>"
)


class Boxplot(Plot):
    def description(self) -> str:
        return "The boxplot shows the distribution of outputs values for different values of each input. Each box shows min, Q1, median, Q3, max."

    def fill_figure(self, data, fig, traits):
        x_name, y_names = get_columns_names(data)

        config = self.get_config_values(
            traits, "boxplot", {"colors": None, "n_bins": 5}
        )
        colors = config["colors"]
        n_bins = config["n_bins"]

        # Create bins and grouping
        bins = pd.cut(data[x_name], bins=n_bins)
        grouped = data.groupby(bins, observed=True)

        labels = [str(b) for b in grouped.groups.keys()]
        styles = self.series_styles(traits, "series")

        # Add a box trace for each (output col × bin)
        for yi, y_name in enumerate(y_names):
            # Get all values per bin for y_name
            values_per_bin = [group[y_name].values for _, group in grouped]
            trace_options, style = self.resolve_series(
                styles,
                y_name,
                TraitsParser.BOXPLOT_STYLE_TRAITS,
                default_hovertemplate=DEFAULT_HOVER_TEMPLATE,
                trace_traits=TraitsParser.TRACE_TRAITS - {"mode"},
            )
            style.setdefault("color", colors[yi] if colors else None)
            name = trace_options.pop("name", y_name)

            for label, values in zip(labels, values_per_bin):
                fig.add_trace(
                    go.Box(
                        y=values,
                        x=[label] * len(values),
                        name=name,
                        marker=style,
                        **trace_options,
                    )
                )

        # Layout grouping
        fig.update_layout(
            title=f"Relationship between {x_name} and outputs",
            xaxis_title=x_name,
            yaxis_title="<br>".join(y_names),
            boxmode="group",
            template="plotly_white",
        )
