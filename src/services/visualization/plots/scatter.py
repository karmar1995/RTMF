from services.visualization.plots.tools.use_wegl import get_scatter_class
from .plot import Plot
from .tools.get_columns_names import get_columns_names
from .tools.traits_parser import TraitsParser


class Scatter(Plot):
    def description(self) -> str:
        return "The scatter plot shows the relationship between outputs and input. Each point represents a single observation."

    def _default_hovertemplate(self, col: str, x_name: str) -> str:
        return (
            f"<b>{col}</b>: %{{y:.2f}}<br>"
            f"<b>{x_name}</b>: %{{x:.2f}}"
            "<extra></extra>"
        )

    def fill_figure(self, data, fig, traits):
        x_name, y_names = get_columns_names(data)

        config = self.get_config_values(traits, "scatter", {"use_webgl": True})
        scatter_class = get_scatter_class(config["use_webgl"])
        styles = self.series_styles(traits, "scatter", "series")

        # Add WebGL scatter traces
        for col in y_names:
            trace_options, style = self.resolve_series(
                styles,
                col,
                TraitsParser.SCATTER_STYLE_TRAITS,
                default_hovertemplate=self._default_hovertemplate(col, x_name),
                default_mode="markers",
            )
            name = trace_options.pop("name", col)
            fig.add_trace(
                scatter_class(
                    x=data[x_name],
                    y=data[col],
                    name=name,
                    marker=style,
                    **trace_options,
                )
            )

        # Update layout
        fig.update_layout(
            title=f"Relationship between outputs and {x_name}",
            xaxis_title=x_name,
            yaxis_title="<br>".join(y_names),
            template="plotly_white",
        )
