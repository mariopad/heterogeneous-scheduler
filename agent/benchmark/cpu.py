import time
import psutil
import tempfile
import concurrent.futures
import platform
import statistics

# Disable BLAS internal threading
# To ensure np.dot runs in a single thread
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import numpy as np

def heavy_cpu_task(A, B, repetitions=10): # Tunear para 1-10 segundos
    # Aumentar arbitrariamente el tamaño de la matriz me puede saturar rapido la memoria de la nano
    for _ in range(repetitions):
        result = np.dot(A, B)
    return result

def benchmark_cpu_single(matrix_size=1500, warmups=1, iterations=5, repetitions_per_iteration=1):
    """Score based on sc matrix multiplication"""
    A = np.random.rand(matrix_size, matrix_size).astype(np.float32)
    B = np.random.rand(matrix_size, matrix_size).astype(np.float32)

    # Warmup
    for _ in range(warmups):
        heavy_cpu_task(A, B, repetitions_per_iteration)

    # Measurements
    durations = []
    for _ in range(iterations):
        start = time.perf_counter()
        heavy_cpu_task(A, B, repetitions_per_iteration)
        durations.append(time.perf_counter() - start)

    median_duration = statistics.median(durations) # Robust against outliers

    # The higher the better (matmuls per second)
    #return repetitions_per_iteration / median_duration if median_duration > 0 else 0.0

    operations = repetitions_per_iteration * (2 * matrix_size**3)
    gflops = operations / median_duration / 1e9
    return gflops

def benchmark_cpu_multi(matrix_size=1500, warmup=1, iterations=5, repetitions_per_iteration=1):
    """Score based on mc matrix multiplication"""
    A = np.random.rand(matrix_size, matrix_size).astype(np.float32)
    B = np.random.rand(matrix_size, matrix_size).astype(np.float32)

    num_cores = os.cpu_count() or 1

    # Se libera el GIL! Comprobado
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
        # Warmup
        for _ in range(warmup):
            futures = [executor.submit(heavy_cpu_task, A, B, repetitions_per_iteration) for _ in range(num_cores)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        # Measurements
        durations = []
        for _ in range(iterations):
            start = time.perf_counter()
            futures = [executor.submit(heavy_cpu_task, A, B, repetitions_per_iteration) for _ in range(num_cores)]
            for future in concurrent.futures.as_completed(futures):
                future.result()
            durations.append(time.perf_counter() - start)

    median_duration = statistics.median(durations)

    operations = num_cores * repetitions_per_iteration * (2 * matrix_size**3)
    gflops = operations / median_duration / 1e9
    return gflops


# Pensar en migrarlo
def benchmark_cpu() -> dict:
    """
    Runs both single-core and multi-core CPU benchmarks
    """
    print(f"[benchmark] CPU benchmark starting on {platform.machine()}...")
    print(f"[benchmark] Detected {os.cpu_count()} logical cores")
    
    single_gflops = benchmark_cpu_single()
    multi_gflops = benchmark_cpu_multi()
    
    # Calculate scaling efficiency (how well the CPU scales with cores)
    logical_cores = os.cpu_count() or 1 # psutil.cpu_count(logical = False) -> nucleos fisicos, pensar!
    physical_cores = psutil.cpu_count(logical=False) or logical_cores
    theoretical_max = single_gflops * physical_cores
    scaling_efficiency = (multi_gflops / theoretical_max * 100) if theoretical_max > 0 else 0
    
    results = {
        "cpu_single_core_gflops": round(single_gflops, 2),
        "cpu_multi_core_gflops": round(multi_gflops, 2),
        "physical_cores": physical_cores,
        "logical_cores": logical_cores,
        "cpu_scaling_efficiency_pct": round(scaling_efficiency, 1),
        "architecture": platform.machine()
    }
    
    print(f"[benchmark] CPU scores: single={results['cpu_single_core_gflops']}, "
          f"multi={results['cpu_multi_core_gflops']}, "
          f"efficiency={results['cpu_scaling_efficiency_pct']}%")
    
    return results