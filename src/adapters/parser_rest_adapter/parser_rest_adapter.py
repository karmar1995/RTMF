from __future__ import annotations

from adapters.parser_rest_adapter.rest_client import ParserRestClient
from use_case_contracts.dtos import DisasterStageMetrics, DisasterStageRecognitionResult
from use_case_contracts.ports import ParserPort


class RestParserAdapter(ParserPort):
    def __init__(self, client: ParserRestClient) -> None:
        self._client = client

    def recognize_stages(self, time_series_csv_bytes: bytes) -> str:
        return self._client.recognize_stages(time_series_csv_bytes)

    def get_recognition_status(self, recognition_id: str) -> str:
        return self._client.get_recognition_status(recognition_id)

    def get_disaster_stage_recognition(self, recognition_id: str) -> DisasterStageRecognitionResult:
        response = self._client.get_disaster_stage_recognition(recognition_id)
        return DisasterStageRecognitionResult(
            stages=[
                (phase_name, start, end)
                for start, end, phase_name in response.phases
            ],
            metrics=(
                DisasterStageMetrics(**response.metrics)
                if response.metrics is not None
                else None
            ),
        )

    def get_disaster_stages(self, recognition_id: str) -> list[tuple[str, float, float]]:
        return self.get_disaster_stage_recognition(recognition_id).stages

    def recognition_finished_successfully(self, recognition_id: str) -> bool:
        return self._client.get_recognition_status(recognition_id).upper() == "COMPLETED"
