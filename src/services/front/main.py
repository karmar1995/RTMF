from flask import (
    Flask,
    render_template,
    request,
    url_for,
    flash,
    abort,
    redirect,
    make_response,
)
from services.front.endpoints.simulators.simulators import (
    register_model,
    model_registration_submitted,
    simulator_registration_status,
    registration_details,
    simulators_browse,
    simulator_details,
)
from services.front.endpoints.simulations.run_simulation import (
    run_simulation,
    get_model_input_params,
    run_simulation_submit,
    get_job_group_status,
    get_simulation_group_details,
    get_simulation_sub_job_details,
)
from use_case_contracts.dtos import LoginCompleted
from services.front.navigation import all_sidebar_permissions, visible_sidebar_groups
from services.front.pagination import build_page_items, parse_per_page, parse_positive_int, total_pages as _compute_total_pages
from use_case_contracts.messages import (
    BeginBrowserLogin,
    CompleteBrowserLogin,
    GetCurrentSessionContext,
    GetJobSubJobs,
    ListJobs,
    ListMonitorEntries,
    ListVisualizationJobs,
    Logout,
    RequireAuthenticatedSession,
)
from services.front.endpoints.system_discovery_training import (
    list_training_queue,
    list_system_discovery_simulations,
    list_saved_models,
    remove_saved_model,
    remove_training_queue_entry,
    save_training_model,
    saved_model_details,
    show_training_form,
    system_discovery_simulation_details,
    submit_training_form,
    training_details,
    training_evaluation,
)
from services.front.endpoints.visualization.visualize_job import (
    show_visualization_modes,
    begin_visualize_job,
    show_single_time_series_visualization,
    show_multiple_time_series_visualization,
    show_multiple_scalar_visualization,
    show_time_series_with_parser_visualization,
    show_monte_carlo_filtering_visualization,
    get_monte_carlo_filtering_plot_state,
    get_job_plot_state,
    get_job_visualization_status,
    get_visualization_constant_params,
    get_visualization_repetitions,
    retry_visualize_job,
    visualize_job
)
from services.front.endpoints.evaluations.evaluations import (
    evaluation_run,
    evaluation_params,
    evaluation_submit,
    evaluation_queue,
    evaluation_details,
)
from use_case_contracts.errors import (
    AuthenticationError,
    AuthorizationDeniedError,
    BrowserLoginFailedError,
    IdentityProviderUnavailableError,
    ExternalServiceError,
    UnauthenticatedError,
)

def create_app():
    app = Flask(__name__)
    return app


app = create_app()


@app.before_request
def requireAuthenticatedSession():
    if not app.config.get("AUTH_ENFORCED", False):
        return None
    if request.endpoint in {"static", "onAuthLogin", "onAuthCallback", "onAuthLogout"}:
        return None
    usecases = app.extensions.get("usecases")
    if usecases is None:
        return None
    usecases.handle(RequireAuthenticatedSession())
    return None


@app.context_processor
def injectSidebarNavigation():
    return {"sidebar_groups": _sidebar_groups_for_current_request()}


def _sidebar_groups_for_current_request():
    if not app.config.get("AUTH_ENFORCED", False):
        return visible_sidebar_groups(all_sidebar_permissions())
    usecases = app.extensions.get("usecases")
    if usecases is None:
        return ()
    context = usecases.handle(GetCurrentSessionContext())
    return visible_sidebar_groups(frozenset(context.permissions))


@app.route("/")
def onIndex():
    return render_template("index.html", active_page="home")


@app.get("/auth/login")
def onAuthLogin():
    usecases = app.extensions.get("usecases")
    callback_url = app.config["AUTH_CALLBACK_URL"]
    force_reauthentication = request.args.get("fresh") == "1"
    challenge = usecases.handle(
        BeginBrowserLogin(
            callback_url=callback_url,
            force_reauthentication=force_reauthentication,
        )
    )
    return redirect(challenge.authorization_url)


