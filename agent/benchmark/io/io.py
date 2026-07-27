"""
agent/benchmark/io/io.py

Disk I/O benchmarking module (FIO-backed).

This module uses fio as the underlying measurement engine to ensure
reliable, reproducible disk performance metrics across heterogeneous
Unix-like systems.

Metrics:
- Sequential read throughput (MB/s)
- Sequential write throughput (MB/s)
- Random read/write IOPS

Requirements:
- fio must be installed
"""

import subprocess
import json
import os
import tempfile
import statistics
import psutil
import shutil

from shared.schemas import IOBenchmarkProfile

REPETITIONS = 1


def _check_fio_available():
    return shutil.which("fio") is not None


def _run_fio_job(name, rw, size_gb=4, bs="1m", iodepth=32, runtime=20, direct=1, fsync=0):
    if not _check_fio_available():
        raise RuntimeError("fio is not installed")

    with tempfile.NamedTemporaryFile(dir=".", delete=False) as tmp:
        filename = tmp.name

    cmd = [
        "fio",
        f"--name={name}",
        f"--filename={filename}",
        f"--rw={rw}",
        f"--bs={bs}",
        f"--size={size_gb}G",
        f"--iodepth={iodepth}",
        f"--runtime={runtime}",
        "--time_based",
        f"--direct={direct}",
        f"--fsync={fsync}",
        "--group_reporting",
        "--output-format=json"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        json_start = output.find('{')
        if json_start == -1:
            raise RuntimeError(f"No JSON found in fio output:\n{output}")
        
        json_output = output[json_start:]
        return json.loads(json_output)["jobs"][0]

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"fio failed:\n{e.stderr}") from e
    
    finally:
        if os.path.exists(filename):
            os.remove(filename)


def benchmark_sequential_read(size_gb=4):
    """Returns (throughput_mbps, latency_us)"""
    job = _run_fio_job(
        name="seq_read",
        rw="read",
        size_gb=size_gb,
        bs="1m",
        iodepth=32,
    )

    throughput = job["read"]["bw"] / 1024

    latency_us = (
        job["read"]
        .get("clat_ns", {})
        .get("mean", 0)
        / 1000
    )

    return throughput, latency_us


def benchmark_sequential_write(size_gb=4):
    """Returns (throughput_mbps, latency_us)"""
    job = _run_fio_job(
        name="seq_write",
        rw="write",
        size_gb=size_gb,
        bs="1m",
        iodepth=32,
    )

    throughput = job["write"]["bw"] / 1024

    latency_us = (
        job["write"]
        .get("clat_ns", {})
        .get("mean", 0)
        / 1000
    )

    return throughput, latency_us


def benchmark_random_read(size_gb=4):
    """Returns (iops, latency_us)"""
    job = _run_fio_job(
        name="rand_read",
        rw="randread",
        size_gb=size_gb,
        bs="4k",
        iodepth=64,
    )

    iops = job["read"]["iops"]
    
    latency_us = (
        job["read"]
        .get("clat_ns", {})
        .get("mean", 0)
        / 1000
    )

    return iops, latency_us


def benchmark_random_write(size_gb=4):
    """Returns (iops, latency_us)"""
    job = _run_fio_job(
        name="rand_write",
        rw="randwrite",
        size_gb=size_gb,
        bs="4k",
        iodepth=64,
    )

    iops = job["write"]["iops"]
    
    latency_us = (
        job["write"]
        .get("clat_ns", {})
        .get("mean", 0)
        / 1000
    )

    return iops, latency_us


