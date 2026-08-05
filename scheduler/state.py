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


    # Running jobs
    def reserve_slot(self, node_id: str) -> bool:
        """
        Atomically claim a job slot on a node.

        Selection and dispatch cannot be one instruction, so a node may be
        expired or filled by the time the dispatcher acts on the policy's
        choice. Re-checking capacity under the lock keeps `running_jobs` from
        exceeding the node's core count, and stops a removed node from being
        resurrected as a phantom entry.

        Returns False if the node is gone or already at capacity, in which
        case the caller should ask the policy again.
        """
        with self.lock:
            registration = self.registrations.get(node_id)

            if registration is None:
                return False

            running_jobs = self.running_jobs.get(node_id, 0)

            if running_jobs >= registration.profile.capabilities.cpus:
                return False

            self.running_jobs[node_id] = running_jobs + 1
            return True

    def release_slot(self, node_id: str):
        """Give back a slot claimed by reserve_slot."""
        with self.lock:
            if node_id in self.running_jobs:
                self.running_jobs[node_id] = max(0, self.running_jobs.get(node_id, 0) - 1)

    def get_running_jobs(self, node_id: str):
        with self.lock:
            return self.running_jobs.get(node_id, 0)

    # Is the node able to accept more jobs?
    def node_has_capacity(self, node: NodeView):
        with self.lock:
            running_jobs = self.get_running_jobs(node.node_id)
            max_parallel_jobs = node.profile.capabilities.cpus

            return running_jobs < max_parallel_jobs

    
    # Get available nodes: existing and room for work
    def get_available_nodes(self):
        with self.lock:
            return [
                node
                for node in self.get_nodes()
                if self.node_has_capacity(node)
            ]


# Global singleton cluster state
cluster_state = ClusterState()