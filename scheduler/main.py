"""
scheduler/main.py
- Initializes FastAPI
- Receives heartbeats
- Lists nodes
- Receives jobs
- Select node using Round Robin / selected policy**
"""

"""
To-dos
    - Improve node expiration workflow
        healthy -> scheduler assigns jobs normally
        stale -> scheduler does not assign new jobs
        dead -> erases node -> job rescheduling
"""

from fastapi import FastAPI, HTTPException
from scheduler.state import cluster_state
from scheduler import db
from shared.schemas import (
    NodeRegistration,
    NodeHeartbeat,
    JobRequest,
    JobAssignment,
    JobResult,
    RunStartRequest,
)
from shared.config import Config
from shared.logging import get_logger
from shared.timeutils import utc_now
import requests
import threading
import time
import os
import sys
import uuid
import argparse

from scheduler.policies import RoundRobinPolicy, LeastLoadedPolicy

logger = get_logger("scheduler")

# Policy registry
POLICIES = {
    "round_robin": RoundRobinPolicy,
    "least_loaded": LeastLoadedPolicy,
}


def parse_args():
    """Parse command-line arguments for the scheduler."""
    parser = argparse.ArgumentParser(
        description="Start the distributed scheduler."
    )
    parser.add_argument(
        "--policy",
        type=str,
        default="round_robin",
        choices=list(POLICIES.keys()),
        help=f"Scheduling policy to use (default: round_robin)",
    )
    return parser.parse_args()


def get_policy(policy_name: str):
    """Get policy instance by name."""
    policy_name = policy_name.lower()
    if policy_name not in POLICIES:
        raise ValueError(
            f"Unknown policy: {policy_name}. Available: {', '.join(POLICIES.keys())}"
        )
    return POLICIES[policy_name]()


def get_policy_name():
    """Determine policy from CLI arg or env var (CLI takes precedence)."""
    # Try to parse CLI args (works when running directly, not with uvicorn)
    try:
        if "uvicorn" not in sys.argv[0]:
            args = parse_args()
            return args.policy
    except:
        pass

    # Fall back to environment variable
    return os.getenv("SCHEDULER_POLICY", "round_robin")


# Initialize policy at module load time
policy_name = get_policy_name()
policy = get_policy(policy_name)

# The experiment run currently accepting jobs, if any. Jobs submitted outside
# a run are still executed and recorded, they just carry no run_id and are
# therefore excluded from experiment exports.
active_run_id = None
run_lock = threading.Lock()

app = FastAPI(title="HeteroSched Scheduler")


def dispatch_job(job, selected_node):

    dispatched_at = utc_now()
    assignment = JobAssignment(
        job_id=job.job_id,
        image=job.image,
        command=job.command,
        dispatched_at=dispatched_at,
        # Carried through so the agent can enforce the declaration on the
        # container rather than leaving it as an unchecked claim.
        requirements=job.requirements,
    )

    try:
        state = {
            "nodes": len(cluster_state.get_nodes()),
            "queue_size": cluster_state.queue_size(),
            "running_jobs": sum(cluster_state.running_jobs.values()),
        }

        logger.event(
            "job.dispatch",
            f"Dispatching job {job.job_id} to {selected_node.node_id}",
            state=state,
            job_id=job.job_id,
            node_id=selected_node.node_id,
            image=job.image,
        )

        # mode="json" renders datetimes as ISO strings; a plain model_dump()
        # hands requests a datetime object it cannot serialise.
        response = requests.post(
            f"{selected_node.agent_url}/execute",
            json=assignment.model_dump(mode="json")
        )

        response.raise_for_status()

        logger.info(
            f"Job {job.job_id} accepted on {selected_node.node_id}",
            job_id=job.job_id,
            node_id=selected_node.node_id,
            status_code=response.status_code,
        )

        # Persist dispatch to database
        db.dispatch_job(job.job_id, selected_node.node_id, dispatched_at)
        cluster_state.forget_dispatch_attempts(job.job_id)

    except Exception as e:
        state = {
            "nodes": len(cluster_state.get_nodes()),
            "queue_size": cluster_state.queue_size(),
        }

        logger.error(
            f"Failed to dispatch job {job.job_id}: {e}",
            state=state,
            job_id=job.job_id,
            node_id=selected_node.node_id,
            error=str(e),
        )

        cluster_state.release_slot(job.job_id)

        attempts = cluster_state.record_dispatch_failure(job.job_id)

        if attempts >= Config.MAX_DISPATCH_ATTEMPTS:
            cluster_state.forget_dispatch_attempts(job.job_id)
            db.mark_job_failed(job.job_id)

            logger.event(
                "job.abandoned",
                f"Giving up on job {job.job_id} after {attempts} dispatch attempts",
                state=state,
                job_id=job.job_id,
                attempts=attempts,
            )
            return

        cluster_state.enqueue_job(job)
        return


