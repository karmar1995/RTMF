from services.front.endpoints.evaluations.details.evaluations_impl import (
    evaluation_details as evaluation_details_impl,
)
from services.front.endpoints.evaluations.details.evaluations_impl import (
    evaluation_params as evaluation_params_impl,
)
from services.front.endpoints.evaluations.details.evaluations_impl import (
    evaluation_queue as evaluation_queue_impl,
)
from services.front.endpoints.evaluations.details.evaluations_impl import (
    evaluation_run as evaluation_run_impl,
)
from services.front.endpoints.evaluations.details.evaluations_impl import (
    evaluation_submit as evaluation_submit_impl,
)


def evaluation_run():
    return evaluation_run_impl()


def evaluation_params(model_id):
    return evaluation_params_impl(model_id)


def evaluation_submit():
    return evaluation_submit_impl()


def evaluation_queue():
    return evaluation_queue_impl()


def evaluation_details(evaluation_id):
    return evaluation_details_impl(evaluation_id)
