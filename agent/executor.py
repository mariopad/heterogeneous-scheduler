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
from datetime import datetime

from shared.schemas import (
    JobAssignment,
    JobResult,
)
from shared.logging import get_logger
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


def run_and_callback(node_id: str, assignment: JobAssignment):
    """
    Run Docker container, measure runtime and notify scheduler.
    """
    start_time = time.time()
    success = False
    exit_code = -1

    try:
        logger.info(
            f"Executing job {assignment.job_id}",
            job_id=assignment.job_id,
            image=assignment.image,
            command=assignment.command,
        )

        container = client.containers.run(
            image=assignment.image,
            command=assignment.command,
            detach=True,
            remove=True
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
    completed_at = datetime.utcnow()

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