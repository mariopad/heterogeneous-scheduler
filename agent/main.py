"""
agent/main.py
Agent bootstrap:
1. Detect static capabilities
2. Run benchmarks
3. Build NodeProfile
4. Start heartbeat + API
"""


import os
import sys
import time
import json
import socket
import requests
import psutil
import threading
from fastapi import FastAPI
import platform
import argparse

from shared.schemas import (
    NodeHeartbeat,
    NodeProfile,
    NodeRegistration,
    NodeCapabilities,
    JobAssignment
)
from shared.config import Config
from shared.logging import get_logger

from agent.executor import execute_job_async

logger = get_logger("agent")
from agent.benchmark.cpu import benchmark_cpu
from agent.benchmark.io import benchmark_disk
from agent.benchmark.memory import benchmark_memory
from agent.benchmark.gpu import benchmark_gpu
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
    logger.info("Registering with scheduler...")

    try:
        response = requests.post(
            f"{SCHEDULER_URL}/register",
            json=registration.model_dump()
        )
        response.raise_for_status()
        logger.info(
            "Node registered successfully",
            scheduler_url=SCHEDULER_URL,
            status_code=response.status_code,
        )
    except Exception as e:
        logger.error(
            f"Failed to register node: {e}",
            scheduler_url=SCHEDULER_URL,
            error=str(e),
        )
        raise


####################################
# HEARTBEAT
####################################
def send_heartbeat():
    heartbeat = NodeHeartbeat(
        node_id=NODE_ID,
        current_load=get_current_load()
    )

    try:
        response = requests.post(
            f"{SCHEDULER_URL}/heartbeat",
            json=heartbeat.model_dump()
        )
        response.raise_for_status()
        logger.debug(
            f"Heartbeat sent",
            current_load=heartbeat.current_load,
        )
    except Exception as e:
        logger.warning(
            f"Failed to send heartbeat: {e}",
            error=str(e),
        )


def heartbeat_loop():
    while True:
        try:
            send_heartbeat()
        except Exception as e:
            logger.error(
                f"Heartbeat loop error: {e}",
                error=str(e),
            )

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
# ARGUMENT PARSING
####################################
def parse_args():
    parser = argparse.ArgumentParser(
        description="Start a scheduler agent node with optional debug mode."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode: reduced iterations for faster testing"
    )
    return parser.parse_args()


####################################
# MAIN
####################################
def main():
    args = parse_args()

    if args.debug:
        Config.set_debug(True)

    logger.info(
        "Agent starting",
        node_id=NODE_ID,
        platform=platform.machine(),
        config=Config.__str__(),
        agent_port=AGENT_PORT,
        scheduler_url=SCHEDULER_URL,
    )

    # 1. Capabilities
    logger.info("Detecting hardware capabilities...")
    capabilities = detect_capabilities()

    # 2. Benchmarks
    logger.info("Running hardware benchmarks...")
    benchmark_results = run_full_benchmark(capabilities)
    failed_benchmarks = benchmark_results.pop("_failed", {})

    # 3. NODE PROFILE
    node_profile = NodeProfile(
        capabilities=capabilities,
        cpu=benchmark_results.get("cpu"),
        io=benchmark_results.get("io"),
        memory=benchmark_results.get("memory"),
        gpu=benchmark_results.get("gpu"),
        network=None,
    )

    if failed_benchmarks:
        # Still register: a partially profiled node is more useful than an
        # absent one. But say so, because the gap silently limits which
        # policies can rank this node.
        logger.warning(
            f"Registering with an incomplete profile; "
            f"{', '.join(sorted(failed_benchmarks))} unavailable",
            failed=failed_benchmarks,
            available=sorted(benchmark_results),
        )

    logger.info("Benchmarks complete", benchmarks=sorted(benchmark_results.keys()))

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

    logger.info("Benchmark results saved")

    # 6. Heartbeat thread
    logger.info("Starting heartbeat thread")
    thread = threading.Thread(
        target=heartbeat_loop,
        daemon=True
    )
    thread.start()

    # 7. START API
    logger.info(
        f"Starting agent API server",
        host="0.0.0.0",
        port=AGENT_PORT,
    )

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AGENT_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()