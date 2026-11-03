import plotly.graph_objects as go


def get_scatter_class(use_webgl):
    return go.Scattergl if use_webgl else go.Scatter
