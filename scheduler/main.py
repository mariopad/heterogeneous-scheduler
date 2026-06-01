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
    - Node expiration
"""

from fastapi import FastAPI, HTTPException
from scheduler.state import cluster_state
from shared.schemas import (
    NodeHeartbeat,
    JobRequest,
    JobAssignment
)
import requests
import threading
import time


app = FastAPI(title="HeteroSched Scheduler")


def dispatch_job(job, selected_node):

    assignment = JobAssignment(
        job_id=job.job_id,
        image=job.image,
        command=job.command
    )

    try:

        print(
            f"[dispatch] "
            f"job={job.job_id} "
            f"node={selected_node.node_id}"
        )

        response = requests.post(
            f"{selected_node.agent_url}/execute",
            json=assignment.model_dump()
        )

        print(
            f"[completed] "
            f"job={job.job_id} "
            f"status={response.status_code}"
        )

    except Exception as e:

        print(
            f"[dispatch error] "
            f"job={job.job_id} "
            f"error={e}"
        )

        cluster_state.enqueue_job(job)
    
    finally:
        cluster_state.decrement_running_jobs(
            selected_node.node_id
        )


def dispatcher_loop():

    while True:

        selected_node = cluster_state.get_next_node_round_robin()

        if selected_node is None:

            nodes = cluster_state.get_nodes()
            
            if nodes:
                print("[dispatcher] all nodes busy")
            else:
                print("[dispatcher] no connected nodes")

            time.sleep(1) # Mirar esto en un futuro

            continue

        job = cluster_state.dequeue_job()

        print(f"[dispatcher] picked job={job.job_id}")

        # Update running_jobs in selected node
        cluster_state.increment_running_jobs(
            selected_node.node_id
        )

        threading.Thread(
            target=dispatch_job,
            args=(job, selected_node),
            daemon=True
        ).start()


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


# Esto bloquea, vamos a sustituirlo por queue jobs para 
# desacoplar recepción de ejecución

# Problema: necesito hacer algo para que alguien ejecute
# los jobs, ahora solo los pongo en cola

# Lo sustituyo por dispatcher_loop, que quita de la cola trabajos
# y los asigna si puede. Si falla, añade fault tolerance. Tambien
# sustituyo por enqueing trabajos una vez que los detectamos.

# @app.post("/jobs")
# def submit_job(job: JobRequest):
#     """
#     Submit a new job.
#     """
#     selected_node = cluster_state.get_next_node_round_robin()
# 
#     if selected_node is None:
#         raise HTTPException(
#             status_code=503,
#             detail="No nodes available"
#         )
#     
#     assignment = JobAssignment(
#         job_id=job.job_id,
#         image=job.image,
#         command=job.command
#     )
# 
#     response = requests.post(
#         f"{selected_node.agent_url}/execute",
#         json=assignment.model_dump()
#     )
# 
#     return response.json()

@app.post("/jobs")
def submit_job(job: JobRequest):

    cluster_state.enqueue_job(job)

    return {
        "status": "queued",
        "job_id": job.job_id,
        "queue_size": cluster_state.queue_size()
    }

@app.on_event("startup")
def startup_event():

    print("[startup] dispatcher thread")

    dispatcher_thread = threading.Thread(
        target=dispatcher_loop,
        daemon=True
    )

    dispatcher_thread.start()