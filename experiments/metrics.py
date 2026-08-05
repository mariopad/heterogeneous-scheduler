"""
experiments/metrics.py

Turn a recorded run into the numbers a results chapter needs.

Everything is derived from timestamps already in the database, so metrics can
be recomputed for an old run without re-running the experiment.

Timeline of one job:

    submitted_at ---- queue wait ---> dispatched_at ---- runtime ---> completed_at
    |________________________ turnaround ______________________________|

`runtime_seconds` is measured on the agent around the container itself, so it
excludes dispatch latency; turnaround minus queue wait minus runtime is the
network and callback overhead.
"""

import json
import statistics
from typing import Any, Dict, List, Optional

from shared.timeutils import from_iso, seconds_between


def percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile. Small samples make interpolation misleading."""
    if not values:
        return None

    ordered = sorted(values)
    rank = max(1, int(round(pct / 100.0 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def distribution(values: List[float]) -> Dict[str, Optional[float]]:
    """Summary statistics for a set of measurements."""
    clean = [v for v in values if v is not None]

    if not clean:
        return {"n": 0, "mean": None, "median": None, "stdev": None,
                "min": None, "p95": None, "max": None}

    return {
        "n": len(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "stdev": statistics.stdev(clean) if len(clean) > 1 else 0.0,
        "min": min(clean),
        "p95": percentile(clean, 95),
        "max": max(clean),
    }


def jains_fairness(values: List[float]) -> Optional[float]:
    """
    Jain's fairness index: 1.0 is perfectly even, 1/n is maximally skewed.

    Applied to raw job counts this asks "did every node get the same number
    of jobs", which is the wrong question for a heterogeneous cluster -- a
    Raspberry Pi should not receive as much work as a 12-thread desktop.
    Applied to jobs-per-core it asks "was work allocated in proportion to
    capacity", which is the fairness a heterogeneous scheduler should aim for.
    Both are reported so the distinction stays visible.
    """
    if not values:
        return None

    total = sum(values)

    if total == 0:
        return None

    squares = sum(v * v for v in values)

    if squares == 0:
        return None

    return (total * total) / (len(values) * squares)


def job_rows(jobs: List[Dict]) -> List[Dict[str, Any]]:
    """Per-job records with the derived durations attached."""
    rows = []

    for job in jobs:
        queue_wait = seconds_between(job.get("submitted_at"), job.get("dispatched_at"))
        turnaround = seconds_between(job.get("submitted_at"), job.get("completed_at"))
        runtime = job.get("runtime_seconds")

        overhead = None
        if turnaround is not None and queue_wait is not None and runtime is not None:
            overhead = turnaround - queue_wait - runtime

        rows.append({
            "job_id": job.get("job_id"),
            "image": job.get("image"),
            "command": job.get("command"),
            "status": job.get("status"),
            "node_id": job.get("dispatched_to_node"),
            "workload_type": job.get("workload_type"),
            "job_size": job.get("job_size"),
            "cpu_request": job.get("cpu_request"),
            "memory_mb": job.get("memory_mb"),
            "submitted_at": job.get("submitted_at"),
            "dispatched_at": job.get("dispatched_at"),
            "completed_at": job.get("completed_at"),
            "queue_wait_s": queue_wait,
            "runtime_s": runtime,
            "turnaround_s": turnaround,
            "overhead_s": overhead,
            "success": bool(job.get("success")) if job.get("success") is not None else None,
            "exit_code": job.get("exit_code"),
        })

    return rows


def node_rows(rows: List[Dict], cluster: List[Dict], makespan: Optional[float]) -> List[Dict]:
    """
    Per-node totals.

    Built from the cluster snapshot rather than from the jobs, so a node that
    received no work at all still appears as a zero row instead of vanishing
    from the comparison.
    """
    by_node: Dict[str, List[Dict]] = {n["node_id"]: [] for n in cluster}

    for row in rows:
        if row["node_id"] is not None:
            by_node.setdefault(row["node_id"], []).append(row)

    cpus_by_node = {n["node_id"]: n.get("cpus") or 1 for n in cluster}

    out = []
    for node_id, node_jobs in sorted(by_node.items()):
        cpus = cpus_by_node.get(node_id, 1)
        runtimes = [r["runtime_s"] for r in node_jobs if r["runtime_s"] is not None]
        busy = sum(runtimes)

        out.append({
            "node_id": node_id,
            "cpus": cpus,
            "jobs": len(node_jobs),
            "jobs_per_cpu": len(node_jobs) / cpus if cpus else None,
            "successful": sum(1 for r in node_jobs if r["success"] is True),
            "failed": sum(1 for r in node_jobs if r["success"] is False),
            "busy_time_s": busy,
            "mean_runtime_s": statistics.fmean(runtimes) if runtimes else None,
            # Fraction of the run's wall clock during which the node's cores
            # were occupied. Above 1.0 would mean oversubscription.
            "utilisation": (busy / (makespan * cpus)) if makespan and cpus else None,
        })

    return out


def by_workload(rows: List[Dict]) -> Dict[str, Any]:
    """
    Metrics split by workload type.

    A run mixing CPU, memory, I/O and GPU jobs has no meaningful average
    runtime -- the aggregate just tracks whichever type dominated the trace.
    The per-type breakdown is what shows that, say, I/O jobs were slow on the
    SD-card node while CPU jobs there were fine, which is the whole argument
    for hardware-aware placement.
    """
    groups: Dict[str, List[Dict]] = {}

    for row in rows:
        groups.setdefault(row.get("workload_type") or "unspecified", []).append(row)

    out = {}
    for workload_type, group in sorted(groups.items()):
        placement: Dict[str, int] = {}
        for row in group:
            if row["node_id"]:
                placement[row["node_id"]] = placement.get(row["node_id"], 0) + 1

        out[workload_type] = {
            "jobs": len(group),
            "completed": sum(1 for r in group if r["success"] is True),
            "failed": sum(1 for r in group if r["success"] is False),
            "runtime_s": distribution([r["runtime_s"] for r in group]),
            "queue_wait_s": distribution([r["queue_wait_s"] for r in group]),
            "turnaround_s": distribution([r["turnaround_s"] for r in group]),
            "placement": placement,
        }

    return out


def runtime_by_node_and_workload(rows: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """
    Mean runtime for each (node, workload type) pair.

    This is the table that exposes hardware heterogeneity directly: the same
    workload taking three times longer on one node than another is the signal
    a hardware-aware policy exists to exploit.
    """
    groups: Dict[str, Dict[str, List[float]]] = {}

    for row in rows:
        if row["node_id"] is None or row["runtime_s"] is None:
            continue

        workload_type = row.get("workload_type") or "unspecified"
        groups.setdefault(workload_type, {}).setdefault(row["node_id"], []).append(
            row["runtime_s"]
        )

    return {
        workload_type: {
            node_id: {
                "jobs": len(runtimes),
                "mean_runtime_s": statistics.fmean(runtimes),
            }
            for node_id, runtimes in sorted(nodes.items())
        }
        for workload_type, nodes in sorted(groups.items())
    }


def summarise(run: Dict, jobs: List[Dict]) -> Dict[str, Any]:
    """Aggregate metrics for one run."""
    rows = job_rows(jobs)

    cluster = json.loads(run["cluster_snapshot"]) if run.get("cluster_snapshot") else []

    submitted = [from_iso(r["submitted_at"]) for r in rows if r["submitted_at"]]
    completed = [from_iso(r["completed_at"]) for r in rows if r["completed_at"]]

    # Makespan spans the whole experiment: first submission to last completion.
    makespan = None
    if submitted and completed:
        makespan = (max(completed) - min(submitted)).total_seconds()

    successful = [r for r in rows if r["success"] is True]
    failed = [r for r in rows if r["success"] is False]
    incomplete = [r for r in rows if r["status"] not in ("completed", "failed")]

    node_stats = node_rows(rows, cluster, makespan)
    counts = [n["jobs"] for n in node_stats]
    per_cpu = [n["jobs_per_cpu"] for n in node_stats if n["jobs_per_cpu"] is not None]

    return {
        "run_id": run.get("run_id"),
        "label": run.get("label"),
        "policy": run.get("policy"),
        "trace": run.get("trace"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "nodes": len(cluster),
        "total_cpus": sum(n.get("cpus") or 0 for n in cluster),
        "jobs": {
            "total": len(rows),
            "completed": len(successful),
            "failed": len(failed),
            "incomplete": len(incomplete),
        },
        "makespan_s": makespan,
        "throughput_jobs_per_s": (len(successful) / makespan) if makespan else None,
        "queue_wait_s": distribution([r["queue_wait_s"] for r in rows]),
        "runtime_s": distribution([r["runtime_s"] for r in rows]),
        "turnaround_s": distribution([r["turnaround_s"] for r in rows]),
        "overhead_s": distribution([r["overhead_s"] for r in rows]),
        "fairness_jobs": jains_fairness(counts),
        "fairness_jobs_per_cpu": jains_fairness(per_cpu),
        "nodes_detail": node_stats,
        "by_workload": by_workload(rows),
        "runtime_by_node_and_workload": runtime_by_node_and_workload(rows),
    }
