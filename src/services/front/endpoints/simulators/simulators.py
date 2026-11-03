from services.front.endpoints.simulators.details.register_model_impl import register_model as register_model_impl
from services.front.endpoints.simulators.details.registrations_impl import (
    recent_registrations as recent_registrations_impl,
    registration_details as registration_details_impl,
)
from services.front.endpoints.simulators.details.simulators_browse_impl import (
    simulators_browse as simulators_browse_impl,
    simulator_details as simulator_details_impl,
)

def register_model():
    return register_model_impl()

def model_registration_submitted(modelName):
    return f"✅ Registered model: {modelName}"

def simulator_registration_status():
    return recent_registrations_impl()

def registration_details(registration_id: str):
    return registration_details_impl(registration_id)

def simulators_browse():
    return simulators_browse_impl()

def simulator_details(simulator_id: str):
    return simulator_details_impl(simulator_id)
