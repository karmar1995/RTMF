from services.front.endpoints.simulations.details.run_simulation_impl import run_simulation as run_simulation_impl
from services.front.endpoints.simulations.details.run_simulation_impl import get_model_input_params as get_model_input_params_impl
from services.front.endpoints.simulations.details.run_simulation_impl import run_simulation_submit as run_simulation_submit_impl
from services.front.endpoints.simulations.details.run_simulation_impl import get_job_group_status as get_job_group_status_impl
from services.front.endpoints.simulations.details.run_simulation_impl import get_simulation_group_details as get_simulation_group_details_impl
from services.front.endpoints.simulations.details.run_simulation_impl import get_simulation_sub_job_details as get_simulation_sub_job_details_impl

def run_simulation():
    return run_simulation_impl()

def get_model_input_params(modelId):
    return get_model_input_params_impl(modelId)

def run_simulation_submit():
    return run_simulation_submit_impl()

def get_job_group_status(group_id: str):
    return get_job_group_status_impl(group_id)

def get_simulation_group_details(group_id: str):
    return get_simulation_group_details_impl(group_id)

def get_simulation_sub_job_details(job_id: str, sub_job_id: str):
    return get_simulation_sub_job_details_impl(job_id, sub_job_id)