def select_node_for(job):
    """
    Block until a node has been chosen for `job` and a slot reserved on it.

    Returns the reserved node. The caller owns that slot and must release it
    if the job never runs.
    """
    waiting_since = None

    while True:

        available_nodes = cluster_state.get_available_nodes(job)

        selected_node = policy.select_node(available_nodes, job)

        # A policy must return one of the candidates it was offered. Anything
        # else would bypass the capacity check, so refuse it rather than
        # dispatch onto a node that cannot take the job.
        if selected_node is not None and selected_node not in available_nodes:
            logger.error(
                f"Policy {policy_name} returned a node that was not available",
                job_id=job.job_id,
                node_id=selected_node.node_id,
            )
            selected_node = None

        if selected_node is None:

            nodes = cluster_state.get_nodes()
            state = {
                "nodes": len(nodes),
                "queue_size": cluster_state.queue_size(),
                "running_jobs": sum(cluster_state.running_jobs.values()),
            }

            # Log once when the wait starts, then occasionally, so a long
            # wait for capacity does not bury everything else in the log.
            now = time.time()
            if waiting_since is None:
                waiting_since = now
                if nodes:
                    logger.debug("All nodes busy, waiting...", state=state)
                else:
                    logger.debug("No connected nodes, waiting...", state=state)
            elif now - waiting_since > 10:
                waiting_since = now
                logger.debug(
                    f"Still waiting to place job {job.job_id}",
                    state=state,
                    job_id=job.job_id,
                )

            time.sleep(1)
            continue

        # The node may have expired or filled up since get_available_nodes.
        if not cluster_state.reserve_slot(selected_node.node_id, job):
            continue

        return selected_node


def dispatcher_loop():
    """
    Place one queued job at a time.

    The job is taken off the queue *before* a node is chosen. Selecting first
    meant the policy was consulted on every idle poll, which advanced the
    round-robin counter with elapsed time rather than with the job sequence
    and made placements irreproducible between runs. Dequeuing first also
    means the policy sees the job it is placing, which is what hardware-aware
    and ML policies need.
    """

    while True:

        job = cluster_state.dequeue_job()

        if job is None:
            continue

        selected_node = select_node_for(job)

        state = {
            "nodes": len(cluster_state.get_nodes()),
            "queue_size": cluster_state.queue_size(),
            "running_jobs": sum(cluster_state.running_jobs.values()),
        }

        logger.info(
            f"Selected node {selected_node.node_id} for job {job.job_id}",
            state=state,
            job_id=job.job_id,
            node_id=selected_node.node_id,
            policy=policy_name,
        )

        threading.Thread(
            target=dispatch_job,
            args=(job, selected_node),
            daemon=True
        ).start()


def expiration_loop():

    while True:

        cluster_state.remove_expired_nodes()

        # Log current state periodically
        nodes = cluster_state.get_nodes()
        state = {
            "nodes": len(nodes),
            "queue_size": cluster_state.queue_size(),
            "running_jobs": sum(cluster_state.running_jobs.values()),
        }

        if nodes:
            logger.debug("Cluster status check", state=state)

        time.sleep(5)


@app.get("/")
def root():
    return {"status": "scheduler running"}


@app.post("/register")
def register_node(
    registration: NodeRegistration
):
    cluster_state.register_node(
        registration
    )

    # Persist to database
    db.register_node(
        registration.node_id,
        registration.hostname,
        registration.agent_url
    )
    db.save_node_profile(
        registration.node_id,
        registration.profile.capabilities.model_dump(),
        registration.profile.cpu.model_dump() if registration.profile.cpu else None,
        registration.profile.io.model_dump() if registration.profile.io else None,
        registration.profile.memory.model_dump() if registration.profile.memory else None,
        registration.profile.gpu.model_dump() if registration.profile.gpu else None,
    )

    state = {
        "nodes": len(cluster_state.get_nodes()),
        "queue_size": cluster_state.queue_size(),
    }

    logger.event(
        "node.registered",
        f"Node {registration.node_id} registered",
        state=state,
        node_id=registration.node_id,
        hostname=registration.hostname,
        cpus=registration.profile.capabilities.cpus,
        memory_mb=registration.profile.capabilities.memory_mb,
    )

    return {
        "status": "registered",
        "node_id": registration.node_id
    }


@app.post("/heartbeat")
def heartbeat(heartbeat: NodeHeartbeat):
    """
    Register/update node heartbeat.
    """
    cluster_state.register_heartbeat(heartbeat)

    # Persist to database
    db.update_heartbeat(heartbeat.node_id, heartbeat.current_load)

    logger.debug(
        f"Heartbeat from {heartbeat.node_id}",
        node_id=heartbeat.node_id,
        current_load=heartbeat.current_load,
    )

    return {
        "status": "ok",
        "registered_node": heartbeat.node_id
    }


