"""
This script performs the following:
    - Launches Docker container
    - Launches detached
    - Launches autoremove
"""


import time
import docker

from shared.schemas import (
    JobAssignment,
    JobResult,
)

def get_docker_client():
    try:
        return docker.from_env()
    except Exception as e:
        print("Docker not available:", e)
        return None
    
client = get_docker_client()


def execute_job(
    node_id: str,
    assignment: JobAssignment
) -> JobResult:
    """
    Execute Docker container job and measure runtime.
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

    return JobResult(
        job_id=assignment.job_id,
        node_id=node_id,
        success=success,
        runtime_seconds=runtime,
        exit_code=exit_code
    )