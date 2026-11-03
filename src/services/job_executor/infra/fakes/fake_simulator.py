#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import random
from pathlib import Path
from services.job_executor.infra.fakes.parse_matrix import load_matrix_bytes

def _to_number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return sum(ord(ch) for ch in value) / 100.0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: fake_simulator.py <matrix_file> <row_number>", file=sys.stderr)
        return 2

    matrix_file = argv[1]
    row = int(argv[2])
    with open(matrix_file, 'rb') as f:
        matrix_bytes = f.read()

    matrix = load_matrix_bytes(matrix_bytes)
    reps = matrix.repetitions

    results_dir = Path("results")
    results_dir.mkdir(parents=True, exist_ok=True)
    results = []

    print(f"Running simulation for: {reps}, params: {matrix.rows[row].params}")

    for rep in range(reps):
        param_numbers = [_to_number(p) for p in matrix.rows[row].params]

        avg_latency = round(random.random() * param_numbers[0] + 0.5, 6)

        timeseries_name = f"results_{rep}.csv"
        timeseries_path = results_dir / timeseries_name

        with timeseries_path.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["time", "packet_delivery_probability"])
            for t in range(100000):
                value = random.random() * param_numbers[1]
                value = round(value, 6)
                writer.writerow([t, value])

        results.append([rep, avg_latency, timeseries_name])

    results_path = results_dir / "results.csv"
    with results_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["repetition", "avg_latency", "packet_delivery_probability"])
        for result in results:
            writer.writerow(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
