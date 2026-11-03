from services.evaluator.core.details.strategies import ParameterStrategy
from use_case_contracts.ports import EvaluatorPort
from services.evaluator.core.details.evaluator_controller import (
    EvaluatorController,
    EvaluatorDependencies,
)


class EvaluatorCompositionRoot:
    def __init__(
        self, deps: EvaluatorDependencies, strategy: ParameterStrategy | None = None
    ):
        self.__controller = EvaluatorController(deps, strategy=strategy)

    def evaluator_port(self) -> EvaluatorPort:
        return self.__controller
