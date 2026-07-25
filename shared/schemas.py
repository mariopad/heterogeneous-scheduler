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
    pass


class GPUBenchmarkProfile(BaseModel):
    pass


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

    current_load:float
    running_jobs: int


class JobRequest(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None


class JobAssignment(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None


class JobResult(BaseModel):
    job_id: str
    node_id: str
    success: bool
    runtime_seconds: float
    exit_code: int