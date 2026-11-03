import csv
import io
import time
import uuid
import zipfile

from use_case_contracts.dtos import DisasterStageRecognitionResult
from use_case_contracts.ports import ParserPort


class FakeParser(ParserPort):
    def __init__(self):
        self._recognitions: dict[str, dict] = {}

    def recognize_stages(self, time_series_csv_bytes: bytes) -> str:
        stages = self._analyze_csv(time_series_csv_bytes)
        recognition_id = uuid.uuid4().hex
        self._recognitions[recognition_id] = {
            "status": "PROCESSING",
            "start_time": time.time(),
            "stages": stages,
        }
        return recognition_id

    def get_recognition_status(self, recognition_id: str) -> str:
        entry = self._recognitions.get(recognition_id)
        if entry is None:
            return "UNKNOWN"
        return "COMPLETED"

    def get_disaster_stages(self, recognition_id: str) -> list[tuple[str, float, float]]:
        entry = self._recognitions.get(recognition_id)
        if entry is None:
            return []
        return entry["stages"]

    def get_disaster_stage_recognition(self, recognition_id: str) -> DisasterStageRecognitionResult:
        return DisasterStageRecognitionResult(stages=self.get_disaster_stages(recognition_id))

    def recognition_finished_successfully(self, recognition_id: str) -> bool:
        entry = self._recognitions.get(recognition_id)
        return entry is not None and entry["status"] == "COMPLETED"

    @staticmethod
    def _analyze_csv(csv_bytes: bytes) -> list[tuple[str, float, float]]:
        try:
            with zipfile.ZipFile(io.BytesIO(csv_bytes), mode="r") as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if not names:
                    return _default_stages()
                content = zf.read(names[0]).decode("utf-8")
        except Exception:
            return _default_stages()

        reader = csv.DictReader(io.StringIO(content))
        steps = []
        values = []
        for row in reader:
            try:
                steps.append(float(row.get("step", 0)))
                values.append(float(row.get("result_x", 0)))
            except (ValueError, TypeError):
                continue

        if not values:
            return _default_stages()

        threshold = 0.5
        failure_regions = []
        in_failure = False
        start = 0.0

        for i, v in enumerate(values):
            if v < threshold and not in_failure:
                in_failure = True
                start = steps[i]
            elif v >= threshold and in_failure:
                in_failure = False
                failure_regions.append((start, steps[i]))

        if in_failure:
            failure_regions.append((start, steps[-1]))

        if not failure_regions:
            return _default_stages()

        total_start = steps[0]
        total_end = steps[-1]
        first_failure_start = failure_regions[0][0]
        last_failure_end = failure_regions[-1][1]

        stages = []
        if first_failure_start > total_start:
            stages.append(("normal", total_start, first_failure_start))
        for fs, fe in failure_regions:
            stages.append(("failure", fs, fe))
        if last_failure_end < total_end:
            stages.append(("recovery", last_failure_end, total_end))

        return stages


def _default_stages() -> list[tuple[str, float, float]]:
    return [
        ("normal", 0.0, 15.0),
        ("failure", 15.0, 35.0),
        ("recovery", 35.0, 50.0),
    ]
