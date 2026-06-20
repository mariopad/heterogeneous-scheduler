"""
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
import requests

SCHEDULER_URL = os.getenv("SCHEDULER_URL", "http://localhost:8000")


def get_docker_client():
    try:
        return docker.from_env()
    except Exception as e:
        print("Docker not available:", e)
        return None
    
    
client = get_docker_client()


def run_and_callback(
    node_id: str,
    assignment: JobAssignment
):
    """
    Run Docker container, measure runtime and notify scheduler.
    """
    start_time = time.time()
    success = False
    exit_code = -1

    try:
        print(
            f"[executor] running image={assignment.image} "
            f"job={assignment.job_id}"
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
        print(f"[executor error] {e}")

    runtime = time.time() - start_time

    job_result = JobResult(
        job_id=assignment.job_id,
        node_id=node_id,
        success=success,
        runtime_seconds=runtime,
        exit_code=exit_code
    )

    # Callback to scheduler
    try:
        requests.post(f"{SCHEDULER_URL}/job_callback", json=job_result.model_dump())
    except Exception as e:
        print(f"[callback error] Failed to notify scheduler: {e}")
    

def execute_job_async(node_id: str, assignment: JobAssignment):
    """Background thread for the job."""
    thread = threading.Thread(
        target = run_and_callback,
        args = (node_id, assignment),
        daemon = True
    )
    thread.start()
    #print(f"[executor] Started background thread for job={assignment.job_id}")