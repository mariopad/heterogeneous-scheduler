"""
shared/schemas.py

This script defines:
    - How does scheduler and agents communicate
    - Job format
    - Heartbeats
    - Results
"""

from pydantic import BaseModel
from typing import Optional
from typing import Dict
from datetime import datetime


class NodeCapabilities(BaseModel):
    cpus: int # logical_cores
    physical_cores:int
    memory_mb: int
    gpu: bool
    architecture: str


class CPUBenchmarkProfile(BaseModel):
    cpu_single_core_gflops_mean: float
    cpu_single_core_gflops_std: float

    cpu_node_gflops_mean: float
    cpu_node_gflops_std: float

    cpu_scaling_efficiency_pct: float


class IOBenchmarkProfile(BaseModel):
    disk_seq_read_mbps_mean: float
    disk_seq_read_mbps_std: float

    disk_seq_write_mbps_mean: float
    disk_seq_write_mbps_std: float

    disk_rand_read_iops_mean: float
    disk_rand_read_iops_std: float

    disk_rand_write_iops_mean: float
    disk_rand_write_iops_std: float

    disk_seq_read_latency_us_mean: float
    disk_seq_read_latency_us_std: float

    disk_seq_write_latency_us_mean: float
    disk_seq_write_latency_us_std: float

    disk_rand_read_latency_us_mean: float
    disk_rand_read_latency_us_std: float

    disk_rand_write_latency_us_mean: float
    disk_rand_write_latency_us_std: float


class MEMBenchmarkProfile(BaseModel):
    ram_seq_read_mbps_mean:float 
    ram_seq_read_mbps_std: float

    ram_seq_write_mbps_mean: float
    ram_seq_write_mbps_std: float

    ram_random_latency_us_mean: float
    ram_random_latency_us_std: float


class GPUBenchmarkProfile(BaseModel):
    gpu_available: bool
    gpu_memory_mb: Optional[int]


class NETBenchmarkProfile(BaseModel):
    pass


class NodeProfile(BaseModel):
    capabilities: NodeCapabilities

    cpu: Optional[CPUBenchmarkProfile] = None
    io: Optional[IOBenchmarkProfile] = None
    memory: Optional[MEMBenchmarkProfile] = None
    gpu: Optional[GPUBenchmarkProfile] = None
    network: Optional[NETBenchmarkProfile] = None


"""
Agent starts -> bench -> POST 
-> profile storaged -> periodic hbs
"""
class NodeHeartbeat(BaseModel):
    node_id: str
    current_load: float
class NodeRegistration(BaseModel):
    node_id: str
    hostname: str
    agent_url: str
    profile: NodeProfile


class NodeView(BaseModel):
    node_id: str
    hostname: str
    agent_url: str

    profile: NodeProfile

    # Measured on the agent, refreshed once per heartbeat -- lags reality.
    current_load: float

    # Owned by the scheduler, exact and updated at dispatch time.
    running_jobs: int

    # running_jobs normalised by core count, in [0, 1). Lets a policy compare
    # a 4-core board against a 12-thread desktop on equal terms.
    slot_occupancy: float = 0.0


class JobRequest(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None
    submitted_at: Optional[datetime] = None


class JobAssignment(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None
    dispatched_at: Optional[datetime] = None


class RunStartRequest(BaseModel):
    """Open an experiment run. Jobs submitted while it is open belong to it."""
    label: Optional[str] = None
    trace: Optional[str] = None
    notes: Optional[str] = None

    # Swap the active policy for this run. Omitted means keep the current one.
    policy: Optional[str] = None


class RunView(BaseModel):
    run_id: str
    label: Optional[str] = None
    policy: str
    trace: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobResult(BaseModel):
    job_id: str
    node_id: str
    success: bool
    runtime_seconds: float
    exit_code: int
    completed_at: Optional[datetime] = None