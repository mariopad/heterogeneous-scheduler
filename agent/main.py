"""
agent/main.py
Agent bootstrap:
1. Detect static capabilities
2. Run benchmarks
3. Build NodeProfile
4. Start heartbeat + API
"""


import os
import time
import json
import socket
import requests
import psutil
import threading
from fastapi import FastAPI
import platform

from shared.schemas import (
    NodeHeartbeat,
    NodeProfile,
    NodeRegistration,
    NodeCapabilities,
    JobAssignment
)

from agent.executor import execute_job_async
from agent.benchmark.cpu import benchmark_cpu
from agent.benchmark.io import benchmark_disk
from agent.benchmark.memory import benchmark_memory
from agent.benchmark.runner import run_full_benchmark



SCHEDULER_URL = os.getenv("SCHEDULER_URL", "http://localhost:8000")
NODE_ID = os.getenv("NODE_ID", socket.gethostname())
AGENT_PORT = int(os.getenv("AGENT_PORT", 9000))
HEARTBEAT_INTERVAL = 5


####################################
# APP
####################################
app = FastAPI(title=f"Agent {NODE_ID}")


####################################
# CAPABILITIES
####################################
def detect_capabilities() -> NodeCapabilities:
    """
    Detect local hardware capabilities.
    """

    logical_cores = os.cpu_count() or 1
    physical_cores = psutil.cpu_count(logical=False) or logical_cores

    total_memory_mb = int(psutil.virtual_memory().total / (1024 * 1024))

    return NodeCapabilities(
        cpus=logical_cores,
        physical_cores=physical_cores,
        memory_mb=total_memory_mb,
        gpu=False,
        architecture=platform.machine(),
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


####################################
# LOAD
####################################
def get_current_load() -> float:
    return psutil.cpu_percent(interval=1) / 100.0


####################################
# REGISTER NODE
####################################
def node_registration(registration: NodeRegistration):
    print("[boot] Registering node...")

    response = requests.post(
        f"{SCHEDULER_URL}/register",
        json=registration.model_dump()
    )

    print(
        f"[boot] Registration status={response.status_code}"
    )


####################################
# HEARTBEAT
####################################
def send_heartbeat():
    heartbeat = NodeHeartbeat(
        node_id=NODE_ID,
        current_load=get_current_load()
    )

    response = requests.post(
        f"{SCHEDULER_URL}/heartbeat",
        json=heartbeat.model_dump()
    )

    print(f"[heartbeat] status={response.status_code} node={NODE_ID}")


def heartbeat_loop():
    while True:
        try:
            send_heartbeat()
        
        except Exception as e:
            print(f"[Heartbeat error] {e}")
        
        time.sleep(HEARTBEAT_INTERVAL)


####################################
# API
####################################
@app.get("/")
def root():
    return {"status": "agent running"}


@app.post("/execute")
def execute(assignment: JobAssignment):
    execute_job_async(node_id=NODE_ID, assignment=assignment)
    return {"status": "accepted", "job_id": assignment.job_id}


####################################
# MAIN
####################################
def main():

    print(f"\n{'='*60}")
    print(f"[boot] Node {NODE_ID} starting...")
    print(f"[boot] Platform: {platform.machine()}")
    print(f"{'='*60}\n")

    # 1. Capabilities
    capabilities = detect_capabilities()

    # 2. Benchmarks
    #print("[boot] Running CPU benchmark...")
    cpu_profile = benchmark_cpu(capabilities)
    #benchmark_results = run_full_benchmark(capabilities)
    #io_profile = benchmark_disk()
    mem_profile = benchmark_memory()

    # 3. NODE PROFILE
    node_profile = NodeProfile(
        capabilities=capabilities,
        cpu=cpu_profile,
        io=None,
        memory=None,
        gpu=None,
        network=None,
    )

    # 4. Node registration
    registration = NodeRegistration(
        node_id=NODE_ID,
        hostname=socket.gethostname(),
        agent_url=f"http://localhost:{AGENT_PORT}",
        profile=node_profile
    )
    node_registration(registration)

    # 5. Save benchmarks
    os.makedirs("logs/benchmarks", exist_ok=True)

    with open(f"logs/benchmarks/benchmark_{NODE_ID}.txt", "w") as f:
        f.write(str(node_profile.model_dump()))

    print("[boot] Benchmark complete")

    # 6. Heartbeat thread
    thread = threading.Thread(
        target=heartbeat_loop,
        daemon=True
    )
    thread.start()

    # 7. START API
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AGENT_PORT
    )


if __name__ == "__main__":
    main()