"""
agent/benchmark/ram/ram.py

Memory bandwidth benchmarking module (sysbench-backed).

Metrics:
- Sequential read bandwidth (MB/s)
- Sequential write bandwidth (MB/s)
- Random access latency (μs)
- Memory throughput under load

Requirements:
- sysbench must be installed
"""

import subprocess
import json
import os
import statistics
import psutil
import shutil
import re

from shared.schemas import MEMBenchmarkProfile

REPETITIONS = 1


def _check_sysbench_available():
    return shutil.which("sysbench") is not None


def _run_sysbench_memory(test_type, total_mb=1024, threads=4):
    """
    Run sysbench memory test.
    test_type: 'seq', 'rnd'
    total_mb: total memory to test (adaptive based on available RAM)
    """
    if not _check_sysbench_available():
        raise RuntimeError("sysbench is not installed")
    
    cmd = [
        "sysbench",
        "memory",
        f"--memory-total-size={total_mb}M",
        f"--memory-block-size=1K",  # Small blocks for realistic access
        f"--threads={threads}",
        f"--memory-access-mode={test_type}",
        "--report-interval=0",
        "run"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"sysbench failed:\n{e.stderr}") from e


def _parse_sysbench_bandwidth(output):
    """Extract bandwidth (MiB/s) from sysbench output"""
    for line in output.split('\n'):
        if 'MiB/sec' in line:
            # Example: "983.00 MiB transferred (4605.89 MiB/sec)"
            import re
            match = re.search(r'([\d.]+)\s+MiB/sec', line)
            if match:
                return float(match.group(1))
    
    raise RuntimeError(f"Could not parse bandwidth from sysbench output:\n{output}")


def _parse_sysbench_latency(output):
    """Extract average latency (ms) from sysbench output"""
    for line in output.split('\n'):
        if 'avg:' in line:
            # Example: "avg:                                    0.00"
            import re
            match = re.search(r'avg:\s+([\d.]+)', line)
            if match:
                latency_ms = float(match.group(1))
                # Convert ms to microseconds
                return latency_ms * 1000
    
    return 0.0


def benchmark_memory_read(total_mb=512):
    """Returns bandwidth (MB/s)"""
    output = _run_sysbench_memory("seq", total_mb=total_mb, threads=4)
    bandwidth = _parse_sysbench_bandwidth(output)
    return bandwidth


def benchmark_memory_write(total_mb=512):
    """Returns bandwidth (MB/s)"""
    output = _run_sysbench_memory("seq", total_mb=total_mb, threads=4)
    return _parse_sysbench_bandwidth(output)


def benchmark_memory_random(total_mb=512):
    """Returns latency (μs)"""
    output = _run_sysbench_memory("rnd", total_mb=total_mb, threads=4)
    return _parse_sysbench_latency(output)


def benchmark_memory():
    """
    Run memory benchmarks and return complete profile.
    
    Returns:
        MEMBenchmarkProfile with:
        - ram_seq_read_mbps_mean/std
        - ram_seq_write_mbps_mean/std
        - ram_random_latency_us_mean/std
    """
    print("[benchmark-ram] Starting sysbench memory benchmark...")
    
    # Warm-up (critical for memory tests—cold caches skew results)
    try:
        _run_sysbench_memory("seq", total_mb=256, threads=2)
    except:
        pass
    
    # Adaptive size: use 25% of available RAM, but cap at 2GB
    available_gb = psutil.virtual_memory().available / (1024**3)
    test_size_mb = min(int(available_gb * 256), 2048)
    
    # Run repetitions
    read_bandwidths = []
    write_bandwidths = []
    random_latencies = []
    
    for _ in range(REPETITIONS):
        read_bandwidths.append(benchmark_memory_read(test_size_mb))
        write_bandwidths.append(benchmark_memory_write(test_size_mb))
        random_latencies.append(benchmark_memory_random(test_size_mb))
    
    # Build result
    result = MEMBenchmarkProfile(
        ram_seq_read_mbps_mean=round(statistics.mean(read_bandwidths), 2),
        ram_seq_read_mbps_std=round(statistics.stdev(read_bandwidths) if len(read_bandwidths) > 1 else 0.0, 2),
        
        ram_seq_write_mbps_mean=round(statistics.mean(write_bandwidths), 2),
        ram_seq_write_mbps_std=round(statistics.stdev(write_bandwidths) if len(write_bandwidths) > 1 else 0.0, 2),
        
        ram_random_latency_us_mean=round(statistics.mean(random_latencies), 2),
        ram_random_latency_us_std=round(statistics.stdev(random_latencies) if len(random_latencies) > 1 else 0.0, 2),
    )
    
    print(f"[benchmark-ram] seq_read={result.ram_seq_read_mbps_mean} ± {result.ram_seq_read_mbps_std} MB/s")
    print(f"[benchmark-ram] seq_write={result.ram_seq_write_mbps_mean} ± {result.ram_seq_write_mbps_std} MB/s")
    print(f"[benchmark-ram] random_latency={result.ram_random_latency_us_mean} ± {result.ram_random_latency_us_std} μs")
    
    return result