"""
experiments/run_experiment.py

Drive one experiment end to end: open a run, submit a job trace, wait for the
cluster to drain, close the run and export the results.

Talks to the scheduler over HTTP only, so it works the same against a local
process and against the real cluster.

    # one run
    python -m experiments.run_experiment --policy least_loaded --jobs 16 \
        --image alpine --command "sleep 2"

    # compare policies back to back on the same trace and cluster
    python -m experiments.run_experiment --trace experiments/traces/burst.json \
        --policy round_robin --policy least_loaded

Each run re-instantiates the policy, so per-policy state such as the
round-robin counter starts from zero and a run is reproducible.
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
from typing import Dict, List, Optional

import requests

from experiments.export import export_run, export_run_via_http, format_summary
from shared.timeutils import utc_now


def load_trace(path: str) -> Dict:
    """
    Read a trace file.

    Format:

        {
          "name": "burst",
          "jobs": [
            {"image": "alpine", "command": "sleep 2", "count": 16,
             "delay_before": 0.0}
          ]
        }

    `count` repeats an entry; `delay_before` is the pause in seconds before
    each of those copies is submitted, which is what shapes the arrival
    pattern -- 0 for a burst, a positive value for a paced stream.
    """
    with open(path) as handle:
        trace = json.load(handle)

    if "jobs" not in trace:
        raise SystemExit(f"Trace {path} has no 'jobs' list")

    return trace


def expand_trace(trace: Dict, image: str) -> List[Dict]:
    """
    Flatten a trace into the individual jobs to submit, in order.

    An entry naming a `workload` is turned into a call to the workload image
    and given that workload's default requirements, so a trace stays short
    while the jobs still declare what they need. Anything the entry sets
    explicitly under `requirements` wins over those defaults.
    """
    from workloads.registry import requirements_for

    jobs = []

    for entry in trace["jobs"]:
        workload = entry.get("workload")

        if workload:
            size = int(entry.get("size", 100))
            requirements = requirements_for(workload, size)
            requirements["size"] = size
            command = entry.get("command") or f"--type {workload} --size {size}"
            job_image = entry.get("image", image)
        else:
            requirements = {}
            command = entry.get("command")
            job_image = entry.get("image", image)

        requirements.update(entry.get("requirements", {}))

        for _ in range(int(entry.get("count", 1))):
            jobs.append({
                "image": job_image,
                "command": command,
                "requirements": requirements,
                "delay_before": float(entry.get("delay_before", 0.0)),
            })

    if trace.get("shuffle"):
        # Interleave workload types instead of running them in blocks, so a
        # policy cannot look good merely because the trace happened to feed
        # it one type at a time.
        random.Random(trace.get("seed", 0)).shuffle(jobs)

    return jobs


def wait_for_nodes(scheduler: str, expected: int, timeout: float) -> List[Dict]:
    """Block until at least `expected` nodes have registered."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        cluster = requests.get(f"{scheduler}/cluster", timeout=10).json()

        if cluster["nodes"] >= expected:
            return cluster["node_status"]

        time.sleep(1)

    raise SystemExit(
        f"Only {cluster['nodes']} node(s) registered, expected {expected}. "
        "Start the agents before running an experiment."
    )


def wait_for_drain(scheduler: str, run_id: str, total: int, timeout: float,
                   poll: float = 1.0) -> Dict:
    """
    Block until every job of the run reaches a terminal state.

    A job stuck in 'dispatched' because its node died never becomes terminal,
    so the wait is bounded. Timing out is reported rather than raised: a
    partial run is still worth exporting, and the incomplete count in the
    summary makes the shortfall explicit.
    """
    deadline = time.time() + timeout
    last_report = 0.0

    while time.time() < deadline:
        progress = requests.get(f"{scheduler}/runs/{run_id}", timeout=10).json()["progress"]

        if progress["terminal"] >= total:
            return progress

        now = time.time()
        if now - last_report > 5:
            last_report = now
            print(f"  {progress['terminal']}/{total} done "
                  f"(queued={progress['queued']} running={progress['dispatched']})")

        time.sleep(poll)

    print(f"  timed out after {timeout:.0f}s with "
          f"{progress['terminal']}/{total} jobs terminal", file=sys.stderr)
    return progress


def submit_jobs(scheduler: str, jobs: List[Dict], prefix: str) -> int:
    """Submit the trace, honouring each job's arrival delay."""
    for index, job in enumerate(jobs):
        if job["delay_before"] > 0:
            time.sleep(job["delay_before"])

        payload = {
            "job_id": f"{prefix}-{index:04d}",
            "image": job["image"],
            "command": job["command"],
            "submitted_at": utc_now().isoformat(),
            "requirements": job.get("requirements") or {},
        }

        response = requests.post(f"{scheduler}/jobs", json=payload, timeout=30)
        response.raise_for_status()

    return len(jobs)


