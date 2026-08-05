"""
GPU-bound workload: dense matrix multiplication on the accelerator.

Tries CuPy then PyTorch, and supports both CUDA (Jetson Nano, any NVIDIA card)
and ROCm (RX 6600) through PyTorch's device abstraction.

Raises GPUUnavailable when there is no usable device rather than silently
falling back to the CPU. A GPU job that quietly runs on a CPU node would make
`requires_gpu` unfalsifiable and would corrupt any comparison that relies on
it: the scheduler must be seen to have placed the job wrongly.
"""

import time
from typing import Dict, Optional, Tuple


DIM = 2048


class GPUUnavailable(RuntimeError):
    """No usable GPU backend on this node."""


def _select_backend() -> Tuple[str, Optional[str]]:
    """Return (backend, device) for the first usable accelerator."""
    try:
        import cupy

        if cupy.cuda.runtime.getDeviceCount() > 0:
            return "cupy", "cuda"
    except Exception:
        pass

    try:
        import torch

        if torch.cuda.is_available():
            # torch reports ROCm devices as "cuda" too, so this covers the
            # AMD card as well as the NVIDIA ones.
            return "torch", "cuda"
    except Exception:
        pass

    raise GPUUnavailable(
        "No CUDA or ROCm device usable from this container. Check that the "
        "runtime exposes the GPU (--gpus all / --device=/dev/kfd)."
    )


def run(size: int, seed: int = 0) -> Dict:
    """
    Multiply two DIM x DIM matrices `size` times on the GPU.

    Args:
        size: Number of matrix multiplications.
        seed: Fixes the operands.

    Returns:
        Measured throughput in GFLOPS and which backend was used.
    """
    backend, device = _select_backend()

    flops_per_iteration = 2.0 * DIM ** 3

    if backend == "cupy":
        import cupy as xp

        xp.random.seed(seed)
        a = xp.random.random((DIM, DIM), dtype=xp.float32)
        b = xp.random.random((DIM, DIM), dtype=xp.float32)

        synchronise = xp.cuda.Stream.null.synchronize
    else:
        import torch

        torch.manual_seed(seed)
        a = torch.rand(DIM, DIM, device=device, dtype=torch.float32)
        b = torch.rand(DIM, DIM, device=device, dtype=torch.float32)

        def synchronise():
            torch.cuda.synchronize()

    # Warm up so kernel compilation and allocation are not counted.
    _ = a @ b
    synchronise()

    start = time.perf_counter()

    result = None
    for _ in range(size):
        result = a @ b
        # Renormalise for the same reason as the CPU kernel: unbounded
        # feedback overflows, and float32 overflows far sooner than float64.
        a = result / (float(result.mean()) * 2.0)

    synchronise()
    elapsed = time.perf_counter() - start

    return {
        "workload": "gpu",
        "size": size,
        "backend": backend,
        "matrix_dim": DIM,
        "iterations": size,
        "elapsed_s": elapsed,
        "gflops": (flops_per_iteration * size / elapsed / 1e9) if elapsed > 0 else None,
        "checksum": float(result.sum()) if result is not None else None,
    }
