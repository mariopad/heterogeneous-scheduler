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


def run_full_benchmark(capabilities) -> dict:
    """
    Runs all hardware benchmarks and returns a unified dictionary of results.
    
    This function orchestrates the execution of CPU, memory, disk, and GPU
    benchmarks in sequence. Each benchmark is independent and can also be
    run individually if needed.
    
    Returns:
        Dictionary containing all benchmark results and node metadata:
        - CPU: single/multi-core GFLOPS, core counts, scaling efficiency
        - Memory: bandwidth in GB/s
        - Disk: I/O throughput in MB/s
        - GPU: compute GFLOPS (if available)
        - Metadata: architecture, hostname, total memory
    """
    print(f"\n{'='*60}")
    print(f"[benchmark] Starting full hardware benchmark")
    print(f"[benchmark] Architecture: {platform.machine()}")
    print(f"[benchmark] Hostname: {platform.node()}")
    print(f"{'='*60}\n")
    
    results = {}
    
    # Run each benchmark in sequence
    # Each benchmark returns a dict that we merge into results
    benchmarks = [
        ("CPU", benchmark_cpu(capabilities)),
        #("Memory", benchmark_memory),
        ("Disk", benchmark_disk),
        #("GPU", benchmark_gpu),
    ]
    
    for name, benchmark_fn in benchmarks:
        print(f"\n[benchmark] Running {name} benchmark...")
        try:
            benchmark_results = benchmark_fn()
            results.update(benchmark_results)
        except Exception as e:
            print(f"[benchmark] ERROR in {name} benchmark: {e}")
            # Continue with other benchmarks even if one fails
    
    # Add node metadata
    results["architecture"] = platform.machine()
    results["hostname"] = platform.node()
    results["total_memory_mb"] = int(psutil.virtual_memory().total / (1024 * 1024))
    
    print(f"\n{'='*60}")
    print(f"[benchmark] Benchmark complete!")
    print(f"[benchmark] Summary:")
    for key, value in results.items():
        print(f"  {key}: {value}")
    print(f"{'='*60}\n")
    
    return results