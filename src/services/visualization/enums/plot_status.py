from enum import Enum


class PlotStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
