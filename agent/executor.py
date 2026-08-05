"""
agent/executor.py

This script performs the following:
    - Launches Docker container
    - Launches detached
    - Launches autoremove
"""

import time
import docker
import threading
import os

from shared.schemas import (
    JobAssignment,
    JobResult,
)
from shared.logging import get_logger
from shared.timeutils import utc_now
import requests

SCHEDULER_URL = os.getenv("SCHEDULER_URL", "http://localhost:8000")
logger = get_logger("executor")


def get_docker_client():
    """Get or create Docker client connection."""
    try:
        return docker.from_env()
    except Exception as e:
        print("Docker not available:", e)
        return None


client = get_docker_client()


def container_limits(assignment: JobAssignment) -> dict:
    """
    Translate the job's declared requirements into Docker options.

    Enforcing them matters for the experiment, not just for safety: if a job
    that declared 512 MB can quietly use 4 GB, the scheduler's memory
    accounting stops describing the node and placements based on it are
    measuring nothing.
    """
    requirements = assignment.requirements
    options = {}

    if requirements.memory_mb:
        options["mem_limit"] = f"{requirements.memory_mb}m"

    if requirements.cpu_request:
        # Docker's CPU quota is expressed in units of 100000 per core.
        options["cpu_period"] = 100000
        options["cpu_quota"] = 100000 * requirements.cpu_request

    if requirements.requires_gpu:
        # Ask for every GPU on the node. docker-py's device_requests is the
        # API equivalent of `--gpus all`.
        options["device_requests"] = [
            docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
        ]

    return options


def run_and_callback(node_id: str, assignment: JobAssignment):
    """
    Run Docker container, measure runtime and notify scheduler.
    """
    start_time = time.time()
    success = False
    exit_code = -1

    try:
        limits = container_limits(assignment)

        logger.info(
            f"Executing job {assignment.job_id}",
            job_id=assignment.job_id,
            image=assignment.image,
            command=assignment.command,
            workload_type=assignment.requirements.workload_type.value,
            limits={k: v for k, v in limits.items() if k != "device_requests"},
        )

        container = client.containers.run(
            image=assignment.image,
            command=assignment.command,
            detach=True,
            remove=True,
            **limits,
        )

        result = container.wait()
        exit_code = result["StatusCode"]
        success = exit_code == 0

    except Exception as e:
        logger.error(
            f"Job execution failed: {e}",
            job_id=assignment.job_id,
            error=str(e),
        )

    runtime = time.time() - start_time
    completed_at = utc_now()

    job_result = JobResult(
        job_id=assignment.job_id,
        node_id=node_id,
        success=success,
        runtime_seconds=runtime,
        exit_code=exit_code,
        completed_at=completed_at
    )

    status = "completed" if success else "failed"
    logger.event(
        f"job.{status}",
        f"Job {assignment.job_id} {status}",
        job_id=assignment.job_id,
        runtime_seconds=runtime,
        exit_code=exit_code,
        success=success,
    )

    # Callback to scheduler
    try:
        response = requests.post(
            f"{SCHEDULER_URL}/job_callback",
            json=job_result.model_dump(mode="json")
        )
        response.raise_for_status()
        logger.debug(
            f"Job result reported to scheduler",
            job_id=assignment.job_id,
        )
    except Exception as e:
        logger.error(
            f"Failed to notify scheduler: {e}",
            job_id=assignment.job_id,
            error=str(e),
        )


def execute_job_async(node_id: str, assignment: JobAssignment):
    """Launch background thread for the job."""
    thread = threading.Thread(
        target=run_and_callback,
        args=(node_id, assignment),
        daemon=True
    )
    thread.start()