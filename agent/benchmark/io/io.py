"""
agent/benchmark/io/io.py

Disk I/O benchmarking module (FIO-backed).

This module uses fio as the underlying measurement engine to ensure
reliable, reproducible disk performance metrics across heterogeneous
Unix-like systems.

Metrics:
- Sequential read/write throughput (MB/s)
- Random read/write IOPS
- Completion latency for each of the above

Requirements:
- fio must be installed

Cost
----
An earlier version took roughly 22 minutes per node, against 43 s for the CPU
benchmark and 10 s for memory. Three things caused it, all fixed here:

1. Every one of the four measurements created its own 4 GB file and deleted it
   afterwards, so the dataset was laid out from scratch 4 x REPETITIONS times.
   Laying out 4 GB costs ~60 s on a desktop SSD and dominated everything else.
   One file is now created once and reused by every job.

2. Each job ran `--time_based --runtime=20`, a fixed 20 s regardless of how
   much data that covered. fio already averages over thousands of I/Os, so a
   shorter run gives essentially the same figure; runtime is now configurable
   and defaults to 3 s.

3. The dataset was 4 GB on the assumption that it must outweigh the page
   cache. It does not: every job already runs with `--direct=1`, which
   bypasses the page cache entirely. Size only has to defeat the device's own
   cache, so the default is now 512 MB.

The sequential write measurement doubles as the layout pass, so creating the
file is no longer wasted work.
"""

import json
import os
import shutil
import statistics
import subprocess
import tempfile
from typing import Dict, List

from shared.schemas import IOBenchmarkProfile
from shared.config import Config


def _check_fio_available():
    return shutil.which("fio") is not None


def _warn_if_memory_backed(path: str) -> None:
    """
    Warn when the benchmark directory is not a real disk.

    A tmpfs is RAM. Benchmarking it produces excellent numbers that describe
    memory, get stored as the node's disk profile, and would send I/O-bound
    jobs to whichever node had the smallest disk. Worth a loud warning rather
    than a silently wrong profile.
    """
    try:
        result = subprocess.run(
            ["findmnt", "-no", "FSTYPE", "--target", path],
            capture_output=True, text=True, timeout=5,
        )
        fstype = result.stdout.strip()
    except Exception:
        return

    if fstype in ("tmpfs", "ramfs"):
        print(
            f"[benchmark-disk] WARNING: {path} is {fstype} (memory-backed). "
            "The reported disk figures will describe RAM, not storage. "
            "Set BENCHMARK_IO_DIR to a real disk."
        )


def _job_file(filename: str, size_mb: int, runtime_s: float, ramp_s: float) -> str:
    """
    Build a fio job file running all four measurements over one dataset.

    `stonewall` makes each section wait for the previous one, so the jobs run
    sequentially and do not contend for the device. Running them in a single
    fio invocation also avoids paying process startup four times.

    The first section writes the whole file and so creates it; its throughput
    is the sequential write figure. Every later section reuses that file.

    Durations are emitted in whole milliseconds. fio parses `runtime` as an
    integer and rejects a fractional value with "time_based requires a
    runtime/timeout setting", which silently disables time_based and lets the
    job run over the entire dataset instead -- slow, and not the measurement
    that was asked for.

    ioengine is psync at queue depth 1. An async engine would show a desktop
    SSD at its best, but libaio and io_uring are not dependably available on
    the ARM boards, and a benchmark that only runs on some of the cluster
    cannot be compared across it. Queue depth 1 still separates an SD card
    from an SSD by a wide margin.
    """
    runtime_ms = max(1, int(round(runtime_s * 1000)))
    ramp_ms = max(0, int(round(ramp_s * 1000)))

    return f"""
[global]
filename={filename}
direct=1
ioengine=psync
randrepeat=0
size={size_mb}M

[seq_write]
rw=write
bs=1m

[seq_read]
stonewall
rw=read
bs=1m
time_based=1
runtime={runtime_ms}ms
ramp_time={ramp_ms}ms

[rand_read]
stonewall
rw=randread
bs=4k
time_based=1
runtime={runtime_ms}ms
ramp_time={ramp_ms}ms

[rand_write]
stonewall
rw=randwrite
bs=4k
time_based=1
runtime={runtime_ms}ms
ramp_time={ramp_ms}ms
""".strip()


def _run_fio_suite(filename: str, size_mb: int, runtime_s: float, ramp_s: float) -> Dict:
    """Run all four measurements in one fio invocation, keyed by job name."""
    if not _check_fio_available():
        raise RuntimeError("fio is not installed")

    with tempfile.NamedTemporaryFile("w", suffix=".fio", delete=False) as spec:
        spec.write(_job_file(filename, size_mb, runtime_s, ramp_s))
        spec_path = spec.name

    try:
        result = subprocess.run(
            ["fio", spec_path, "--output-format=json"],
            capture_output=True, text=True, check=True,
        )

        output = result.stdout.strip()
        start = output.find("{")
        if start == -1:
            raise RuntimeError(f"No JSON found in fio output:\n{output}")

        # fio reports a rejected option on stderr, then carries on with that
        # option ignored and still exits 0. Staying quiet about it is how a
        # misconfigured job passes for a valid measurement -- a fractional
        # runtime silently disabled time_based and made every job run over the
        # whole dataset instead. Anything fio complains about is surfaced.
        complaints = "; ".join(
            line.strip()
            for line in dict.fromkeys(result.stderr.strip().splitlines())
            if line.strip()
        )
        if complaints:
            print(f"[benchmark-disk] WARNING: fio reported: {complaints}")

        jobs = json.loads(output[start:])["jobs"]

        for job in jobs:
            if job.get("error"):
                raise RuntimeError(
                    f"fio job {job.get('jobname')} failed with error {job['error']}"
                )

        return {job["jobname"]: job for job in jobs}

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"fio failed:\n{e.stderr}") from e

    finally:
        os.unlink(spec_path)


