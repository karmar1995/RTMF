from __future__ import annotations

from typing import Any

from use_case_contracts.ports import UseCaseAPI


class RemoteUseCaseAdapter(UseCaseAPI):
    def handle(self, message: Any) -> Any:
        raise NotImplementedError("Remote transport adapter not implemented yet.")
