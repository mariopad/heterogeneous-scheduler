"""
Memory-bandwidth-bound workload: streaming reads and writes over a large array.

The array is sized to overflow cache, so the loop is limited by RAM bandwidth
rather than by the CPU. This is the workload that should separate a desktop
with dual-channel DDR4 from a Raspberry Pi, even when their core counts are
similar -- a distinction a purely CPU-bound trace never surfaces.

Declaring `memory_mb` on jobs of this type matters: the scheduler must not
place several of them on a 2 GB Jetson at once.
"""

import time
from typing import Dict


def run(size: int, seed: int = 0) -> Dict:
    """
    Stream over a `size` MB array.

    Args:
        size: Working set in MiB. Should comfortably exceed last-level cache.
        seed: Unused; kept so every workload has the same signature.

    Returns:
        Effective bandwidth in MB/s.
    """
    import numpy as np

    elements = (size * 1024 * 1024) // 8
    data = np.ones(elements, dtype=np.float64)

    passes = 5

    start = time.perf_counter()

    total = 0.0
    for _ in range(passes):
        # Read the whole array, then write the whole array.
        total += float(data.sum())
        data *= 1.0000001

    elapsed = time.perf_counter() - start

    # Each pass touches the array twice: once summing, once scaling.
    bytes_moved = passes * 2 * elements * 8

    return {
        "workload": "memory",
        "size": size,
        "working_set_mb": size,
        "passes": passes,
        "elapsed_s": elapsed,
        "bandwidth_mb_s": (bytes_moved / elapsed / 1e6) if elapsed > 0 else None,
        "checksum": total,
    }
