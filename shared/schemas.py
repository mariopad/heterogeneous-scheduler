"""
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
    cpus: int
    memory_mb: int
    gpu: bool
    architecture: str # Identificador simple nodo


class NodeHeartbeat(BaseModel):
    node_id: str
    hostname: str
    agent_url: str
    capabilities: NodeCapabilities
    current_load: float


class JobRequest(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None #?


class JobAssignment(BaseModel):
    job_id: str
    image: str
    command: Optional[str] = None #?


class JobResult(BaseModel):
    job_id: str
    node_id: str
    success: bool
    runtime_seconds: float
    exit_code: int