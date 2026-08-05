"""
Benchmark orchestration module.

Coordinates the execution of all hardware benchmarks and aggregates results.

A benchmark that fails does not stop the others: a node with no GPU, or one
without fio installed, should still join the cluster with whatever profile it
managed to produce. It must not do so quietly, though. A missing profile
silently became `None` on the node, and a benchmark-driven policy cannot score
a node it has no numbers for, so failures are collected and reported rather
than printed once and forgotten.
"""

from agent.benchmark.cpu import benchmark_cpu
from agent.benchmark.memory import benchmark_memory
from agent.benchmark.io import benchmark_disk
from agent.benchmark.gpu import benchmark_gpu


def run_full_benchmark(capabilities) -> dict:
    """
    Orchestrate all benchmarks and return unified result.

    Returns the completed profiles keyed by name. Any benchmark that failed is
    listed under "_failed" as name -> error message, so the caller can report
    an incomplete profile instead of registering as if nothing went wrong.
    """
    print(f"\n{'='*60}")
    print(f"[benchmark] Starting full hardware benchmark")
    print(f"{'='*60}\n")

    results = {}
    failures = {}

    benchmarks = (
        ("cpu", "CPU", lambda: benchmark_cpu(capabilities)),
        ("io", "Disk I/O", benchmark_disk),
        ("memory", "Memory", benchmark_memory),
        ("gpu", "GPU detection", benchmark_gpu),
    )

    for key, label, run in benchmarks:
        print(f"[benchmark] Running {label} benchmark...")
        try:
            results[key] = run()
        except Exception as e:
            failures[key] = f"{type(e).__name__}: {e}"
            print(f"[benchmark] ERROR in {label} benchmark: {e}")

    print(f"\n{'='*60}")
    if failures:
        print(f"[benchmark] Completed with {len(failures)} failure(s):")
        for key, error in sorted(failures.items()):
            print(f"[benchmark]   {key}: {error}")
        print("[benchmark] The node will register without those profiles, so a "
              "policy that scores nodes on them cannot rank it.")
        results["_failed"] = failures
    else:
        print(f"[benchmark] Benchmark complete!")
    print(f"{'='*60}\n")

    return results
