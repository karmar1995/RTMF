from .plot import Plot
from .tools.get_columns_names import get_columns_names
from .tools.traits_parser import TraitsParser
from services.visualization.plots.tools.use_wegl import get_scatter_class


DEFAULT_HOVER_TEMPLATE = "<b>%{y:.2f}</b><extra></extra>"


class Line(Plot):
    def description(self) -> str:
        return "The chart shows how the value of a parameter changes across consecutive data samples."

    def fill_figure(self, data, fig, traits):
        x, y_cols = get_columns_names(data)

        config = self.get_config_values(traits, "series", {"use_webgl": True})
        scatter_class = get_scatter_class(config["use_webgl"])
        styles = self.series_styles(traits, "series")

        # Draw one line trace per output column
        for col in y_cols:
            trace_options, style = self.resolve_series(
                styles,
                col,
                TraitsParser.LINE_STYLE_TRAITS,
                default_hovertemplate=DEFAULT_HOVER_TEMPLATE,
                default_mode="lines",
            )
            name = trace_options.pop("name", col)
            fig.add_trace(
                scatter_class(
                    x=data[x],
                    y=data[col],
                    name=name,
                    line=style,
                    **trace_options,
                )
            )

        # Update layout (axes labels etc.)
        fig.update_layout(
            title=f"Relationship between outputs and {x}",
            xaxis_title=x,
            yaxis_title="<br>".join(y_cols),
            template="plotly_white",
        )
