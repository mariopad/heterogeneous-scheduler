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
    - Change selection policy
    - Improve node expiration workflow
        healthy -> scheduler assigns jobs normally
        stale -> scheduler does not assign new jobs
        dead -> erases node -> job rescheduling
"""

from fastapi import FastAPI
from scheduler.state import cluster_state
from scheduler import db
from shared.schemas import (
    NodeRegistration,
    NodeHeartbeat,
    JobRequest,
    JobAssignment,
    JobResult
)
from shared.config import Config
from shared.logging import get_logger
import requests
import threading
import time
import os
import sys
import argparse
from datetime import datetime

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

app = FastAPI(title="HeteroSched Scheduler")


def dispatch_job(job, selected_node):

    dispatched_at = datetime.utcnow()
    assignment = JobAssignment(
        job_id=job.job_id,
        image=job.image,
        command=job.command,
        dispatched_at=dispatched_at
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

        response = requests.post(
            f"{selected_node.agent_url}/execute",
            json=assignment.model_dump()
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

        cluster_state.decrement_running_jobs(selected_node.node_id)
        cluster_state.enqueue_job(job)
        return


def dispatcher_loop():

    while True:

        available_nodes = cluster_state.get_available_nodes()

        selected_node = policy.select_node(available_nodes)

        if selected_node is None:

            nodes = cluster_state.get_nodes()
            state = {
                "nodes": len(nodes),
                "queue_size": cluster_state.queue_size(),
                "running_jobs": sum(cluster_state.running_jobs.values()),
            }

            if nodes:
                logger.debug("All nodes busy, waiting...", state=state)
            else:
                logger.debug("No connected nodes, waiting...", state=state)

            time.sleep(1)
            continue

        job = cluster_state.dequeue_job()

        if job is None:
            time.sleep(0.5)
            continue

        state = {
            "nodes": len(cluster_state.get_nodes()),
            "queue_size": cluster_state.queue_size(),
            "running_jobs": sum(cluster_state.running_jobs.values()),
        }

        logger.info(
            f"Selected job {job.job_id} for dispatch",
            state=state,
            job_id=job.job_id,
        )

        # Update running_jobs in selected node
        cluster_state.increment_running_jobs(
            selected_node.node_id
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


@app.post("/jobs")
def submit_job(job: JobRequest):

    cluster_state.enqueue_job(job)

    # Persist to database
    submitted_at = job.submitted_at or datetime.utcnow()
    db.submit_job(job.job_id, job.image, job.command)

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
    cluster_state.decrement_running_jobs(result.node_id)

    # Persist job result to database
    completed_at = result.completed_at or datetime.utcnow()
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
    available_nodes = cluster_state.get_available_nodes()
    job_stats = db.get_job_statistics()

    # Calculate node utilization
    total_capacity = sum(n.profile.capabilities.cpus for n in nodes)
    used_capacity = sum(cluster_state.running_jobs.get(n.node_id, 0) for n in nodes)

    return {
        "timestamp": datetime.utcnow().isoformat(),
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