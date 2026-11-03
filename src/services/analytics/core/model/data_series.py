from __future__ import annotations

import csv
from dataclasses import dataclass
import io

DataSeriesXValue = str | int | float | bool


@dataclass(frozen=True)
class DataSeries:
    """Serializable representation of one evaluated x/y data series."""

    x_name: str
    y_name: str
    statistic: str
    constants: list[tuple[str, str]]
    x_values: list[DataSeriesXValue]
    y_values: list[float]

    def writeCsv(self) -> str:
        """Return the series as CSV text with one header row."""

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([self.x_name, self.y_name])
        for x_value, y_value in zip(self.x_values, self.y_values, strict=True):
            writer.writerow([x_value, y_value])
        return output.getvalue()


@dataclass(frozen=True)
class MultiDataSeries:
    """Serializable representation of multiple evaluated x/y data series."""

    series: list[DataSeries]

    def writeCsv(self) -> str:
        """Return all series as CSV text with one shared x column."""

        if not self.series:
            return ""

        series_lengths: list[int] = []
        for data_series in self.series:
            if len(data_series.x_values) != len(data_series.y_values):
                raise ValueError("DataSeries x/y value lengths differ")
            series_lengths.append(len(data_series.x_values))

        first_series = self.series[0]
        first_length = series_lengths[0]
        if any(length != first_length for length in series_lengths[1:]):
            raise ValueError("MultiDataSeries contains series with differing lengths")
        if any(data_series.x_name != first_series.x_name for data_series in self.series[1:]):
            raise ValueError("MultiDataSeries contains series with differing x names")
        if any(data_series.x_values != first_series.x_values for data_series in self.series[1:]):
            raise ValueError("MultiDataSeries contains series with differing x values")

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([first_series.x_name, *[data_series.y_name for data_series in self.series]])
        for row_index in range(first_length):
            writer.writerow(
                [first_series.x_values[row_index], *[data_series.y_values[row_index] for data_series in self.series]]
            )
        return output.getvalue()
