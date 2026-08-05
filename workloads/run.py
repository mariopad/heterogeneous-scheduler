"""
workloads/run.py

Entrypoint for every workload, used identically inside a container and on the
host:

    python -m workloads.run --type cpu --size 20
    docker run heterosched/workload:latest --type cpu --size 20

Prints one JSON object on stdout and exits non-zero if the workload could not
run, so the agent's exit-code check reflects what actually happened.
"""

import argparse
import json
import os
import sys


def _pin_blas_threads(threads: int) -> None:
    """
    Cap the BLAS thread count.

    Must happen before numpy is imported: OpenBLAS and MKL read these once at
    load time. Left unpinned, a single job would spread over every core and
    the scheduler's one-job-per-slot accounting would no longer describe
    reality -- placing four jobs on a four-core node would oversubscribe it
    fourfold rather than fill it.
    """
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(variable, str(threads))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a benchmark workload.")
    parser.add_argument("--type", required=True,
                        help="Workload: cpu, memory, io or gpu.")
    parser.add_argument("--size", type=int, default=10,
                        help="Work scale; meaning depends on the workload.")
    parser.add_argument("--seed", type=int, default=0,
                        help="Fixes operands so repeated runs do identical work.")
    parser.add_argument("--threads", type=int, default=1,
                        help="BLAS threads. Keep at 1 so one job means one slot.")
    args = parser.parse_args()

    _pin_blas_threads(args.threads)

    # Imported after the thread pinning above, since it pulls in numpy.
    from workloads.registry import run_workload

    try:
        result = run_workload(args.type, size=args.size, seed=args.seed)
    except KeyError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}",
                          "workload": args.type}), file=sys.stderr)
        return 1

    result["threads"] = args.threads
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
