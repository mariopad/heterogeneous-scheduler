"""
- Initializes FastAPI
- Receives heartbeats
- Lists nodes
- Receives jobs
- Select node using Round Robin / selected policy**
"""

"""
To-dos
    - Change selection policy
"""

from fastapi import FastAPI, HTTPException
from scheduler.state import cluster_state
from shared.schemas import (
    NodeHeartbeat,
    JobRequest,
    JobAssignment
)
import requests


app = FastAPI(title="HeteroSched Scheduler")


@app.get("/")
def root():
    return {"status": "scheduler running"}


@app.post("/heartbeat")
def heartbeat(heartbeat: NodeHeartbeat):
    """
    Register/update node heartbeat.
    """
    cluster_state.register_heartbeat(heartbeat)

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


@app.post("/jobs")
def submit_job(job: JobRequest):
    """
    Submit a new job.
    """
    selected_node = cluster_state.get_next_node_round_robin()

    if selected_node is None:
        raise HTTPException(
            status_code=503,
            detail="No nodes available"
        )
    
    assignment = JobAssignment(
        job_id=job.job_id,
        image=job.image,
        command=job.command
    )

    response = requests.post(
        f"{selected_node.agent_url}/execute",
        json=assignment.model_dump()
    )

    return response.json()