@app.get("/auth/callback")
def onAuthCallback():
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    usecases = app.extensions.get("usecases")
    result = usecases.handle(CompleteBrowserLogin(authorization_code=code, state=state))
    if not isinstance(result, LoginCompleted):
        abort(500)
    response = make_response(redirect(url_for("onIndex")))
    response.set_cookie(
        app.config["AUTH_SESSION_COOKIE_NAME"],
        result.raw_session_credential,
        max_age=app.config["AUTH_SESSION_COOKIE_MAX_AGE"],
        expires=result.expires_at,
        secure=app.config["AUTH_SESSION_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


@app.post("/auth/logout")
def onAuthLogout():
    usecases = app.extensions.get("usecases")
    try:
        usecases.handle(Logout())
    except UnauthenticatedError:
        pass
    response = make_response(redirect(url_for("onIndex")))
    response.delete_cookie(
        app.config["AUTH_SESSION_COOKIE_NAME"],
        secure=app.config["AUTH_SESSION_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


@app.errorhandler(UnauthenticatedError)
def onUnauthenticated(error):
    if request.method == "GET" and _client_accepts_html():
        return redirect(url_for("onAuthLogin"))
    return ("Authentication is required.", 401)


@app.errorhandler(AuthorizationDeniedError)
def onAuthorizationDenied(error):
    return ("Forbidden.", 403)


@app.errorhandler(BrowserLoginFailedError)
def onBrowserLoginFailed(error):
    response = make_response(redirect(url_for("onAuthLogin", fresh="1")))
    response.delete_cookie(
        app.config["AUTH_SESSION_COOKIE_NAME"],
        secure=app.config["AUTH_SESSION_COOKIE_SECURE"],
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


@app.errorhandler(IdentityProviderUnavailableError)
def onIdentityProviderUnavailable(error):
    return ("Identity provider unavailable.", 503)


def _client_accepts_html() -> bool:
    best = request.accept_mimetypes.best_match(["text/html", "application/json"])
    return best == "text/html" or not request.accept_mimetypes


@app.route("/run_simulation", methods=["GET", "POST"])
def onRunSimulation():
    return run_simulation()


@app.route("/api/models/<model_id>/input-params")
def onSimulationModelInputQuery(model_id):
    return get_model_input_params(model_id)


@app.route("/api/simulation-groups/<group_id>/jobs")
def onSimulationGroupJobs(group_id):
    return get_job_group_status(group_id)


@app.route("/simulation-groups/<group_id>")
def onSimulationGroupDetails(group_id):
    return get_simulation_group_details(group_id)


@app.route("/simulation-jobs/<job_id>/<sub_job_id>")
def onSimulationSubJobDetails(job_id, sub_job_id):
    return get_simulation_sub_job_details(job_id, sub_job_id)


@app.route("/simulation-groups/<job_id>/visualize")
def onSimulationGroupVisualize(job_id):
    return show_visualization_modes(job_id)


@app.route("/simulation-groups/<job_id>/visualize/batch")
def onSimulationGroupBatchVisualize(job_id):
    return begin_visualize_job(job_id)


@app.route("/simulation-groups/<job_id>/visualize/single-time-series")
def onSimulationGroupSingleTimeSeriesVisualize(job_id):
    return show_single_time_series_visualization(job_id)


@app.route("/simulation-groups/<job_id>/visualize/multiple-time-series")
def onSimulationGroupMultipleTimeSeriesVisualize(job_id):
    return show_multiple_time_series_visualization(job_id)


@app.route("/simulation-groups/<job_id>/visualize/multiple-scalar")
def onSimulationGroupMultipleScalarVisualize(job_id):
    return show_multiple_scalar_visualization(job_id)


@app.route("/simulation-groups/<job_id>/visualize/parser")
def onSimulationGroupParserVisualize(job_id):
    return show_time_series_with_parser_visualization(job_id)


@app.route("/simulation-groups/<job_id>/visualize/monte-carlo-filtering")
def onSimulationGroupMonteCarloFilteringVisualize(job_id):
    return show_monte_carlo_filtering_visualization(job_id)


@app.route("/simulation-groups/<job_id>/visualize/retry-results", methods=["POST"])
def onSimulationGroupRetryVisualize(job_id):
    return retry_visualize_job(job_id)


@app.route(
    "/simulation-groups/<job_id>/visualize/monte-carlo-filtering/plots/<string:plot_id>",
    methods=["GET"],
)
@app.route(
    "/simulation-groups/<job_id>/visualize/monte-carlo-filtering/plots/"
    "<string:plot_id>/<string:scatter_plot_id>",
    methods=["GET"],
)
def onSimulationGroupMonteCarloFilteringPlotState(
    job_id, plot_id, scatter_plot_id=None
):
    return get_monte_carlo_filtering_plot_state(job_id, plot_id, scatter_plot_id)


@app.route("/simulation-groups/<job_id>/plot", methods=["GET"])
def onSimulationJobPlot(job_id):
    return visualize_job(job_id, request)

@app.route("/jobs/<job_id>/visualization/constant-params", methods=["GET"])
def visualization_constant_params(job_id):
    selected_x = request.args.get("selected_x")
    res = get_visualization_constant_params(job_id, selected_x)
    return res


@app.route("/jobs/<job_id>/visualization/repetitions", methods=["GET"])
def visualization_repetitions(job_id):
    return get_visualization_repetitions(job_id)


@app.route("/jobs/<job_id>/visualization/status", methods=["GET"])
def visualization_status(job_id):
    return get_job_visualization_status(job_id)


@app.route(
    "/simulation-groups/<job_id>/visualize/plot-state/<string:plot_id>",
    methods=["GET"],
)
def job_plot_state(job_id, plot_id):
    return get_job_plot_state(job_id, plot_id)


@app.route("/register_model")
def onRegisterModel():
    return register_model()

@app.route("/simulators/registration_status")
def onSimulatorRegistrationMonitor():
    return simulator_registration_status()

@app.route("/simulators/browse")
def onSimulatorsBrowse():
    return simulators_browse()

@app.route("/simulators/registrations/<registration_id>")
def onRegistrationDetails(registration_id):
    return registration_details(registration_id)

@app.route("/simulators/<simulator_id>")
def onSimulatorDetails(simulator_id):
    return simulator_details(simulator_id)


@app.route("/simulation_monitor")
def onSimulationMonitor():
    group_id = request.args.get("group_id", type=str)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    waiting_page = parse_positive_int(request.args.get("waiting_page"), default=1)
    running_page = parse_positive_int(request.args.get("running_page"), default=1)
    finished_page = parse_positive_int(request.args.get("finished_page"), default=1)
    if not group_id:
        usecases = app.extensions.get("usecases")
        try:
            entries = usecases.handle(ListMonitorEntries()) if usecases else None
        except (AuthenticationError, ExternalServiceError) as exc:
            flash(str(exc), "warning")
            entries = None
        waiting_jobs = []
        running_jobs = []
        finished_jobs = []
        for group_id_value in entries.simulation_group_ids if entries else []:
            try:
                jobs = usecases.handle(GetJobSubJobs(job_id=group_id_value)) if usecases else []
            except (AuthenticationError, ExternalServiceError) as exc:
                flash(str(exc), "warning")
                jobs = []
            summary = _summarize_group_status(jobs)
            job_entry = {
                "uuid": group_id_value,
                "name": f"Simulation job {group_id_value}",
                "status": summary["status"],
                "success": summary.get("success"),
                "link": url_for("onSimulationGroupDetails", group_id=group_id_value),
            }
            if summary["state"] == "waiting":
                waiting_jobs.append(job_entry)
            elif summary["state"] == "running":
                running_jobs.append(job_entry)
            else:
                finished_jobs.append(job_entry)

        # An evaluation submits one Slurm job per SSBO point; those individual
        # jobs are already filtered out of the simulation list above, so the
        # evaluation appears once as a synthetic parent.
        for evaluation in entries.evaluations if entries else []:
            name = f"Evaluation {evaluation.evaluation_id}"
            if evaluation.model_name:
                name = f"{name} - {evaluation.model_name}"
            job_entry = {
                "uuid": evaluation.evaluation_id,
                "name": name,
                "status": "success" if evaluation.success else (
                    "error" if evaluation.success is False else evaluation.status
                ),
                "success": evaluation.success,
                "link": url_for(
                    "onEvaluationDetails", evaluation_id=evaluation.evaluation_id
                ),
            }
            if evaluation.progress is not None:
                job_entry["progress"] = evaluation.progress
            if evaluation.state == "waiting":
                waiting_jobs.append(job_entry)
            elif evaluation.state == "running":
                running_jobs.append(job_entry)
            else:
                finished_jobs.append(job_entry)

        return render_template(
            "monitor.html",
            active_page='sim_monitor',
            **_monitor_context(
                waiting_jobs,
                running_jobs,
                finished_jobs,
                waiting_page,
                running_page,
                finished_page,
                per_page,
            ),
        )

    usecases = app.extensions.get("usecases")
    try:
        jobs = usecases.handle(GetJobSubJobs(job_id=group_id)) if usecases else []
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        jobs = []
    summary = _summarize_group_status(jobs)
    job_entry = {
        "uuid": group_id,
        "name": f"Simulation job {group_id}",
        "status": summary["status"],
        "success": summary.get("success"),
        "link": url_for("onSimulationGroupDetails", group_id=group_id),
    }

    waiting_jobs = [job_entry] if summary["state"] == "waiting" else []
    running_jobs = [job_entry] if summary["state"] == "running" else []
    finished_jobs = [job_entry] if summary["state"] == "finished" else []

    return render_template(
        "monitor.html",
        active_page='sim_monitor',
        **_monitor_context(
            waiting_jobs,
            running_jobs,
            finished_jobs,
            waiting_page,
            running_page,
            finished_page,
            per_page,
        ),
    )


def _monitor_context(
    waiting_jobs,
    running_jobs,
    finished_jobs,
    waiting_page: int,
    running_page: int,
    finished_page: int,
    per_page: int,
) -> dict:
    waiting = _monitor_column(waiting_jobs, waiting_page, per_page)
    running = _monitor_column(running_jobs, running_page, per_page)
    finished = _monitor_column(finished_jobs, finished_page, per_page)
    return {
        "waiting_jobs": waiting["jobs"],
        "running_jobs": running["jobs"],
        "finished_jobs": finished["jobs"],
        "waiting_total": waiting["total"],
        "running_total": running["total"],
        "finished_total": finished["total"],
        "waiting_total_pages": waiting["total_pages"],
        "running_total_pages": running["total_pages"],
        "finished_total_pages": finished["total_pages"],
        "waiting_page": waiting_page,
        "running_page": running_page,
        "finished_page": finished_page,
        "waiting_page_items": waiting["page_items"],
        "running_page_items": running["page_items"],
        "finished_page_items": finished["page_items"],
        "per_page": per_page,
    }

@app.route("/jobs/<job_uuid>")
def job_detail(job_uuid):
    simulation_runner = app.extensions.get("simulation_runner")
    job = simulation_runner.job(job_uuid) if simulation_runner else None
    if not job:
        abort(404, description=f"Job {job_uuid} not found")
    return render_template("job_detail.html", job=job)


@app.route("/simulation_visualization")
def onSimulationVisualization():
    usecases = app.extensions.get("usecases")
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    jobs = []
    total = 0
    total_pages = 0
    if usecases:
        try:
            _page = usecases.handle(ListVisualizationJobs(page=page, per_page=per_page))
        except (AuthenticationError, ExternalServiceError) as exc:
            flash(str(exc), "warning")
            _page = None
        if _page is not None:
            jobs = [
                {
                    "uuid": job.job_id,
                    "model_name": job.model_name,
                    "start_time": job.created_at,
                    "kind": job.kind,
                    "link": url_for("onSimulationGroupVisualize", job_id=job.job_id),
                }
                for job in _page.jobs
            ]
            total = _page.total
            total_pages = _compute_total_pages(total, per_page)
    return render_template(
        "visualization.html",
        active_page="visualization",
        jobs=jobs,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        page_items=build_page_items(total_pages, page),
    )


@app.route("/register_model", methods=["GET", "POST"])
def onRegisterModelSubmit():
    return register_model()


@app.route("/run_simulation/run", methods=["GET", "POST"])
def onRunSimulationSubmit():
    return run_simulation_submit()


@app.route("/register_model/success")
def onRegistrationSubmitted():
    return model_registration_submitted(request.args.get("name", ""))



@app.get("/system_discovery_register")
def onSystemDiscoveryRegister():
    return render_template(
        "system_discovery_register.html", active_page="system_discovery_register"
    )


@app.get("/system_discovery_train")
def onSystemDiscoveryTrain():
    return show_training_form()


@app.post("/system_discovery_train")
def onSystemDiscoveryTrainSubmit():
    return submit_training_form()


@app.get("/system-discovery/trainings")
def onSystemDiscoveryTrainingQueue():
    return list_training_queue()


@app.get("/system-discovery/training/<training_id>")
def onSystemDiscoveryTrainingDetails(training_id):
    return training_details(training_id)


@app.get("/system-discovery/training/<training_id>/evaluation")
def onSystemDiscoveryTrainingEvaluation(training_id):
    return training_evaluation(training_id)


@app.post("/system-discovery/training/<training_id>/evaluation/save")
def onSystemDiscoveryTrainingEvaluationSave(training_id):
    return save_training_model(training_id)


@app.post("/system-discovery/training/<training_id>/remove")
def onSystemDiscoveryTrainingRemove(training_id):
    return remove_training_queue_entry(training_id)


@app.get("/system-discovery/models")
def onSystemDiscoverySavedModels():
    return list_saved_models()


@app.get("/system-discovery/models/<model_id>")
def onSystemDiscoverySavedModelDetails(model_id):
    return saved_model_details(model_id)


@app.post("/system-discovery/models/<model_id>/remove")
def onSystemDiscoverySavedModelRemove(model_id):
    return remove_saved_model(model_id)


@app.get("/system-discovery/simulations")
def onSystemDiscoverySimulations():
    return list_system_discovery_simulations()


@app.get("/system-discovery/simulations/<simulation_id>")
def onSystemDiscoverySimulationDetails(simulation_id):
    return system_discovery_simulation_details(simulation_id)


@app.route("/evaluation/run", methods=["GET"])
def onEvaluationRun():
    return evaluation_run()


@app.post("/evaluation/run/submit")
def onEvaluationRunSubmit():
    return evaluation_submit()


@app.get("/api/models/<model_id>/evaluation-params")
def onEvaluationModelParams(model_id):
    return evaluation_params(model_id)


@app.get("/evaluations")
def onEvaluationQueue():
    return evaluation_queue()


@app.get("/evaluations/<evaluation_id>")
def onEvaluationDetails(evaluation_id):
    return evaluation_details(evaluation_id)


def _summarize_group_status(jobs):
    if not jobs:
        return {"state": "waiting", "status": "waiting", "success": None}
    statuses = [job.status.lower() for job in jobs]
    if all(status == "waiting" for status in statuses):
        return {"state": "waiting", "status": "waiting", "success": None}
    if any(status in ("waiting", "running") for status in statuses):
        return {"state": "running", "status": "running", "success": None}
    success = all(status == "successful" for status in statuses)
    return {
        "state": "finished",
        "status": "success" if success else "error",
        "success": success,
    }


def _monitor_column(jobs, page: int, per_page: int) -> dict:
    total = len(jobs)
    total_pages = _compute_total_pages(total, per_page)
    start = (page - 1) * per_page
    return {
        "jobs": jobs[start : start + per_page],
        "total": total,
        "total_pages": total_pages,
        "page_items": build_page_items(total_pages, page),
    }
