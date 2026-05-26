"""
Agent needs to accomplish the following:
    1. Booting:
        - Detect hw and provide metrics
        - Generate node_id
    2. Loop:
        - Send heartbeat every few seconds
"""


import os
import time
import socket
import requests
import psutil
import threading
from fastapi import FastAPI

from shared.schemas import (
    NodeHeartbeat,
    NodeCapabilities,
    JobAssignment
)

from agent.executor import execute_job

SCHEDULER_URL = os.getenv(
    "SCHEDULER_URL",
    "http://localhost:8000"
)

NODE_ID = os.getenv(
    "NODE_ID",
    socket.gethostname()
)

AGENT_PORT = int(
    os.getenv("AGENT_PORT", 9000)
)

HEARTBEAT_INTERVAL = 5

app = FastAPI(title=f"Agent {NODE_ID}")


# To-do:
## benchmark.py usage
### cpus -> cpu_score
### fix gpu detection if needed and gpu_score
def detect_capabilities() -> NodeCapabilities:
    """
    Detect local hardware capabilities.
    """

    total_memory_mb = int(
        psutil.virtual_memory().total / (1024 * 1024)
    ) # Podemos cachearlo si no

    return NodeCapabilities(
        cpus=os.cpu_count() or 1,
        memory_mb=total_memory_mb,
        gpu=False,  # later
        architecture=os.uname().machine
    )


def get_current_load() -> float:
    """
    Return normalized CPU usage.
    """
    return psutil.cpu_percent(interval=1) / 100.0


def send_heartbeat():
    capabilities = detect_capabilities()

    heartbeat = NodeHeartbeat(
        node_id=NODE_ID,
        hostname=socket.gethostname(),
        agent_url=f"http://localhost:{AGENT_PORT}",
        capabilities=capabilities,
        current_load=get_current_load()
    )

    response = requests.post(
        f"{SCHEDULER_URL}/heartbeat",
        json=heartbeat.model_dump()
    )

    print(
        f"[heartbeat] status={response.status_code} "
        f"node={NODE_ID}"
    )


def heartbeat_loop():
    while True:
        try:
            send_heartbeat()
        
        except Exception as e:
            print(f"[Heartbeat error] {e}")
        
        time.sleep(HEARTBEAT_INTERVAL)


@app.get("/")
def root():
    return {"status": "agent running"}


@app.post("/execute")
def execute(assignment: JobAssignment):
    result = execute_job(
        node_id=NODE_ID,
        assignment=assignment
    )

    return result



def main():

    thread = threading.Thread(
        target=heartbeat_loop,
        daemon=True
    )

    thread.start()

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AGENT_PORT
    )


if __name__ == "__main__":
    main()