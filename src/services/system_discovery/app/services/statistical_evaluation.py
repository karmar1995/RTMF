import math
import numpy as np
from scipy.stats import norm
import pandas as pd
from pathlib import Path
import json

# --- Preprocessing ---
def preprocess_data(obs, sim, drop_duplicates=False):
    if not drop_duplicates:
        return obs, sim
    
    data = list(zip(obs, sim))
    unique_data = []
    seen = set()
    for item in data:
        if item not in seen:
            unique_data.append(item)
            seen.add(item)
            
    obs_new = [x[0] for x in unique_data]
    sim_new = [x[1] for x in unique_data]
    return obs_new, sim_new

# --- Mathematical Helpers ---
def lambda_function(t):
    if (abs(t) >= 0) and (abs(t) <= 0.5):
        return 1
    elif (abs(t) >= 0.5) and (abs(t) <= 1):
        return 2 * (1 - abs(t))
    else:
        return 0

def r_function(k, observed):
    n = len(observed)
    average = np.sum(observed) / len(observed)
    values = 0
    for i in range(n - abs(k)):
        values += (observed[i] - average) * (observed[i + abs(k)] - average)
    return values / n

def g_function(w, M, observed):
    values = 0
    for i in range(-M, M):
        values += lambda_function(i / M) * r_function(i, observed) * math.cos(w * i)
    return values

def calculate_optimal_p(observed):
    n = len(observed)
    M = int(n / 2)
    G = 0
    for i in range(-M, M):
        G += lambda_function(i / M) * abs(i) * r_function(i, observed)

    integration_step = 0.01
    g_0 = g_function(0, M, observed)
    D = 4 * (g_0 ** 2)
    values = 0
    w = -math.pi
    while w < math.pi:
        g_w = g_function(w, M, observed)
        values += (1 + math.cos(w)) * (g_w ** 2) * integration_step
        w += integration_step
    values = 2 * values / math.pi
    D = D + values

    if D == 0:
        p = 0.9
    else:
        b = (((2 * (G ** 2)) / D) ** (1 / 3)) * (n ** (1 / 3))
        p = 1 / b
    
    if p >= 1:
        p = 0.9
    return p

# --- Metrics Calculations ---
def compute_nse(obs, sim):
    obs = np.array(obs)
    sim = np.array(sim)
    mean_obs = np.mean(obs)
    num = np.sum((obs - sim) ** 2)
    den = np.sum((obs - mean_obs) ** 2)
    if den == 0:
        return -np.inf
    return 1.0 - num / den

def compute_rmse(obs, sim):
    obs = np.array(obs)
    sim = np.array(sim)
    mse = np.mean((obs - sim) ** 2)
    return float(np.sqrt(mse))

def compute_pbias(obs, sim):
    obs = np.array(obs)
    sim = np.array(sim)
    sum_obs = np.sum(obs)
    if sum_obs == 0:
        return np.nan
    return (np.sum(sim - obs) / sum_obs) * 100

def compute_nrmse(obs, rmse_val):
    obs_std = np.std(obs)
    if obs_std != 0:
        return (rmse_val / obs_std) * 100
    return np.nan

def calculate_metrics(obs, sim):
    nse = compute_nse(obs, sim)
    rmse = compute_rmse(obs, sim)
    pbias = compute_pbias(obs, sim)
    nrmse = compute_nrmse(obs, rmse)
    return {"NSE": nse, "RMSE": rmse, "PBIAS": pbias, "NRMSE": nrmse}

def evaluate_nse_categories(nse_values, threshold=0.65):
    nse_array = np.array(nse_values)
    total = len(nse_array)
    
    very_good = np.sum((nse_array >= 0.900) & (nse_array <= 1.000))
    good = np.sum((nse_array >= 0.800) & (nse_array < 0.900))
    acceptable = np.sum((nse_array >= threshold) & (nse_array < 0.800))
    unsatisfactory = np.sum(nse_array < threshold)
    
    return {
        "very_good": {"label": "Very Good", "range": [0.9, 1.0], "prob": float(very_good / total)},
        "good": {"label": "Good", "range": [0.8, 0.899], "prob": float(good / total)},
        "acceptable": {"label": "Acceptable", "range": [threshold, 0.799], "prob": float(acceptable / total)},
        "unsatisfactory": {"label": "Unsatisfactory", "range": ["-inf", threshold], "prob": float(unsatisfactory / total)}
    }

# --- Bootstrap & Stats ---
def bootstrap(observed, simulated, p, n_resamplings=2000):
    nash_list = []
    rmse_list = []
    n = len(observed)
    
    for i in range(n_resamplings):
        observed_blocks = []
        simulated_blocks = []
        while len(observed_blocks) < n:
            index = np.random.randint(0, n, dtype=int)
            size = np.random.geometric(p)
            
            indices = [(index + k) % n for k in range(size)]
            block_observed = [observed[k] for k in indices]
            block_simulated = [simulated[k] for k in indices]

            observed_blocks += block_observed
            simulated_blocks += block_simulated
            
        observed_sample = np.array(observed_blocks[:n])
        simulated_sample = np.array(simulated_blocks[:n])

        nash_list.append(compute_nse(observed_sample, simulated_sample))
        rmse_list.append(compute_rmse(observed_sample, simulated_sample))
        
    return nash_list, rmse_list

def compute_acceleration(observed, simulated, metric_func):
    n = len(observed)
    jack_vals = []
    
    for i in range(n):
        obs_jack = np.delete(observed, i)
        sim_jack = np.delete(simulated, i)
        jack_vals.append(metric_func(obs_jack, sim_jack))
        
    jack_vals = np.array(jack_vals)
    mean_jack = np.mean(jack_vals)
    
    num = np.sum((mean_jack - jack_vals)**3)
    den = 6 * (np.sum((mean_jack - jack_vals)**2))**1.5
    
    return num / den if den != 0 else 0

