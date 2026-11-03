from .plot import Plot
from .tools.traits_parser import TraitsParser
from .tools.use_wegl import get_scatter_class


class MISO(Plot):
    def description(self) -> str:
        return "The chart displays values of multiple input parameters and their corresponding outputs: actual and predicted by the model. The horizontal axis shows consecutive data samples. You can enable and disable the lines by clicking on them in the legend."

    def fill_figure(self, data, fig, traits):
        x_data = list(range(len(data)))
        y_names = data.columns.tolist()

        config = self.get_config_values(traits, "miso", {"use_webgl": True})
        scatter_class = get_scatter_class(config["use_webgl"])

        styles = self.series_styles(traits, "series")

        # Add one line trace per column
        for idx, y_name in enumerate(y_names):
            trace_options, style = self.resolve_series(
                styles,
                y_name,
                TraitsParser.LINE_STYLE_TRAITS,
                default_hovertemplate=None,
                default_mode="lines",
            )
            name = trace_options.pop("name", y_name)
            fig.add_trace(
                scatter_class(
                    x=x_data,
                    y=data[y_name],
                    name=name,
                    opacity=0.7 if idx < len(y_names) - 1 else 1.0,
                    line=style,
                    **trace_options,
                )
            )

        # Layout: labels + title
        fig.update_layout(
            title="Figure for multiple parameters",
            xaxis_title="Sample index",
            yaxis_title="<br>".join(y_names),
            template="plotly_white",
        )
