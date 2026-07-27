"""
Benchmark orchestration module.

Coordinates the execution of all hardware benchmarks and aggregates results.
"""

import platform
import psutil

from agent.benchmark.cpu import benchmark_cpu
from agent.benchmark.memory import benchmark_memory
from agent.benchmark.io import benchmark_disk
from agent.benchmark.gpu import benchmark_gpu


# agent/benchmark/runner.py

def run_full_benchmark(capabilities) -> dict:
    """
    Orchestrate all benchmarks and return unified result.
    """
    print(f"\n{'='*60}")
    print(f"[benchmark] Starting full hardware benchmark")
    print(f"{'='*60}\n")
    
    results = {}
    
    # CPU
    print("[benchmark] Running CPU benchmark...")
    try:
        results["cpu"] = benchmark_cpu(capabilities)
    except Exception as e:
        print(f"[benchmark] ERROR in CPU benchmark: {e}")
    
    # Disk I/O
    print("[benchmark] Running Disk I/O benchmark...")
    try:
        results["io"] = benchmark_disk()
    except Exception as e:
        print(f"[benchmark] ERROR in Disk benchmark: {e}")
    
    # Memory
    print("[benchmark] Running Memory benchmark...")
    try:
        results["memory"] = benchmark_memory()
    except Exception as e:
        print(f"[benchmark] ERROR in Memory benchmark: {e}")
    
    # GPU
    print("[benchmark] Running GPU detection...")
    try:
        results["gpu"] = benchmark_gpu()
    except Exception as e:
        print(f"[benchmark] ERROR in GPU benchmark: {e}")
    
    print(f"\n{'='*60}")
    print(f"[benchmark] Benchmark complete!")
    print(f"{'='*60}\n")
    
    return results