@app.get("/nodes")
def list_nodes():
    """
    Return all known nodes.
    """
    return cluster_state.get_nodes()


@app.get("/cluster")
def cluster_status():

    nodes = cluster_state.get_nodes()

    node_status = []

    for node in nodes:

        node_status.append(
            {
                "node_id": node.node_id,
                "load": node.current_load,
                "running_jobs": node.running_jobs,
                "cpus": node.profile.capabilities.cpus,
                "memory_mb": node.profile.capabilities.memory_mb,
            }
        )

    return {
        "nodes": len(nodes),
        "queued_jobs": cluster_state.queue_size(),
        "node_status": node_status,
    }


@app.get("/stats")
def job_statistics():
    """
    Get job execution statistics from the database.
    """
    return db.get_job_statistics()


@app.get("/jobs-history")
def jobs_history():
    """
    Get all jobs from the database (persisted history).
    """
    return {
        "jobs": db.get_all_jobs()
    }


@app.get("/jobs-status/{status}")
def jobs_by_status(status: str):
    """
    Get jobs filtered by status (queued, dispatched, completed, failed).
    """
    return {
        "status": status,
        "jobs": db.get_jobs_by_status(status)
    }


@app.get("/job/{job_id}")
def get_job_info(job_id: str):
    """
    Get job metadata and result.
    """
    job = db.get_job(job_id)
    result = db.get_job_result(job_id)

    return {
        "job": job,
        "result": result
    }


@app.get("/node/{node_id}/summary")
def node_job_summary(node_id: str):
    """
    Get job execution summary for a specific node.
    """
    return {
        "node_id": node_id,
        **db.get_node_job_summary(node_id)
    }


@app.post("/runs/start")
def start_run(request: RunStartRequest):
    """
    Open an experiment run.

    Requires a drained cluster: a run whose measurements overlap with jobs
    from the previous one is not a controlled experiment. The policy is
    re-instantiated even when it is unchanged, so per-policy state such as
    the round-robin counter always starts a run from zero.
    """
    global active_run_id, policy, policy_name

    with run_lock:
        if active_run_id is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Run {active_run_id} is still open; finish it first.",
            )

        in_flight = cluster_state.queue_size() + sum(cluster_state.running_jobs.values())
        if in_flight > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cluster is not drained: {in_flight} job(s) still queued or running.",
            )

        if request.policy is not None:
            try:
                policy = get_policy(request.policy)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            policy_name = request.policy.lower()
        else:
            policy = get_policy(policy_name)

        run_id = uuid.uuid4().hex[:12]

        nodes = cluster_state.get_nodes()
        cluster_snapshot = [
            {
                "node_id": n.node_id,
                "hostname": n.hostname,
                "cpus": n.profile.capabilities.cpus,
                "physical_cores": n.profile.capabilities.physical_cores,
                "memory_mb": n.profile.capabilities.memory_mb,
                "architecture": n.profile.capabilities.architecture,
                "gpu": n.profile.capabilities.gpu,
            }
            for n in nodes
        ]

        db.start_run(
            run_id,
            policy=policy_name,
            label=request.label,
            trace=request.trace,
            cluster_snapshot=cluster_snapshot,
            notes=request.notes,
        )

        active_run_id = run_id

    logger.event(
        "run.started",
        f"Run {run_id} started with policy {policy_name}",
        run_id=run_id,
        policy=policy_name,
        label=request.label,
        nodes=len(cluster_snapshot),
    )

    return {
        "run_id": run_id,
        "policy": policy_name,
        "label": request.label,
        "nodes": cluster_snapshot,
    }


@app.post("/runs/finish")
def finish_run():
    """Close the open run. Jobs submitted afterwards carry no run_id."""
    global active_run_id

    with run_lock:
        if active_run_id is None:
            raise HTTPException(status_code=409, detail="No run is open.")

        run_id = active_run_id
        db.finish_run(run_id)
        active_run_id = None

    progress = db.get_run_progress(run_id)

    logger.event(
        "run.finished",
        f"Run {run_id} finished",
        run_id=run_id,
        **progress,
    )

    return {"run_id": run_id, **progress}


@app.get("/runs")
def list_runs():
    """All experiment runs, newest first."""
    return {"active_run_id": active_run_id, "runs": db.get_all_runs()}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    """Run metadata plus job status counts, used to detect a drained trace."""
    run = db.get_run(run_id)

    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")

    return {"run": run, "progress": db.get_run_progress(run_id)}


@app.get("/runs/{run_id}/jobs")
def get_run_jobs(run_id: str):
    """Every job in a run with its execution result attached."""
    if db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")

    return {"run_id": run_id, "jobs": db.get_run_jobs(run_id)}


