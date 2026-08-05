"""
workloads/registry.py

Maps a workload name to its implementation and to the resource requirements a
job of that kind should declare.

The defaults here are what the trace generator uses when a trace does not
override them, so a trace file stays short while the jobs it produces still
carry meaningful requirements.
"""

from typing import Callable, Dict

from workloads import cpu, io, memory, gpu


#: name -> (module, default requirements for a job of this type)
WORKLOADS: Dict[str, Dict] = {
    "cpu": {
        "run": cpu.run,
        "description": "Repeated dense matrix multiplication, single-threaded.",
        "size_unit": "matrix multiplications",
        "defaults": {
            "cpu_request": 1,
            "memory_mb": 256,
            "requires_gpu": False,
        },
    },
    "memory": {
        "run": memory.run,
        "description": "Streaming reads and writes over a cache-overflowing array.",
        "size_unit": "MiB working set",
        "defaults": {
            "cpu_request": 1,
            # Must cover the working set itself plus interpreter overhead,
            # otherwise the container is killed the moment it allocates.
            "memory_mb": 512,
            "requires_gpu": False,
        },
    },
    "io": {
        "run": io.run,
        "description": "Sequential write with fsync, then random reads.",
        "size_unit": "MiB written",
        "defaults": {
            "cpu_request": 1,
            "memory_mb": 256,
            "requires_gpu": False,
        },
    },
    "gpu": {
        "run": gpu.run,
        "description": "Dense matrix multiplication on the accelerator.",
        "size_unit": "matrix multiplications",
        "defaults": {
            "cpu_request": 1,
            "memory_mb": 1024,
            "requires_gpu": True,
        },
    },
}


def requirements_for(workload_type: str, size: int) -> Dict:
    """
    Default requirements for a job of this workload type and size.

    Memory scales with the working set for the memory workload, since that is
    the one whose footprint is the point of the job rather than incidental.
    """
    if workload_type not in WORKLOADS:
        raise KeyError(
            f"Unknown workload: {workload_type}. "
            f"Available: {', '.join(sorted(WORKLOADS))}"
        )

    defaults = dict(WORKLOADS[workload_type]["defaults"])

    if workload_type == "memory":
        # Working set plus headroom for the interpreter and a copy.
        defaults["memory_mb"] = max(defaults["memory_mb"], int(size * 1.5) + 256)

    defaults["workload_type"] = workload_type
    return defaults


def run_workload(workload_type: str, size: int, seed: int = 0) -> Dict:
    """Execute a workload by name."""
    if workload_type not in WORKLOADS:
        raise KeyError(
            f"Unknown workload: {workload_type}. "
            f"Available: {', '.join(sorted(WORKLOADS))}"
        )

    return WORKLOADS[workload_type]["run"](size=size, seed=seed)
