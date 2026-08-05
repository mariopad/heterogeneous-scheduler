"""
I/O-bound workload: sequential write with fsync, then random reads.

Stdlib only, so it runs anywhere. This is the workload that should separate an
SSD-backed desktop from a Raspberry Pi running off an SD card, which is one of
the sharpest hardware differences in the target cluster and is invisible to
any CPU-only trace.

fsync is what makes the write phase honest: without it the measurement is of
the page cache, and every node looks equally fast.
"""

import os
import random
import tempfile
import time
from typing import Dict


CHUNK_BYTES = 1024 * 1024
READ_BLOCK = 4096


def run(size: int, seed: int = 0) -> Dict:
    """
    Write `size` MiB, fsync it, then perform random reads over it.

    Args:
        size: Bytes written, in MiB.
        seed: Fixes the random read offsets so runs are comparable.

    Returns:
        Write throughput, random read IOPS and the raw timings.
    """
    rng = random.Random(seed)
    chunk = b"\xa5" * CHUNK_BYTES

    # Written inside the container's own filesystem, which is what a real job
    # would use; TMPDIR can redirect it to a mounted volume if needed.
    handle, path = tempfile.mkstemp(prefix="hs-io-")
    os.close(handle)

    try:
        write_start = time.perf_counter()

        with open(path, "wb") as target:
            for _ in range(size):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())

        write_elapsed = time.perf_counter() - write_start

        total_bytes = size * CHUNK_BYTES
        reads = max(1, size * 64)

        read_start = time.perf_counter()

        checksum = 0
        with open(path, "rb") as source:
            for _ in range(reads):
                offset = rng.randrange(0, max(1, total_bytes - READ_BLOCK))
                source.seek(offset)
                block = source.read(READ_BLOCK)
                checksum = (checksum + len(block)) % 1_000_000_007

        read_elapsed = time.perf_counter() - read_start

    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    return {
        "workload": "io",
        "size": size,
        "written_mb": size,
        "elapsed_s": write_elapsed + read_elapsed,
        "write_elapsed_s": write_elapsed,
        "read_elapsed_s": read_elapsed,
        "write_mb_s": (total_bytes / write_elapsed / 1e6) if write_elapsed > 0 else None,
        "random_read_iops": (reads / read_elapsed) if read_elapsed > 0 else None,
        "checksum": checksum,
    }
