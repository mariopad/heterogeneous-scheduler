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
import json
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

from agent.executor import execute_job_async
from agent.benchmark import benchmark_cpu

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


# Benchmark
print(f"\n{'='*60}")
print(f"[boot] Node {NODE_ID} starting...")
print(f"[boot] Running hardware benchmark")
print(f"{'='*60}\n")

BENCHMARK_RESULTS = benchmark_cpu()

# Guardar resultados en archivo (como mencionaste)
with open(f"benchmarks/benchmark_{NODE_ID}.txt", "w") as f:
    f.write(f"Node: {NODE_ID}\n")
    f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"{'='*60}\n")
    for key, value in BENCHMARK_RESULTS.items():
        f.write(f"{key}: {value}\n")

print(f"[boot] Benchmark complete! Results saved to benchmark_{NODE_ID}.txt")
print(f"{'='*60}\n")


app = FastAPI(title=f"Agent {NODE_ID}")


# To-do:
### fix gpu detection if needed and gpu_score
def detect_capabilities() -> NodeCapabilities:
    """
    Detect local hardware capabilities.
    """

    total_memory_mb = int(
        psutil.virtual_memory().total / (1024 * 1024)
    ) # Podemos cachearlo sino

    return NodeCapabilities(
        cpus=os.cpu_count() or 1,
        memory_mb=total_memory_mb,
        gpu=False,  # later
        architecture=os.uname().machine
    )
    # return NodeCapabilities(
    #     cpus=BENCHMARK_RESULTS.get("logical_cores", os.cpu_count() or 1),
    #     memory_mb=BENCHMARK_RESULTS.get("total_memory_mb", 
    #                                     int(psutil.virtual_memory().total / (1024 * 1024))),
    #     gpu=BENCHMARK_RESULTS.get("gpu_available", False),
    #     architecture=BENCHMARK_RESULTS.get("architecture", os.uname().machine),
    #     # Añadir los nuevos campos de benchmark
    #     cpu_single_core_gflops=BENCHMARK_RESULTS.get("cpu_single_core_gflops", 0.0),
    #     cpu_multi_core_gflops=BENCHMARK_RESULTS.get("cpu_multi_core_gflops", 0.0),
    #     cpu_scaling_efficiency_pct=BENCHMARK_RESULTS.get("cpu_scaling_efficiency_pct", 0.0),
    # )


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
    execute_job_async(node_id=NODE_ID, assignment=assignment)
    return {"status": "accepted", "job_id": assignment.job_id}



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