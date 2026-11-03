from __future__ import annotations

from dependency_injector import containers, providers

from adapters.evaluator_rest_adapter.config import EvaluatorConfig
from adapters.evaluator_rest_adapter.rest_adapter import RestEvaluatorAdapter
from use_case_contracts.ports import EvaluatorPort


class EvaluatorRestAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    evaluator_config = providers.Factory(
        EvaluatorConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    evaluator_port = providers.Singleton(
        RestEvaluatorAdapter,
        config=evaluator_config,
        http_client=None,
    )


class EvaluatorRestAdapterRoot:
    def __init__(self, container: EvaluatorRestAdapterContainer) -> None:
        self._c = container

    def evaluator_port(self) -> EvaluatorPort:
        return self._c.evaluator_port()
