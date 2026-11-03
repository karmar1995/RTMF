import pandas as pd
import csv

from services.visualization.enums.plot_type import Plot2DType
from .boxplot import Boxplot
from .scatter import Scatter
from .plot import Plot
from io import StringIO
from .miso import MISO

from .uof_ringplot import UoF_Ringplot
from .bar import Bar
from .ecdf import Ecdf
from .line import Line


class PlotGenerator:
    def __init__(self) -> None:
        self.__active_plot: Plot | None = None
        self.__plots: dict[Plot2DType, Plot] = {
            Plot2DType.BAR: Bar(),
            Plot2DType.BOXPLOT: Boxplot(),
            Plot2DType.ECDF: Ecdf(),
            Plot2DType.LINE: Line(),
            Plot2DType.SCATTER: Scatter(),
            Plot2DType.MISO: MISO(),
            Plot2DType.UOF_RINGPLOT: UoF_Ringplot(),
        }

    def set_plot(self, plot: Plot2DType) -> None:
        self.__active_plot = self.__plots[plot]

    def bytes_to_file(self, data: bytes) -> StringIO:
        return StringIO(data.decode("utf-8"))

    def get_delimeter(self, data: StringIO) -> str:
        sample = data.readline()
        dialect = csv.Sniffer().sniff(sample)
        data.seek(0)  # come back to the top of the "file"
        return dialect.delimiter

    def generate(self, data: bytes, traits) -> str:
        data_as_file = self.bytes_to_file(data)
        delimiter = self.get_delimeter(data_as_file)
        if self.__active_plot:
            return self.__active_plot.generate(
                pd.read_csv(data_as_file, sep=delimiter), traits
            )
        return ""

    @property
    def get_plots_info(self) -> list[dict[Plot2DType | str, str]]:
        return [
            {"name": name, "description": plot.description()}
            for name, plot in self.__plots.items()
        ]