def _throughput_mbps(job: Dict, direction: str) -> float:
    """fio reports bandwidth in KiB/s."""
    return job[direction]["bw"] / 1024


def _latency_us(job: Dict, direction: str) -> float:
    return job[direction].get("clat_ns", {}).get("mean", 0) / 1000


def _stats(values: List[float]) -> Dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def benchmark_disk():
    """
    Run disk benchmarks and return complete I/O profile.
    """
    size_mb = Config.BENCHMARK_IO_SIZE_MB
    runtime_s = Config.BENCHMARK_IO_RUNTIME_S
    ramp_s = Config.BENCHMARK_IO_RAMP_S
    repetitions = Config.BENCHMARK_IO_REPETITIONS
    directory = Config.BENCHMARK_IO_DIR

    print(
        f"[benchmark-disk] Starting FIO-based disk benchmark "
        f"({size_mb}MB dataset, {runtime_s}s per job, {repetitions} repetition(s))..."
    )

    os.makedirs(directory, exist_ok=True)
    _warn_if_memory_backed(directory)

    filename = os.path.join(directory, "hs-io-benchmark.dat")

    samples: Dict[str, List[float]] = {
        key: [] for key in (
            "seq_read_bw", "seq_read_lat",
            "seq_write_bw", "seq_write_lat",
            "rand_read_iops", "rand_read_lat",
            "rand_write_iops", "rand_write_lat",
        )
    }

    try:
        for _ in range(repetitions):
            jobs = _run_fio_suite(filename, size_mb, runtime_s, ramp_s)

            samples["seq_write_bw"].append(_throughput_mbps(jobs["seq_write"], "write"))
            samples["seq_write_lat"].append(_latency_us(jobs["seq_write"], "write"))

            samples["seq_read_bw"].append(_throughput_mbps(jobs["seq_read"], "read"))
            samples["seq_read_lat"].append(_latency_us(jobs["seq_read"], "read"))

            samples["rand_read_iops"].append(jobs["rand_read"]["read"]["iops"])
            samples["rand_read_lat"].append(_latency_us(jobs["rand_read"], "read"))

            samples["rand_write_iops"].append(jobs["rand_write"]["write"]["iops"])
            samples["rand_write_lat"].append(_latency_us(jobs["rand_write"], "write"))

    finally:
        # The dataset is large; leaving it behind would eat disk on every node.
        if os.path.exists(filename):
            os.remove(filename)

    stats = {key: _stats(values) for key, values in samples.items()}

    result = IOBenchmarkProfile(
        disk_seq_read_mbps_mean=round(stats["seq_read_bw"]["mean"], 2),
        disk_seq_read_mbps_std=round(stats["seq_read_bw"]["std"], 2),
        disk_seq_read_latency_us_mean=round(stats["seq_read_lat"]["mean"], 2),
        disk_seq_read_latency_us_std=round(stats["seq_read_lat"]["std"], 2),

        disk_seq_write_mbps_mean=round(stats["seq_write_bw"]["mean"], 2),
        disk_seq_write_mbps_std=round(stats["seq_write_bw"]["std"], 2),
        disk_seq_write_latency_us_mean=round(stats["seq_write_lat"]["mean"], 2),
        disk_seq_write_latency_us_std=round(stats["seq_write_lat"]["std"], 2),

        disk_rand_read_iops_mean=round(stats["rand_read_iops"]["mean"], 2),
        disk_rand_read_iops_std=round(stats["rand_read_iops"]["std"], 2),
        disk_rand_read_latency_us_mean=round(stats["rand_read_lat"]["mean"], 2),
        disk_rand_read_latency_us_std=round(stats["rand_read_lat"]["std"], 2),

        disk_rand_write_iops_mean=round(stats["rand_write_iops"]["mean"], 2),
        disk_rand_write_iops_std=round(stats["rand_write_iops"]["std"], 2),
        disk_rand_write_latency_us_mean=round(stats["rand_write_lat"]["mean"], 2),
        disk_rand_write_latency_us_std=round(stats["rand_write_lat"]["std"], 2),
    )

    print(f"[benchmark-disk] seq_read={result.disk_seq_read_mbps_mean} ± {result.disk_seq_read_mbps_std} MB/s")
    print(f"[benchmark-disk] seq_write={result.disk_seq_write_mbps_mean} ± {result.disk_seq_write_mbps_std} MB/s")
    print(f"[benchmark-disk] rand_read={result.disk_rand_read_iops_mean} ± {result.disk_rand_read_iops_std} IOPS")
    print(f"[benchmark-disk] rand_write={result.disk_rand_write_iops_mean} ± {result.disk_rand_write_iops_std} IOPS")
    return result
