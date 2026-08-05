"""
Containerised workloads used to evaluate scheduling policies.

Each workload stresses one subsystem, so that heterogeneous hardware actually
differentiates. Running identical trivial jobs makes every policy score the
same and proves nothing.

Every workload takes a `size` and reports what it measured as JSON on stdout,
so a container's log is enough to check that the run was sane.
"""

from workloads.registry import WORKLOADS, run_workload

__all__ = ["WORKLOADS", "run_workload"]
