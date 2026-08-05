"""
Shared configuration module for scheduler and agents.

Debug mode can be controlled via DEBUG environment variable (0 or 1).
In debug mode, benchmarks run fewer iterations for faster iteration during development.
"""

import os


class Config:
    """Centralized configuration with debug mode support."""

    DEBUG: bool = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")

    # How many times the dispatcher retries a job before giving up on it.
    # Without a cap, a job whose image is missing on every node is requeued
    # forever and the trace never drains.
    MAX_DISPATCH_ATTEMPTS: int = int(os.getenv("MAX_DISPATCH_ATTEMPTS", "3"))

    # Benchmark repetitions and iterations
    if DEBUG:
        BENCHMARK_REPETITIONS = 1
        BENCHMARK_CPU_ITERATIONS = 1
        BENCHMARK_CPU_WARMUP_ITERATIONS = 1
        # Matrix multiplications per timed iteration. Previously the CPU
        # benchmark reused BENCHMARK_CPU_ITERATIONS for this, so the two could
        # never be tuned apart and the work per iteration grew quadratically
        # with the iteration count.
        BENCHMARK_CPU_REPETITIONS = 1
    else:
        BENCHMARK_REPETITIONS = 5
        BENCHMARK_CPU_ITERATIONS = 5
        BENCHMARK_CPU_WARMUP_ITERATIONS = 3
        BENCHMARK_CPU_REPETITIONS = 3

    # Threads for the memory bandwidth runs, clamped to the node's core count.
    BENCHMARK_MEM_THREADS: int = int(os.getenv("BENCHMARK_MEM_THREADS", "4"))

    # --- I/O benchmark shape -------------------------------------------------
    # Sized independently of BENCHMARK_REPETITIONS because disk work is orders
    # of magnitude slower than the CPU and memory benchmarks, and reusing their
    # settings made a node take over twenty minutes to start.
    #
    # The dataset does not need to exceed RAM. fio runs with O_DIRECT, which
    # bypasses the page cache outright, so size only has to be large enough to
    # defeat the device's own cache -- not the operating system's.
    if DEBUG:
        BENCHMARK_IO_SIZE_MB = 64
        BENCHMARK_IO_RUNTIME_S = 0.5
        BENCHMARK_IO_RAMP_S = 0.2
        BENCHMARK_IO_REPETITIONS = 1
    else:
        BENCHMARK_IO_SIZE_MB = 512
        BENCHMARK_IO_RUNTIME_S = 3
        BENCHMARK_IO_RAMP_S = 1
        BENCHMARK_IO_REPETITIONS = 2

    # Where the I/O benchmark writes its dataset. Defaults to the working
    # directory, which is the disk the agent was started from. Point it at the
    # device you actually want characterised -- and never at a tmpfs such as
    # /tmp, which would measure RAM and report it as disk.
    BENCHMARK_IO_DIR: str = os.getenv("BENCHMARK_IO_DIR", ".")

    @classmethod
    def get_debug(cls) -> bool:
        """Return current debug mode status."""
        return cls.DEBUG

    @classmethod
    def set_debug(cls, enabled: bool) -> None:
        """Set debug mode at runtime (primarily for testing)."""
        cls.DEBUG = enabled
        if enabled:
            cls.BENCHMARK_REPETITIONS = 1
            cls.BENCHMARK_CPU_ITERATIONS = 1
            cls.BENCHMARK_CPU_WARMUP_ITERATIONS = 1
        else:
            cls.BENCHMARK_REPETITIONS = 5
            cls.BENCHMARK_CPU_ITERATIONS = 5
            cls.BENCHMARK_CPU_WARMUP_ITERATIONS = 3

    @classmethod
    def __str__(cls) -> str:
        return (
            f"Config(debug={cls.DEBUG}, "
            f"repetitions={cls.BENCHMARK_REPETITIONS}, "
            f"cpu_iterations={cls.BENCHMARK_CPU_ITERATIONS}, "
            f"max_dispatch_attempts={cls.MAX_DISPATCH_ATTEMPTS})"
        )