@app.post("/jobs")
def submit_job(job: JobRequest):

    cluster_state.enqueue_job(job)

    # Measured from when the client submitted, not when this row is written,
    # so queue wait reflects the scheduler's delay rather than the DB's.
    submitted_at = job.submitted_at or utc_now()
    db.submit_job(
        job.job_id,
        job.image,
        job.command,
        run_id=active_run_id,
        submitted_at=submitted_at,
        requirements=job.requirements,
    )

    state = {
        "nodes": len(cluster_state.get_nodes()),
        "queue_size": cluster_state.queue_size(),
        "running_jobs": sum(cluster_state.running_jobs.values()),
    }

    logger.event(
        "job.submitted",
        f"Job {job.job_id} submitted",
        state=state,
        job_id=job.job_id,
        image=job.image,
        command=job.command,
    )

    return {
        "status": "queued",
        "job_id": job.job_id,
        "queue_size": cluster_state.queue_size()
    }

@app.post("/job_callback")
def job_callback(result: JobResult):
    cluster_state.release_slot(result.job_id)

    # Persist job result to database
    completed_at = result.completed_at or utc_now()
    db.record_job_result(
        result.job_id,
        result.node_id,
        result.success,
        result.runtime_seconds,
        result.exit_code,
        completed_at
    )

    state = {
        "nodes": len(cluster_state.get_nodes()),
        "queue_size": cluster_state.queue_size(),
        "running_jobs": sum(cluster_state.running_jobs.values()),
        "db_jobs_completed": db.get_job_statistics().get("completed", 0),
    }

    event_type = "job.completed" if result.success else "job.failed"
    status_str = "completed" if result.success else "failed"

    logger.event(
        event_type,
        f"Job {result.job_id} {status_str}",
        state=state,
        job_id=result.job_id,
        node_id=result.node_id,
        runtime_seconds=result.runtime_seconds,
        exit_code=result.exit_code,
        success=result.success,
    )

    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """
    Get real-time metrics from database and current state.
    Useful for monitoring dashboards and understanding scheduler behavior.
    """
    nodes = cluster_state.get_nodes()

    # Availability is per job now, so this reports it for a nominal
    # single-slot job with no special requirements.
    probe = JobRequest(job_id="__metrics_probe__", image="")
    available_nodes = cluster_state.get_available_nodes(probe)

    job_stats = db.get_job_statistics()

    # Calculate node utilization
    total_capacity = sum(n.profile.capabilities.cpus for n in nodes)
    used_capacity = sum(cluster_state.running_jobs.get(n.node_id, 0) for n in nodes)

    return {
        "timestamp": utc_now().isoformat(),
        "cluster": {
            "nodes_total": len(nodes),
            "nodes_available": len(available_nodes),
            "nodes_busy": len(nodes) - len(available_nodes),
        },
        "capacity": {
            "total_cpus": total_capacity,
            "used_cpus": used_capacity,
            "available_cpus": total_capacity - used_capacity,
            "utilization_pct": round((used_capacity / total_capacity * 100) if total_capacity > 0 else 0, 1),
        },
        "queue": {
            "queued": cluster_state.queue_size(),
            "running": sum(cluster_state.running_jobs.values()),
        },
        "jobs": {
            "total": job_stats.get("total_jobs", 0),
            "completed": job_stats.get("completed", 0),
            "failed": job_stats.get("failed", 0),
            "dispatched": job_stats.get("dispatched", 0),
            "queued_db": job_stats.get("queued", 0),
        },
        "performance": {
            "avg_runtime_seconds": job_stats.get("avg_runtime_seconds"),
            "min_runtime_seconds": job_stats.get("min_runtime_seconds"),
            "max_runtime_seconds": job_stats.get("max_runtime_seconds"),
        },
        "nodes": [
            {
                "node_id": n.node_id,
                "hostname": n.hostname,
                "cpus": n.profile.capabilities.cpus,
                "memory_mb": n.profile.capabilities.memory_mb,
                "current_load": n.current_load,
                "running_jobs": cluster_state.running_jobs.get(n.node_id, 0),
            }
            for n in nodes
        ],
    }


@app.on_event("startup")
def startup_event():

    logger.info(
        "Scheduler starting",
        config=Config.__str__(),
        database=db.DATABASE_PATH,
        policy=policy_name,
    )

    # Initialize database
    db.init_db()
    logger.info(f"Database initialized: {db.DATABASE_PATH}")
    logger.info(f"Using scheduling policy: {policy_name}")

    logger.info("Starting dispatcher thread")

    dispatcher_thread = threading.Thread(
        target=dispatcher_loop,
        daemon=True
    )

    dispatcher_thread.start()

    logger.info("Starting expiration thread")

    expiration_thread = threading.Thread(
        target=expiration_loop,
        daemon=True
    )

    expiration_thread.start()

    logger.info("Scheduler startup complete")