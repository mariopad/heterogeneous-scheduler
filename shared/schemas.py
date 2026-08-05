"""
shared/schemas.py

This script defines:
    - How does scheduler and agents communicate
    - Job format
    - Heartbeats
    - Results
"""

from pydantic import BaseModel, Field
from typing import Optional
from typing import Dict, Literal
from datetime import datetime
from enum import Enum


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


class WorkloadType(str, Enum):
    """
    Which subsystem a job mainly stresses.

    This is the field that lets a hardware-aware policy reason about fit: a
    memory-bound job belongs on the node with the best measured bandwidth,
    not merely on the one with the most idle cores.
    """
    CPU = "cpu"
    MEMORY = "memory"
    IO = "io"
    GPU = "gpu"
    MIXED = "mixed"


class JobRequirements(BaseModel):
    """
    What a job needs, declared by whoever submits it.

    Kept as one object rather than loose fields on JobRequest because this is
    also the feature vector a learned policy will consume, and because the
    scheduler has to pass the whole thing to the agent so the declaration is
    actually enforced on the container instead of being advisory.
    """

    workload_type: WorkloadType = WorkloadType.MIXED

    #: Slots the job occupies on a node. The capacity model counts these, so a
    #: job that really uses four cores must say so or it will oversubscribe.
    cpu_request: int = Field(default=1, ge=1)

    #: Applied as a hard container limit by the agent. None means unlimited.
    memory_mb: Optional[int] = Field(default=None, ge=1)

    #: Nodes without a GPU are not candidates at all when this is set.
    requires_gpu: bool = False

    #: Submitter's rough expectation. Advisory only -- unlike `size` it is a
    #: guess, so nothing load-bearing should depend on it, but it is a cheap
    #: feature for a learned policy and useful for grouping results.
    expected_duration_class: Optional[Literal["short", "medium", "long"]] = None

    #: The workload's scale parameter, when the job came from the workload
    #: suite. Objective, unlike expected_duration_class.
    size: Optional[int] = None


class JobRequest(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None
    submitted_at: Optional[datetime] = None

    requirements: JobRequirements = Field(default_factory=JobRequirements)


class JobAssignment(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None
    dispatched_at: Optional[datetime] = None

    requirements: JobRequirements = Field(default_factory=JobRequirements)


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