"""
experiments/export.py

Export a recorded run to CSV and JSON.

Reads the database directly rather than the scheduler's HTTP API, so results
can be re-exported long after the experiment, from a copied database file,
with no cluster running.

    python -m experiments.export --list
    python -m experiments.export <run_id> [--db scheduler.db] [--out results/]
"""

import argparse
import csv
import json
import os
import sys
from typing import Dict, List, Optional

from experiments.metrics import summarise, job_rows

JOB_COLUMNS = [
    "job_id", "image", "command", "status", "node_id",
    "workload_type", "job_size", "cpu_request", "memory_mb",
    "submitted_at", "dispatched_at", "completed_at",
    "queue_wait_s", "runtime_s", "turnaround_s", "overhead_s",
    "success", "exit_code",
]

NODE_COLUMNS = [
    "node_id", "cpus", "jobs", "jobs_per_cpu", "successful", "failed",
    "busy_time_s", "mean_runtime_s", "utilisation",
]


def _db(path: Optional[str]):
    """Import the db layer pointed at `path`."""
    from scheduler import db

    if path:
        db.DATABASE_PATH = path

    return db


def _write_csv(path: str, columns: List[str], rows: List[Dict]) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_export(run: Dict, jobs: List[Dict], out_dir: str = "results") -> Dict:
    """
    Write per-job CSV, per-node CSV and a summary JSON for one run.

    Returns the summary so a caller can print or compare it without re-reading
    the files.
    """
    summary = summarise(run, jobs)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"{run['policy']}_{run['run_id']}")

    _write_csv(f"{stem}_jobs.csv", JOB_COLUMNS, job_rows(jobs))
    _write_csv(f"{stem}_nodes.csv", NODE_COLUMNS, summary["nodes_detail"])

    with open(f"{stem}_summary.json", "w") as handle:
        json.dump(summary, handle, indent=2)

    return summary


def export_run(run_id: str, out_dir: str = "results", db_path: Optional[str] = None) -> Dict:
    """Export a run by reading the scheduler's database file."""
    db = _db(db_path)

    run = db.get_run(run_id)
    if run is None:
        raise SystemExit(f"Unknown run: {run_id}")

    return write_export(run, db.get_run_jobs(run_id), out_dir)


def export_run_via_http(scheduler: str, run_id: str, out_dir: str = "results") -> Dict:
    """
    Export a run by asking the scheduler for it.

    Needed whenever the harness runs somewhere other than the scheduler host,
    which is the normal case for the real cluster -- there is no database file
    to open locally.
    """
    import requests

    run = requests.get(f"{scheduler}/runs/{run_id}", timeout=30).json()["run"]
    jobs = requests.get(f"{scheduler}/runs/{run_id}/jobs", timeout=60).json()["jobs"]

    return write_export(run, jobs, out_dir)


def format_summary(summary: Dict) -> str:
    """Human-readable digest of a run."""
    jobs = summary["jobs"]

    def fmt(value, spec=".3f"):
        return "n/a" if value is None else format(value, spec)

    lines = [
        f"run {summary['run_id']}  policy={summary['policy']}"
        + (f"  label={summary['label']}" if summary.get("label") else ""),
        f"  jobs         {jobs['total']} total, {jobs['completed']} completed, "
        f"{jobs['failed']} failed, {jobs['incomplete']} incomplete",
        f"  cluster      {summary['nodes']} nodes, {summary['total_cpus']} cpus",
        f"  makespan     {fmt(summary['makespan_s'])} s",
        f"  throughput   {fmt(summary['throughput_jobs_per_s'])} jobs/s",
        f"  queue wait   mean {fmt(summary['queue_wait_s']['mean'])} s  "
        f"p95 {fmt(summary['queue_wait_s']['p95'])} s  "
        f"max {fmt(summary['queue_wait_s']['max'])} s",
        f"  turnaround   mean {fmt(summary['turnaround_s']['mean'])} s  "
        f"p95 {fmt(summary['turnaround_s']['p95'])} s",
        f"  fairness     jobs {fmt(summary['fairness_jobs'])}  "
        f"per-cpu {fmt(summary['fairness_jobs_per_cpu'])}",
        "  placement    " + ", ".join(
            f"{n['node_id']}={n['jobs']} ({fmt(n['utilisation'], '.2f')} util)"
            for n in summary["nodes_detail"]
        ),
    ]

    breakdown = summary.get("by_workload") or {}
    if len(breakdown) > 1 or set(breakdown) - {"unspecified"}:
        lines.append("  by workload")
        for workload_type, stats in breakdown.items():
            placement = " ".join(f"{node}={count}"
                                 for node, count in sorted(stats["placement"].items()))
            lines.append(
                f"    {workload_type:<12} {stats['jobs']:>3} jobs  "
                f"runtime mean {fmt(stats['runtime_s']['mean'])} s  "
                f"wait mean {fmt(stats['queue_wait_s']['mean'])} s  [{placement}]"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export experiment results.")
    parser.add_argument("run_id", nargs="?", help="Run to export.")
    parser.add_argument("--db", default=os.getenv("SCHEDULER_DB", "scheduler.db"))
    parser.add_argument("--out", default="results", help="Output directory.")
    parser.add_argument("--list", action="store_true", help="List recorded runs and exit.")
    args = parser.parse_args()

    if args.list:
        for run in _db(args.db).get_all_runs():
            state = "open" if not run["finished_at"] else "finished"
            print(f"{run['run_id']}  {run['policy']:<14} {run['started_at']}  "
                  f"{state:<8} {run['label'] or ''}")
        return 0

    if not args.run_id:
        parser.error("run_id is required unless --list is given")

    summary = export_run(args.run_id, out_dir=args.out, db_path=args.db)
    print(format_summary(summary))
    print(f"\nwritten to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
