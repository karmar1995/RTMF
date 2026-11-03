from abc import ABC, abstractmethod
import plotly.graph_objects as go

from .tools.traits_parser import TraitsParser

FILTER_DICT = {
    "line": TraitsParser.LINE_TRAITS,
    "scatter": TraitsParser.SCATTER_TRAITS,
    "series": TraitsParser.SERIES_TRAITS,
}


class Plot(ABC):
    def generate(self, data, traits) -> str:
        """
        Build and return interactive HTML for the plot.
        """
        parts = [
            self.render_figure(fig, traits)
            for fig in self.build_figures(data, traits)
        ]
        return "\n".join(parts)

    def build_figures(self, data, traits) -> list[go.Figure]:
        fig = go.Figure()
        self.fill_figure(data, fig, traits)
        return [fig]

    def render_figure(self, fig, traits) -> str:
        self.add_annotations(fig, traits)
        self.add_lines(fig, traits)
        self.add_background(fig, traits)
        self._apply_layout_titles(fig, traits)
        return fig.to_html(include_plotlyjs=False, full_html=False)

    def _apply_layout_titles(self, fig, traits):
        layout = next(iter(TraitsParser.get_trait_list(traits, "layout")), None)
        if layout is None:
            return
        updates = {}
        for key in ("title", "xaxis_title", "yaxis_title"):
            value = TraitsParser.get_trait_value(layout, key, None)
            if value is not None:
                updates[key] = value
        if updates:
            fig.update_layout(**updates)

    def add_annotations(self, fig, traits):
        for annotation in TraitsParser.get_trait_list(traits, "annotation"):
            annotation = TraitsParser.filtered_trait(
                annotation, TraitsParser.TEXT_TRAITS
            )
            fig.add_annotation(
                text=TraitsParser.get_trait_value(annotation, "text", ""),
                x=TraitsParser.get_trait_value(annotation, "x", None),
                y=TraitsParser.get_trait_value(annotation, "y", None),
                font=dict(
                    size=TraitsParser.get_trait_value(annotation, "fontsize", 12),
                    color=TraitsParser.get_trait_value(annotation, "color", "black"),
                ),
                showarrow=False,
            )

    def add_lines(self, fig, traits):
        """
        Add lines (vertical/horizontal/diagonal) as shapes.
        """
        traits = TraitsParser.get_trait_list(traits, "line")
        styles = self.get_styles(traits, "line", "orientation")

        for trait in traits:
            orientation = TraitsParser.get_trait_value(trait, "orientation", None)
            if orientation == "vertical":
                style = styles.get("vertical", {})
                x_val = TraitsParser.get_trait_value(trait, "x", None)
                fig.add_shape(
                    type="line",
                    x0=x_val,
                    x1=x_val,
                    y0=0,
                    y1=1,
                    yref="paper",
                    line=style,
                )
            elif orientation == "horizontal":
                style = styles.get("horizontal", {})
                y_val = TraitsParser.get_trait_value(trait, "y", None)
                fig.add_shape(
                    type="line",
                    x0=0,
                    x1=1,
                    xref="paper",
                    y0=y_val,
                    y1=y_val,
                    line=style,
                )
            elif orientation == "diagonal":
                style = styles.get("diagonal", {})
                start = TraitsParser.get_trait_value(trait, "p_start", None)
                end = TraitsParser.get_trait_value(trait, "p_end", None)
                if start and end:
                    fig.add_shape(
                        type="line",
                        x0=start[0],
                        y0=start[1],
                        x1=end[0],
                        y1=end[1],
                        line=style,
                    )

    def add_background(self, fig, traits):
        """
        Add colored background regions as shapes.
        """
        for background in TraitsParser.get_trait_list(traits, "background") or []:
            start = TraitsParser.get_trait_value(background, "start", 0)
            end = TraitsParser.get_trait_value(background, "end", 0)
            color = TraitsParser.get_trait_value(background, "color", "white")
            opacity = TraitsParser.get_trait_value(background, "opacity", 0.2)
            fig.add_shape(
                type="rect",
                x0=start,
                x1=end,
                y0=0,
                y1=1,
                fillcolor=color,
                opacity=opacity,
                layer="below",
                yref="paper",
            )

    def get_config_values(self, traits, name, trait_dict) -> dict:
        first = next(iter(TraitsParser.get_trait_list(traits, name)), {})
        return {
            key: TraitsParser.get_trait_value(first, key, default)
            for key, default in trait_dict.items()
        }

    def get_styles(self, traits, plot_name, trait_name) -> dict:
        styles = {}
        filter = FILTER_DICT.get(plot_name, None)
        if filter is None:
            return styles

        for trait in TraitsParser.get_trait_list(traits, plot_name):
            y_col = TraitsParser.get_trait_value(trait, trait_name, None)

            if y_col is not None:
                styles.setdefault(y_col, {}).update(
                    TraitsParser.filtered_trait(trait, filter)
                )

        return styles

    def series_styles(self, traits, *trait_types) -> dict:
        """
        Collect per-series styles, keyed by column. Later trait types win.
        """
        styles: dict = {}
        for trait_type in trait_types:
            for y_name, style in self.get_styles(traits, trait_type, "y_name").items():
                styles.setdefault(y_name, {}).update(style)
        return styles

    def resolve_series(
        self,
        series_styles: dict,
        column: str,
        style_traits: set,
        *,
        default_hovertemplate: str | None,
        default_mode: str | None = None,
        trace_traits: set | None = None,
    ) -> tuple[dict, dict]:
        """
        Split the per-series trait of a column into trace options and plot style.

        Keys listed in TRACE_TRAITS are passed to the trace itself, the remaining
        accepted keys are nested under the plot's style object (line, marker).
        """
        trait = series_styles.get(column, {})
        trace_options = {}
        style = {}
        allowed_trace_traits = (
            TraitsParser.TRACE_TRAITS if trace_traits is None else trace_traits
        )
        for key, value in trait.items():
            if key in allowed_trace_traits:
                trace_options[key] = value
            elif key in style_traits:
                if key == "line_color":
                    style.setdefault("line", {})["color"] = value
                else:
                    style[key] = value
        if default_hovertemplate is not None:
            trace_options.setdefault("hovertemplate", default_hovertemplate)
        if default_mode is not None:
            trace_options.setdefault("mode", default_mode)
        return trace_options, style

    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    def fill_figure(self, data, fig, traits):
        pass