def _repeat_seq_read(size_gb, repetitions=REPETITIONS):
    """Helper: run sequential read benchmark multiple times, return stats."""
    throughputs = []
    latencies = []
    for _ in range(repetitions):
        tp, lat = benchmark_sequential_read(size_gb)
        throughputs.append(tp)
        latencies.append(lat)
    
    return {
        "throughput_mean": statistics.mean(throughputs),
        "throughput_std": statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0,
        "latency_mean": statistics.mean(latencies),
        "latency_std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    }


def _repeat_seq_write(size_gb, repetitions=REPETITIONS):
    """Helper: run sequential write benchmark multiple times, return stats."""
    throughputs = []
    latencies = []
    for _ in range(repetitions):
        tp, lat = benchmark_sequential_write(size_gb)
        throughputs.append(tp)
        latencies.append(lat)
    
    return {
        "throughput_mean": statistics.mean(throughputs),
        "throughput_std": statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0,
        "latency_mean": statistics.mean(latencies),
        "latency_std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    }


def _repeat_rand_read(size_gb, repetitions=REPETITIONS):
    """Helper: run random read benchmark multiple times, return stats."""
    iops_list = []
    latencies = []
    for _ in range(repetitions):
        iops, lat = benchmark_random_read(size_gb)
        iops_list.append(iops)
        latencies.append(lat)
    
    return {
        "iops_mean": statistics.mean(iops_list),
        "iops_std": statistics.stdev(iops_list) if len(iops_list) > 1 else 0.0,
        "latency_mean": statistics.mean(latencies),
        "latency_std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    }


def _repeat_rand_write(size_gb, repetitions=REPETITIONS):
    """Helper: run random write benchmark multiple times, return stats."""
    iops_list = []
    latencies = []
    for _ in range(repetitions):
        iops, lat = benchmark_random_write(size_gb)
        iops_list.append(iops)
        latencies.append(lat)
    
    return {
        "iops_mean": statistics.mean(iops_list),
        "iops_std": statistics.stdev(iops_list) if len(iops_list) > 1 else 0.0,
        "latency_mean": statistics.mean(latencies),
        "latency_std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    }



def benchmark_disk():
    """
    Run disk benchmarks and return complete I/O profile.
    """
    print("[benchmark-disk] Starting FIO-based disk benchmark...")

    # Adjust dataset size based on available disk space
    try:
        free_gb = psutil.disk_usage(os.getcwd()).free / (1024**3)
        size = 1 if free_gb < 5 else 4
    except Exception:
        size = 4

    # Warmup run
    try:
        _run_fio_job(name="warmup", rw="read", size_gb=1, runtime=5)
    except:
        pass

    # Run benchmarks with repetitions
    seq_read_results = _repeat_seq_read(size, REPETITIONS)
    seq_write_results = _repeat_seq_write(size, REPETITIONS)
    rand_read_results = _repeat_rand_read(size, REPETITIONS)
    rand_write_results = _repeat_rand_write(size, REPETITIONS)

    result = IOBenchmarkProfile(
        disk_seq_read_mbps_mean = round(seq_read_results["throughput_mean"], 2),
        disk_seq_read_mbps_std = round(seq_read_results["throughput_std"], 2),
        disk_seq_read_latency_us_mean = round(seq_read_results["latency_mean"], 2),
        disk_seq_read_latency_us_std = round(seq_read_results["latency_std"], 2),

        disk_seq_write_mbps_mean = round(seq_write_results["throughput_mean"], 2),
        disk_seq_write_mbps_std = round(seq_write_results["throughput_std"], 2),
        disk_seq_write_latency_us_mean = round(seq_write_results["latency_mean"], 2),
        disk_seq_write_latency_us_std = round(seq_write_results["latency_std"], 2),

        disk_rand_read_iops_mean = round(rand_read_results["iops_mean"], 2),
        disk_rand_read_iops_std = round(rand_read_results["iops_std"], 2),
        disk_rand_read_latency_us_mean = round(rand_read_results["latency_mean"], 2),
        disk_rand_read_latency_us_std = round(rand_read_results["latency_std"], 2),

        disk_rand_write_iops_mean = round(rand_write_results["iops_mean"], 2),
        disk_rand_write_iops_std = round(rand_write_results["iops_std"], 2),
        disk_rand_write_latency_us_mean = round(rand_write_results["latency_mean"], 2),
        disk_rand_write_latency_us_std = round(rand_write_results["latency_std"], 2),
    )

    print(f"[benchmark-disk] seq_read={result.disk_seq_read_mbps_mean} ± {result.disk_seq_read_mbps_std} MB/s")
    print(f"[benchmark-disk] seq_write={result.disk_seq_write_mbps_mean} ± {result.disk_seq_write_mbps_std} MB/s")
    print(f"[benchmark-disk] rand_read={result.disk_rand_read_iops_mean} ± {result.disk_rand_read_iops_std} IOPS")
    print(f"[benchmark-disk] rand_write={result.disk_rand_write_iops_mean} ± {result.disk_rand_write_iops_std} IOPS")
    return result