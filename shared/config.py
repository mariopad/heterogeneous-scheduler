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
    else:
        BENCHMARK_REPETITIONS = 5
        BENCHMARK_CPU_ITERATIONS = 5
        BENCHMARK_CPU_WARMUP_ITERATIONS = 3

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
