"""
scheduler/state.py

Objetivo del script: hacer que funcione esto
    cluster_state.register_node(...)
    cluster_state.get_nodes()
    cluster_state.get_next_node_rr()
"""

from typing import Dict, List, Optional
from shared.schemas import (
    NodeHeartbeat,
    NodeRegistration,
    NodeView,
    JobRequest
)
from queue import Queue
import time
import threading

class ClusterState:
    def __init__(self):
        self.lock = threading.RLock() # evitar racing
        self.registrations: Dict[str, NodeRegistration] = {}
        self.heartbeats: Dict[str, NodeHeartbeat] = {}
        self.job_queue = Queue()
        self.running_jobs: Dict[str, int] = {}
        self.last_heartbeat: Dict[str, float] = {}
        self.dispatch_attempts: Dict[str, int] = {}
        self.allocated_memory: Dict[str, int] = {}
        # job_id -> (node_id, cpu_request, memory_mb) for what it reserved
        self.reservations: Dict[str, tuple] = {}

    # Registry
    def register_heartbeat(self, heartbeat: NodeHeartbeat):
        """Add or update node heartbeat info."""
        with self.lock:
            self.heartbeats[heartbeat.node_id] = heartbeat
            self.last_heartbeat[heartbeat.node_id] = time.time()
            
    def register_node(self, registration: NodeRegistration):
        with self.lock:
            self.registrations[registration.node_id] = registration

            if registration.node_id not in self.running_jobs:
                self.running_jobs[registration.node_id] = 0

    def get_node_view(self, node_id):
        registration = self.registrations.get(node_id)

        if registration is None:
            return None

        heartbeat = self.heartbeats.get(node_id)

        current_load = (
            heartbeat.current_load
            if heartbeat
            else 0.0
        )

        running_jobs = self.get_running_jobs(node_id)
        cpus = max(1, registration.profile.capabilities.cpus)

        return NodeView(
            node_id=node_id,
            hostname=registration.hostname,
            agent_url=registration.agent_url,
            profile=registration.profile,
            current_load=current_load,
            running_jobs=running_jobs,
            slot_occupancy=running_jobs / cpus,
        )


    # Get nodes
    def get_nodes(self):
        with self.lock:
            nodes = []
            for node_id in self.registrations:
                view = self.get_node_view(node_id)
                if view is not None:
                    nodes.append(view)
            return nodes

    def get_node(self, node_id: str):
        return self.registrations.get(node_id)

    # Remove expired nodes
    def remove_expired_nodes(self, timeout_seconds: int=15):

        now = time.time()

        with self.lock:

            expired_nodes = []

            for node_id, last_seen in self.last_heartbeat.items():

                if now - last_seen > timeout_seconds:

                    expired_nodes.append(node_id)

            for node_id in expired_nodes:

                print(f"[expiration] removing node={node_id}")

                self.registrations.pop(node_id, None)
                self.heartbeats.pop(node_id, None)

                self.last_heartbeat.pop(node_id, None)
                self.running_jobs.pop(node_id, None)
                self.allocated_memory.pop(node_id, None)


    # Queues
    def enqueue_job(self, job: JobRequest):
        self.job_queue.put(job)

    def dequeue_job(self):
        try:
            return self.job_queue.get(timeout=1)
        except:
            return None

    def queue_size(self) -> int:
        return self.job_queue.qsize()

    def queue_empty(self):
        return self.job_queue.empty()

    # Dispatch attempts
    def record_dispatch_failure(self, job_id: str) -> int:
        """Count a failed dispatch for a job and return the new total."""
        with self.lock:
            attempts = self.dispatch_attempts.get(job_id, 0) + 1
            self.dispatch_attempts[job_id] = attempts
            return attempts

    def forget_dispatch_attempts(self, job_id: str):
        """Drop the failure counter once a job is placed or abandoned."""
        with self.lock:
            self.dispatch_attempts.pop(job_id, None)


    # Capacity and reservations
    def _fits(self, registration, job: JobRequest) -> bool:
        """Whether a node could take this job right now. Caller holds the lock."""
        capabilities = registration.profile.capabilities
        requirements = job.requirements

        if requirements.requires_gpu and not capabilities.gpu:
            return False

        used_cpus = self.running_jobs.get(registration.node_id, 0)
        if used_cpus + requirements.cpu_request > capabilities.cpus:
            return False

        if requirements.memory_mb is not None:
            used_memory = self.allocated_memory.get(registration.node_id, 0)
            if used_memory + requirements.memory_mb > capabilities.memory_mb:
                return False

        return True

    def reserve_slot(self, node_id: str, job: JobRequest) -> bool:
        """
        Atomically claim this job's resources on a node.

        Selection and dispatch cannot be one instruction, so a node may be
        expired or filled by the time the dispatcher acts on the policy's
        choice. Re-checking under the lock keeps usage within the node's real
        capacity and stops a removed node from being resurrected as a phantom
        entry.

        What was reserved is remembered per job, so release_slot can give back
        exactly the same amount without the caller having to track it.

        Returns False if the node is gone or cannot fit the job, in which case
        the caller should ask the policy again.
        """
        with self.lock:
            registration = self.registrations.get(node_id)

            if registration is None:
                return False

            if not self._fits(registration, job):
                return False

            requirements = job.requirements
            memory_mb = requirements.memory_mb or 0

            self.running_jobs[node_id] = (
                self.running_jobs.get(node_id, 0) + requirements.cpu_request
            )
            self.allocated_memory[node_id] = (
                self.allocated_memory.get(node_id, 0) + memory_mb
            )
            self.reservations[job.job_id] = (node_id, requirements.cpu_request, memory_mb)

            return True

    def release_slot(self, job_id: str):
        """
        Give back what a job reserved.

        Keyed by job rather than by node so it is idempotent: a duplicated
        completion callback, or one arriving after the node already expired,
        cannot free resources twice and drift the accounting below reality.
        """
        with self.lock:
            reservation = self.reservations.pop(job_id, None)

            if reservation is None:
                return

            node_id, cpu_request, memory_mb = reservation

            if node_id in self.running_jobs:
                self.running_jobs[node_id] = max(
                    0, self.running_jobs.get(node_id, 0) - cpu_request
                )

            if node_id in self.allocated_memory:
                self.allocated_memory[node_id] = max(
                    0, self.allocated_memory.get(node_id, 0) - memory_mb
                )

    def get_running_jobs(self, node_id: str):
        with self.lock:
            return self.running_jobs.get(node_id, 0)

    def node_has_capacity(self, node: NodeView, job: JobRequest):
        """Whether this node can fit this job."""
        with self.lock:
            registration = self.registrations.get(node.node_id)

            if registration is None:
                return False

            return self._fits(registration, job)

    def get_available_nodes(self, job: JobRequest):
        """
        Nodes that could run `job` right now.

        Filtering is per job because feasibility depends on what is being
        placed: a GPU job sees only GPU nodes, and a job asking for 4 GB sees
        only nodes with that much free.
        """
        with self.lock:
            return [
                node
                for node in self.get_nodes()
                if self.node_has_capacity(node, job)
            ]


# Global singleton cluster state
cluster_state = ClusterState()