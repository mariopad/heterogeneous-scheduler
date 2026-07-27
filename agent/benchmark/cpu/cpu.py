"""
agent/benchmark/cpu/cpu.py
"""

import os

# Disable BLAS internal threading
# To ensure np.dot runs in a single thread
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import time
import psutil
import tempfile
import concurrent.futures
import platform
import statistics
import numpy as np

from shared.schemas import (
    NodeCapabilities,
    CPUBenchmarkProfile,
)


####################################
# DEBUGGING
####################################
DEBUG = 1
if DEBUG: 
    repetitions_per_iteration = 1
    iterations = 1
    warmup_iterations = 1
else: 
    repetitions_per_iteration = 5
    iterations = 5
    warmup_iterations = 3


####################################
# CORE JOB
####################################
def _run_cpu_job(A, B, repetitions=10): # Tunear para 1-10 segundos
    result = None
    for _ in range(repetitions):
        result = np.dot(A, B)
    return result

####################################
# SINGLE CORE BENCHMARK
####################################
def benchmark_cpu_single(
    matrix_size=1500,
    warmups=warmup_iterations,
    iterations=iterations,
    repetitions_per_iteration=repetitions_per_iteration,
):
    A = np.random.rand(matrix_size, matrix_size).astype(np.float32)
    B = np.random.rand(matrix_size, matrix_size).astype(np.float32)

    # Warmup
    for _ in range(warmups):
        _run_cpu_job(A, B, repetitions_per_iteration)

    gflops_runs = []
    ops = repetitions_per_iteration * (2 * matrix_size**3)

    for _ in range(iterations):
        start = time.perf_counter()
        _run_cpu_job(A, B, repetitions_per_iteration)
        duration = time.perf_counter() - start

        if duration > 0:
            gflops_runs.append(ops / duration / 1e9)

    return {
        "mean": statistics.mean(gflops_runs),
        "std": statistics.stdev(gflops_runs) if len(gflops_runs) > 1 else 0.0,
    }


####################################
# MULTI CORE BENCHMARK
####################################
def benchmark_cpu_multi(
    capabilities: NodeCapabilities,
    matrix_size=1500,
    warmup=warmup_iterations,
    iterations=iterations,
    repetitions_per_iteration=repetitions_per_iteration,
):
    A = np.random.rand(matrix_size, matrix_size).astype(np.float32)
    B = np.random.rand(matrix_size, matrix_size).astype(np.float32)

    num_cores = capabilities.cpus

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
        for _ in range(warmup):
            futures = [
                executor.submit(_run_cpu_job, A, B, repetitions_per_iteration)
                for _ in range(num_cores)
            ]
            for f in futures:
                f.result()

        gflops_runs = []
        ops = num_cores * repetitions_per_iteration * (2 * matrix_size**3)
        for _ in range(iterations):
            start = time.perf_counter()
            futures = [
                executor.submit(_run_cpu_job, A, B, repetitions_per_iteration)
                for _ in range(num_cores)
            ]
            for f in futures:
                f.result()

            duration = time.perf_counter() - start

            if duration > 0:
                gflops_runs.append(ops / duration / 1e9)

    return {
        "mean": statistics.mean(gflops_runs),
        "std": statistics.stdev(gflops_runs) if len(gflops_runs) > 1 else 0.0,
    }


def benchmark_cpu(capabilities: NodeCapabilities) -> CPUBenchmarkProfile:
    """
    Runs both single-core and multi-core CPU benchmarks
    """
    print(f"[benchmark-cpu] CPU benchmark starting on {platform.machine()}...")
    print(f"[benchmark-cpu] Detected {os.cpu_count()} logical cores")
    
    single = benchmark_cpu_single()
    multi = benchmark_cpu_multi(capabilities)

    single_mean = single["mean"]
    single_std = single["std"]

    multi_mean = multi["mean"]
    multi_std = multi["std"]

    theoretical_max = single_mean * capabilities.physical_cores
    
    scaling_efficiency = (multi_mean / theoretical_max * 100) if theoretical_max > 0 else 0
    
    result = CPUBenchmarkProfile(
        cpu_single_core_gflops_mean=round(single_mean, 2),
        cpu_single_core_gflops_std=round(single_std, 2),

        cpu_node_gflops_mean=round(multi_mean, 2),
        cpu_node_gflops_std=round(multi_std if len(multi) > 1 else 0.0, 2),

        cpu_scaling_efficiency_pct=round(scaling_efficiency, 1),
    )
    
    print(
        f"[benchmark-cpu] CPU single={result.cpu_single_core_gflops_mean}±{result.cpu_single_core_gflops_std} "
        f"multi={result.cpu_node_gflops_mean}±{result.cpu_node_gflops_std} "
        f"eff={result.cpu_scaling_efficiency_pct}%"
    )

    return result