def run_once(scheduler: str, policy: Optional[str], trace: Dict, jobs: List[Dict],
             label: Optional[str], out_dir: str, db_path: str,
             timeout: float) -> Dict:
    """Execute one policy against one trace and return its summary."""
    response = requests.post(f"{scheduler}/runs/start", json={
        "policy": policy,
        "label": label,
        "trace": trace.get("name"),
    }, timeout=30)

    if response.status_code == 409:
        raise SystemExit(f"Scheduler refused to start a run: {response.json()['detail']}")

    response.raise_for_status()
    started = response.json()
    run_id = started["run_id"]

    print(f"\n=== run {run_id}  policy={started['policy']}  "
          f"{len(jobs)} jobs on {len(started['nodes'])} nodes ===")

    try:
        total = submit_jobs(scheduler, jobs, prefix=run_id)
        wait_for_drain(scheduler, run_id, total, timeout)
    finally:
        # Always close the run, otherwise the next one is refused.
        requests.post(f"{scheduler}/runs/finish", timeout=30)

    # Read the database directly when it is on this machine, otherwise ask
    # the scheduler. The harness usually runs away from the cluster.
    if db_path and os.path.exists(db_path):
        summary = export_run(run_id, out_dir=out_dir, db_path=db_path)
    else:
        summary = export_run_via_http(scheduler, run_id, out_dir=out_dir)

    print(format_summary(summary))
    return summary


def build_trace(args) -> Dict:
    """Trace from a file, or synthesised from the CLI flags."""
    if args.trace:
        return load_trace(args.trace)

    if args.workload:
        return {
            "name": f"cli-{args.jobs}x{args.workload}{args.size}",
            "jobs": [{
                "workload": args.workload,
                "size": args.size,
                "count": args.jobs,
                "delay_before": args.interval,
            }],
        }

    return {
        "name": f"cli-{args.jobs}x{args.image}",
        "jobs": [{
            "image": args.image,
            "command": args.command,
            "count": args.jobs,
            "delay_before": args.interval,
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a scheduling experiment.")
    parser.add_argument("--scheduler", default=os.getenv("SCHEDULER_URL", "http://localhost:8000"))
    parser.add_argument("--db", default=os.getenv("SCHEDULER_DB", "scheduler.db"),
                        help="Database to export from; must be the scheduler's.")
    parser.add_argument("--out", default="results", help="Output directory.")
    parser.add_argument("--policy", action="append", dest="policies",
                        help="Policy to run. Repeat to compare several in one go.")
    parser.add_argument("--label", help="Free-text label recorded with the run.")
    parser.add_argument("--expect-nodes", type=int, default=1,
                        help="Wait until this many nodes have registered.")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="Seconds to wait for the trace to drain.")

    parser.add_argument("--trace", help="Trace file to submit.")
    parser.add_argument("--jobs", type=int, default=16, help="Job count when no trace file.")
    parser.add_argument("--workload", help="Workload from the suite: cpu, memory, io or gpu.")
    parser.add_argument("--size", type=int, default=100, help="Workload scale.")
    parser.add_argument("--image", default=os.getenv("WORKLOAD_IMAGE", "heterosched/workload:latest"),
                        help="Image running the workload suite.")
    parser.add_argument("--command", default="sleep 2",
                        help="Command when neither --trace nor --workload is given.")
    parser.add_argument("--interval", type=float, default=0.0,
                        help="Seconds between submissions; 0 submits as a burst.")

    args = parser.parse_args()

    trace = build_trace(args)
    jobs = expand_trace(trace, image=args.image)

    nodes = wait_for_nodes(args.scheduler, args.expect_nodes, timeout=60)
    print(f"cluster ready: {len(nodes)} node(s), "
          f"{sum(n['cpus'] for n in nodes)} cpus")

    summaries = []
    for policy in (args.policies or [None]):
        summaries.append(run_once(
            args.scheduler, policy, trace, jobs,
            label=args.label, out_dir=args.out, db_path=args.db,
            timeout=args.timeout,
        ))

    if len(summaries) > 1:
        print("\n=== comparison ===")
        header = f"{'policy':<16}{'makespan_s':>12}{'throughput':>12}{'mean_wait':>12}{'fair/cpu':>10}"
        print(header)
        print("-" * len(header))
        for summary in summaries:
            def fmt(value, spec=".3f"):
                return "n/a" if value is None else format(value, spec)
            print(f"{summary['policy']:<16}"
                  f"{fmt(summary['makespan_s']):>12}"
                  f"{fmt(summary['throughput_jobs_per_s']):>12}"
                  f"{fmt(summary['queue_wait_s']['mean']):>12}"
                  f"{fmt(summary['fairness_jobs_per_cpu'], '.3f'):>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
