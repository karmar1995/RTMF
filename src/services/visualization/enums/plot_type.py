from enum import Enum


class Plot2DType(str, Enum):
    BAR = "Bar"
    BOXPLOT = "Boxplot"
    ECDF = "ECDF"
    LINE = "Line"
    MISO = "MISO"
    SCATTER = "Scatter"
    UOF_RINGPLOT = "University of Florida Ringplot"