def get_bca_ci_values(data, original_value, acceleration_a):
    data_arr = np.array(data)
    n_boots = len(data_arr)

    p0 = np.sum(data_arr < original_value) / n_boots
    if p0 == 0: z0 = -3.0
    elif p0 == 1: z0 = 3.0
    else: z0 = norm.ppf(p0)

    alpha_lower = 0.025
    alpha_upper = 0.975
    
    z_alpha_lower = norm.ppf(alpha_lower)
    z_alpha_upper = norm.ppf(alpha_upper)
    
    def calc_z(z_alpha):
        num = z0 + z_alpha
        den = 1 - acceleration_a * num
        if den == 0: return z0 + num # Fallback
        return z0 + num / den

    pct_lower = norm.cdf(calc_z(z_alpha_lower)) * 100
    pct_upper = norm.cdf(calc_z(z_alpha_upper)) * 100
    
    pct_lower = max(0.0, min(100.0, pct_lower))
    pct_upper = max(0.0, min(100.0, pct_upper))

    conf_start = np.percentile(data_arr, pct_lower)
    conf_end = np.percentile(data_arr, pct_upper)
    
    return [float(conf_start), float(conf_end)]

# --- Main Evaluation Flow ---
def run_evaluation_pipeline(predictions_path: Path, job_dir: Path):
    """
    Reads predictions, computes metrics/bootstrap, and generates metadata.json and cdf.csv.
    """
    df = pd.read_csv(predictions_path)
    if len(df.columns) == 1 and ';' in df.columns[0]:
        df = pd.read_csv(predictions_path, sep=';')
    sim = df['y_sim'].values
    obs = df.iloc[:, -2].values
    
    n_samples = len(obs)
    p = calculate_optimal_p(obs)
    metrics = calculate_metrics(obs, sim)
    
    # Bootstrap
    nashes, rmses = bootstrap(obs, sim, p)
    
    # BCa Confidence Intervals
    acc_nse = compute_acceleration(obs, sim, compute_nse)
    acc_rmse = compute_acceleration(obs, sim, compute_rmse)
    
    nse_ci = get_bca_ci_values(nashes, metrics["NSE"], acc_nse)
    rmse_ci = get_bca_ci_values(rmses, metrics["RMSE"], acc_rmse)
    
    # Categories and p_val
    GOODNESS_THRESHOLD = 0.65
    nse_cats = evaluate_nse_categories(nashes, threshold=GOODNESS_THRESHOLD)
    p_val = np.sum(np.array(nashes) < GOODNESS_THRESHOLD) / len(nashes)
    nse_cats['p_val'] = float(p_val)
    
    # Note for PBIAS
    pbias_note = "Overestimation" if metrics["PBIAS"] > 0 else "Underestimation" if metrics["PBIAS"] < 0 else "Accurate"
    
    # Prepare text summary (analysis) in English
    alpha = 0.05
    is_significant = p_val < alpha
    significance_str = (
        f"statistically significant (p-value = {p_val:.4f} < {alpha})"
        if is_significant
        else f"not statistically significant (p-value = {p_val:.4f} >= {alpha})"
    )
    
    very_good_pct = nse_cats["very_good"]["prob"] * 100
    good_pct = nse_cats["good"]["prob"] * 100
    acceptable_pct = nse_cats["acceptable"]["prob"] * 100
    unsatisfactory_pct = nse_cats["unsatisfactory"]["prob"] * 100

    analysis_text = (
        f"Model evaluation based on {n_samples} samples.\n"
        f"- The Nash-Sutcliffe Efficiency (NSE) is {metrics['NSE']:.4f} with a 95% BCa confidence interval of [{nse_ci[0]:.4f}, {nse_ci[1]:.4f}].\n"
        f"- The Root Mean Square Error (RMSE) is {metrics['RMSE']:.4f} with a 95% BCa confidence interval of [{rmse_ci[0]:.4f}, {rmse_ci[1]:.4f}].\n"
        f"- Bootstrap analysis shows the following probability distribution for the model's NSE:\n"
        f"  * Very Good [0.9, 1.0]: {very_good_pct:.2f}%\n"
        f"  * Good [0.8, 0.899]: {good_pct:.2f}%\n"
        f"  * Acceptable [0.65, 0.799]: {acceptable_pct:.2f}%\n"
        f"  * Unsatisfactory [< 0.65]: {unsatisfactory_pct:.2f}%\n"
        f"- At a significance level of {alpha}, the obtained result is {significance_str}."
    )
    
    # Construct Output JSON
    output_json = {
        "analysis": analysis_text,
        "metrics": {
            "sample_size": n_samples,
            "nse": {
                "val": float(metrics["NSE"]),
                "ci": {
                    "range": nse_ci,
                    "level": 0.95,
                    "type": "BCa"
                }
            },
            "rmse": {
                "val": float(metrics["RMSE"]),
                "ci": {
                    "range": rmse_ci,
                    "level": 0.95,
                    "type": "BCa"
                }
            },
            "nrmse": {
                "val": float(metrics["NRMSE"])
            },
            "pbias": {
                "val": float(metrics["PBIAS"]),
                "note": pbias_note
            }
        },
        "evaluation": {
            "nse": nse_cats
        }
    }
    
    # Save Metadata
    (job_dir / "metadata.json").write_text(json.dumps(output_json, indent=2))
    
    # Save CDF
    x_cdf = np.sort(nashes)
    y_cdf = np.arange(1, len(x_cdf) + 1) / len(x_cdf)
    pd.DataFrame({"x": x_cdf, "y": y_cdf}).to_csv(job_dir / "cdf.csv", index=False, sep=";")
