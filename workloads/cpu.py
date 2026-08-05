"""
CPU-bound workload: repeated dense matrix multiplication.

Deliberately the same kernel the agent's CPU benchmark uses, so a
benchmark-driven policy can correlate a node's measured GFLOPS with how long
this workload actually takes there. A workload that stressed something else
would make the benchmark useless as a predictor.

Single-threaded by default (see workloads/run.py, which pins the BLAS thread
count before numpy is imported). One job then means one core, which is what
the scheduler's slot accounting assumes -- a multi-threaded BLAS would let a
single job consume the whole node and silently break the capacity model.
"""

import time
from typing import Dict


DIM = 512


def run(size: int, seed: int = 0) -> Dict:
    """
    Multiply two DIM x DIM matrices `size` times.

    Args:
        size: Number of matrix multiplications. Work scales linearly with it.
        seed: Fixes the operands so repeated runs do identical work.

    Returns:
        Measured throughput in GFLOPS alongside the raw timing.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    a = rng.random((DIM, DIM), dtype=np.float64)
    b = rng.random((DIM, DIM), dtype=np.float64)

    # One multiply-add per inner-loop step, hence 2 * n^3 floating point ops.
    flops_per_iteration = 2.0 * DIM ** 3

    start = time.perf_counter()

    result = None
    for _ in range(size):
        result = a @ b
        # Feed the output back in so the loop cannot be optimised away and
        # every iteration depends on the previous one. Renormalising keeps
        # the magnitudes bounded: without it the entries grow by roughly two
        # orders of magnitude per iteration and overflow to inf within a few
        # hundred, after which the kernel is measuring arithmetic on
        # infinities rather than on numbers.
        a = result / (float(result.mean()) * 2.0)

    elapsed = time.perf_counter() - start

    return {
        "workload": "cpu",
        "size": size,
        "matrix_dim": DIM,
        "iterations": size,
        "elapsed_s": elapsed,
        "gflops": (flops_per_iteration * size / elapsed / 1e9) if elapsed > 0 else None,
        "checksum": float(result.sum()) if result is not None else None,
    }
