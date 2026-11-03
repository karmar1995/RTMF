from services.front.endpoints.visualization.details.visualize_job_impl import (
    show_visualization_modes as show_visualization_modes_impl,
    begin_visualize_job as begin_visualize_job_impl,
    show_single_time_series_visualization as show_single_time_series_visualization_impl,
    show_multiple_time_series_visualization as show_multiple_time_series_visualization_impl,
    show_multiple_scalar_visualization as show_multiple_scalar_visualization_impl,
    show_time_series_with_parser_visualization as show_time_series_with_parser_visualization_impl,
    show_monte_carlo_filtering_visualization as show_monte_carlo_filtering_visualization_impl,
    get_monte_carlo_filtering_plot_state as get_monte_carlo_filtering_plot_state_impl,
    get_job_plot_state as get_job_plot_state_impl,
    get_job_visualization_status as get_job_visualization_status_impl,
    get_visualization_constant_params as get_visualization_constant_params_impl,
    get_visualization_repetitions as get_visualization_repetitions_impl,
    retry_visualize_job as retry_visualize_job_impl,
    visualize_job as visualize_job_impl,
)


def show_visualization_modes(job_id):
    return show_visualization_modes_impl(job_id)

def begin_visualize_job(job_id):
    return begin_visualize_job_impl(job_id)

def show_single_time_series_visualization(job_id):
    return show_single_time_series_visualization_impl(job_id)

def show_multiple_time_series_visualization(job_id):
    return show_multiple_time_series_visualization_impl(job_id)

def show_multiple_scalar_visualization(job_id):
    return show_multiple_scalar_visualization_impl(job_id)

def show_time_series_with_parser_visualization(job_id):
    return show_time_series_with_parser_visualization_impl(job_id)

def show_monte_carlo_filtering_visualization(job_id):
    return show_monte_carlo_filtering_visualization_impl(job_id)

def get_monte_carlo_filtering_plot_state(job_id, plot_id, scatter_plot_id=None):
    return get_monte_carlo_filtering_plot_state_impl(
        job_id, plot_id, scatter_plot_id
    )

def get_job_plot_state(job_id, plot_id):
    return get_job_plot_state_impl(job_id, plot_id)

def get_job_visualization_status(job_id):
    return get_job_visualization_status_impl(job_id)

def get_visualization_constant_params(job_id, selected_x):
    return get_visualization_constant_params_impl(job_id, selected_x)

def get_visualization_repetitions(job_id):
    return get_visualization_repetitions_impl(job_id)

def retry_visualize_job(job_id):
    return retry_visualize_job_impl(job_id)

def visualize_job(job_id, request):
    return visualize_job_impl(job_id, request)
