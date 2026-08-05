"""
agent/benchmark/memory/memory.py

Memory bandwidth benchmarking module (sysbench-backed).

Metrics:
- Sequential read bandwidth (MB/s)
- Sequential write bandwidth (MB/s)
- Random access latency (us)

Requirements:
- sysbench must be installed

Correctness notes
-----------------
Two things were wrong here and both produced numbers that looked plausible:

1. The read and write helpers built the *same* command. Neither passed
   `--memory-oper`, so sysbench used its default (write) for both, and the
   reported "read bandwidth" was a second write measurement. The two figures
   differed only by run-to-run noise. On this machine the real gap is large --
   about 7700 MiB/s reading against 3900 MiB/s writing -- so the profile was
   both wrong and misleadingly narrow.

2. Random latency was parsed from sysbench's `avg:` field, which is printed in
   milliseconds to two decimals. Memory operations take well under 0.01 ms, so
   that field is always 0.00 and the profile reported either 0 or, after the
   unit conversion, a flat 10 us. It was measuring the print resolution.
   Latency is now derived from the accumulated `sum:` over the event count,
   which keeps five significant figures and resolves microseconds properly.
"""

import os
import re
import shutil
import statistics
import subprocess
from typing import Dict

import psutil

from shared.schemas import MEMBenchmarkProfile
from shared.config import Config

REPETITIONS = Config.BENCHMARK_REPETITIONS


def _check_sysbench_available():
    return shutil.which("sysbench") is not None


def _thread_count() -> int:
    """
    Threads used for the bandwidth runs.

    Capped at the node's core count: asking for four threads on a two-core
    board oversubscribes it and measures scheduling contention rather than
    memory.
    """
    return max(1, min(Config.BENCHMARK_MEM_THREADS, os.cpu_count() or 1))


def _run_sysbench_memory(
    oper: str,
    access_mode: str = "seq",
    total_mb: int = 1024,
    threads: int = None,
) -> Dict[str, float]:
    """
    Run one sysbench memory test and return its parsed measurements.

    Args:
        oper: 'read' or 'write'. Must be passed explicitly -- sysbench
              defaults to write, which is what silently collapsed the read and
              write measurements into one.
        access_mode: 'seq' or 'rnd'.
        total_mb: Total memory moved during the test.
        threads: Concurrent threads; defaults to the capped core count.
    """
    if not _check_sysbench_available():
        raise RuntimeError("sysbench is not installed")

    if oper not in ("read", "write"):
        raise ValueError(f"oper must be 'read' or 'write', got {oper!r}")

    if threads is None:
        threads = _thread_count()

    cmd = [
        "sysbench",
        "memory",
        f"--memory-total-size={total_mb}M",
        "--memory-block-size=1K",  # Small blocks for realistic access
        f"--threads={threads}",
        f"--memory-oper={oper}",
        f"--memory-access-mode={access_mode}",
        "--report-interval=0",
        "run",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"sysbench failed:\n{e.stderr}") from e

    return _parse_sysbench(result.stdout, threads)


def _parse_sysbench(output: str, threads: int) -> Dict[str, float]:
    """Extract bandwidth, event count and accumulated latency from sysbench."""
    bandwidth = re.search(r"([\d.]+)\s+MiB/sec", output)
    if not bandwidth:
        raise RuntimeError(f"Could not parse bandwidth from sysbench output:\n{output}")

    events = re.search(r"total number of events:\s+(\d+)", output)
    latency_sum = re.search(r"sum:\s+([\d.]+)", output)

    parsed = {
        "bandwidth_mibs": float(bandwidth.group(1)),
        "threads": threads,
        "events": float(events.group(1)) if events else 0.0,
        "latency_sum_ms": float(latency_sum.group(1)) if latency_sum else 0.0,
    }

    # Mean time per operation. Taken from the accumulated latency rather than
    # sysbench's own `avg:` field, which is quantised to 0.01 ms and cannot
    # resolve an event this short.
    if parsed["events"] > 0 and parsed["latency_sum_ms"] > 0:
        parsed["latency_us"] = parsed["latency_sum_ms"] * 1000 / parsed["events"]
    else:
        parsed["latency_us"] = 0.0

    return parsed


def benchmark_memory_read(total_mb=512):
    """Returns sequential read bandwidth (MiB/s)."""
    return _run_sysbench_memory("read", "seq", total_mb)["bandwidth_mibs"]


def benchmark_memory_write(total_mb=512):
    """Returns sequential write bandwidth (MiB/s)."""
    return _run_sysbench_memory("write", "seq", total_mb)["bandwidth_mibs"]


def benchmark_memory_random(total_mb=512):
    """
    Returns mean random-access latency (us).

    This is the mean time for one random 1 KiB block read, not a DRAM
    row-activation latency: sysbench walks blocks rather than chasing
    pointers, so hardware prefetching still helps it. It is nonetheless a
    consistent, well-resolved figure for comparing nodes.
    """
    return _run_sysbench_memory("read", "rnd", total_mb)["latency_us"]


def _test_size_mb() -> int:
    """
    Working set for the benchmark: a quarter of available RAM, capped at 2 GB.

    Large enough to overflow cache on every board in the cluster, small enough
    not to push a 2 GB Jetson into swap.
    """
    available_mb = psutil.virtual_memory().available / (1024 ** 2)
    return max(128, min(int(available_mb * 0.25), 2048))


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

    test_size_mb = _test_size_mb()

    # Warm up so the first timed run does not pay for page faults on a
    # freshly allocated buffer.
    try:
        _run_sysbench_memory("write", "seq", total_mb=256, threads=2)
    except Exception as e:
        print(f"[benchmark-ram] warmup skipped: {e}")

    read_bandwidths = []
    write_bandwidths = []
    random_latencies = []

    for _ in range(REPETITIONS):
        read_bandwidths.append(benchmark_memory_read(test_size_mb))
        write_bandwidths.append(benchmark_memory_write(test_size_mb))
        random_latencies.append(benchmark_memory_random(test_size_mb))

    def stats(values):
        return (
            statistics.mean(values),
            statistics.stdev(values) if len(values) > 1 else 0.0,
        )

    read_mean, read_std = stats(read_bandwidths)
    write_mean, write_std = stats(write_bandwidths)
    latency_mean, latency_std = stats(random_latencies)

    result = MEMBenchmarkProfile(
        ram_seq_read_mbps_mean=round(read_mean, 2),
        ram_seq_read_mbps_std=round(read_std, 2),

        ram_seq_write_mbps_mean=round(write_mean, 2),
        ram_seq_write_mbps_std=round(write_std, 2),

        ram_random_latency_us_mean=round(latency_mean, 3),
        ram_random_latency_us_std=round(latency_std, 3),
    )

    print(f"[benchmark-ram] threads={_thread_count()} working_set={test_size_mb}MB")
    print(f"[benchmark-ram] seq_read={result.ram_seq_read_mbps_mean} ± {result.ram_seq_read_mbps_std} MB/s")
    print(f"[benchmark-ram] seq_write={result.ram_seq_write_mbps_mean} ± {result.ram_seq_write_mbps_std} MB/s")
    print(f"[benchmark-ram] random_latency={result.ram_random_latency_us_mean} ± {result.ram_random_latency_us_std} μs")

    return result
