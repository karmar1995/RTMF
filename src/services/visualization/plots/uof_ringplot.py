import numpy as np
import plotly.graph_objects as go
from plotly.colors import DEFAULT_PLOTLY_COLORS

from .plot import Plot


IMPORTANCE_THRESHOLD = 0.03

INNER_BASE = 0.45
INNER_THICKNESS = 0.1

MIDDLE_BASE = 0.55
MIDDLE_THICKNESS = 0.3

OUTER_BASE = 0.85
OUTER_THICKNESS = 0.15

INNER_DIRECT_COLOR = "#777777"
INNER_INTERACTION_COLOR = "#cccccc"
DETERMINISTIC_COLOR = "#2166ac"
STOCHASTIC_COLOR = "#d7191c"

PATTERN_SIZE = 10
PATTERN_SOLIDITY = 0.3


class UoF_Ringplot(Plot):
    def description(self) -> str:
        return "University of Florida's Visualization."

    def fill_figure(self, data, fig, traits):
        config = self.get_config_values(
            traits, "uof_ringplot", {"output": None, "mode": "det", "color_dic": None}
        )
        output = config["output"]
        mode = config["mode"]
        color_dic = config["color_dic"]

        df = data[data["output"] == output].copy()

        outer = self._compute_outer_ring(df, mode)
        middle = self._compute_middle_ring(df, outer["S_exp"])
        inner = self._compute_inner_ring(df, middle["important"], outer["S_exp"])

        self._add_ring(
            fig,
            base=OUTER_BASE,
            thickness=OUTER_THICKNESS,
            values=outer["values"],
            labels=outer["labels"],
            colors=outer["colors"],
        )

        widths = self._add_middle_ring(
            fig,
            base=MIDDLE_BASE,
            thickness=MIDDLE_THICKNESS,
            values=middle["values"],
            labels=middle["labels"],
            S_exp=outer["S_exp"],
            colors=color_dic,
        )

        self._add_ring(
            fig,
            base=INNER_BASE,
            thickness=INNER_THICKNESS,
            values=inner["values"],
            labels=inner["labels"],
            colors=inner["colors"],
            widths=widths,
        )

        self._update_layout(fig, output, mode)

    def _compute_outer_ring(self, df, mode):
        if mode == "det":
            S_exp = df["S_exp"].mean()

            return {
                "S_exp": S_exp,
                "labels": ["Deterministic", "Stochastic"],
                "values": [S_exp * 100, (1 - S_exp) * 100],
                "colors": [DETERMINISTIC_COLOR, STOCHASTIC_COLOR],
            }

        return {
            "S_exp": 1,
            "labels": ["Stochastic"],
            "values": [100],
            "colors": [STOCHASTIC_COLOR],
        }

    def _compute_middle_ring(self, df, S_exp):
        total_st = df["ST"].sum()

        important = df[df["ST"] > IMPORTANCE_THRESHOLD]

        labels = list(important["input"])
        values = list(important["ST"] * S_exp * 100 / total_st)

        other = (total_st - important["ST"].sum()) * S_exp * 100 / total_st

        if other > 0:
            labels.append("others")
            values.append(other)

        return {
            "important": important,
            "labels": labels,
            "values": values,
        }

    def _compute_inner_ring(self, df, important, S_exp):
        total_st = df["ST"].sum()

        labels = []
        values = []
        colors = []

        direct = important["Si"].clip(lower=0)
        interaction = (important["ST"] - important["Si"]).clip(lower=0)

        for name, d, inter in zip(important["input"], direct, interaction):
            labels.extend([f"{name} direct", f"{name} interaction"])
            values.extend([d * S_exp * 100 / total_st, inter * S_exp * 100 / total_st])
            colors.extend([INNER_DIRECT_COLOR, INNER_INTERACTION_COLOR])

        others = df[~df["input"].isin(important["input"])]

        others_direct = others["Si"].clip(lower=0).sum()
        others_interaction = (others["ST"] - others["Si"]).clip(lower=0).sum()

        labels.extend(["Others direct", "Others interaction"])
        values.extend(
            [
                others_direct * S_exp * 100 / total_st,
                others_interaction * S_exp * 100 / total_st,
            ]
        )
        colors.extend([INNER_DIRECT_COLOR, INNER_INTERACTION_COLOR])

        return {
            "labels": labels,
            "values": values,
            "colors": colors,
        }

    def _add_ring(self, fig, base, thickness, values, labels, colors, widths=None):
        total = np.sum(values)

        if widths is None:
            widths = np.array(values) / total * 360
        else:
            new_widths = []
            for i, angle in enumerate(widths.tolist()):
                temp_width = values[i * 2] + values[i * 2 + 1]
                new_widths.append(values[i * 2] / temp_width * angle)
                new_widths.append(values[i * 2 + 1] / temp_width * angle)
            widths = np.array(new_widths)

        thetas = np.cumsum(widths) - widths / 2

        pattern_map = {
            "Deterministic": self.get_pattern(left=True),
            "Stochastic": self.get_pattern(),
        }

        for label, value, theta, width, color in zip(
            labels, values, thetas, widths, colors
        ):
            trace = fig.add_trace(
                go.Barpolar(
                    r=[thickness],
                    base=[base],
                    theta=[theta],
                    width=[width],
                    customdata=[[label, value]],
                    marker=dict(
                        color=color,
                        line=dict(color="white", width=1),
                        pattern=pattern_map.get(label, None),
                    ),
                    hovertemplate="%{customdata[0]}<br>Value: %{customdata[1]:.3f}<extra></extra>",
                    name=label,
                    showlegend=True,
                )
            )
            if label == "Stochastic":
                trace.data[-1].legendgroup = "Stochastic"

    def get_pattern(self, left: bool = False):
        if left:
            shape = "/"
        else:
            shape = "\\"
        return dict(
            shape=shape,
            fgcolor="white",
            size=PATTERN_SIZE,
            solidity=PATTERN_SOLIDITY,
        )

    def _add_middle_ring(
        self, fig, base, thickness, values, labels, S_exp, colors=None
    ):
        total = np.sum(values)

        widths = np.array(values) / total * (360 * S_exp)
        theta = np.cumsum(widths) - widths / 2

        for i, (label, value) in enumerate(zip(labels, values)):
            if isinstance(colors, dict):
                color = colors.get(
                    label, DEFAULT_PLOTLY_COLORS[i % len(DEFAULT_PLOTLY_COLORS)]
                )
            else:
                color = DEFAULT_PLOTLY_COLORS[i % len(DEFAULT_PLOTLY_COLORS)]

            fig.add_trace(
                go.Barpolar(
                    r=[thickness],
                    base=[base],
                    theta=[theta[i]],
                    width=[widths[i]],
                    customdata=[[label, value]],
                    marker=dict(
                        color=color,
                        line=dict(color="white", width=1),
                    ),
                    hovertemplate="%{customdata[0]}<br>Value: %{customdata[1]:.3f}<extra></extra>",
                    name=label,
                    showlegend=True,
                )
            )

        if S_exp != 1:
            gap_width = 360 * (1 - S_exp)
            gap_theta = 360 * S_exp + gap_width / 2

            fig.add_trace(
                go.Barpolar(
                    r=[thickness],
                    base=[base],
                    theta=[gap_theta],
                    width=[gap_width],
                    marker=dict(
                        color=[STOCHASTIC_COLOR],
                        line=dict(color="white", width=1),
                        pattern=dict(
                            shape="\\",
                            fgcolor="white",
                            size=PATTERN_SIZE,
                            solidity=PATTERN_SOLIDITY,
                        ),
                    ),
                    hoverinfo="skip",
                    name="",
                    legendgroup="Stochastic",
                    showlegend=False,
                )
            )

        return widths

    def _update_layout(self, fig, output, mode):
        fig.update_layout(
            polar=dict(
                radialaxis=dict(visible=False, range=[0, 1]),
                angularaxis=dict(visible=False),
            ),
            showlegend=True,
            margin=dict(t=40, b=20, l=20, r=20),
            title=f"Sensitivity structure for {output} ({mode})",
        )
