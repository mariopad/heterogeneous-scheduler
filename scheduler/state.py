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

        return NodeView(
            node_id=node_id,
            hostname=registration.hostname,
            agent_url=registration.agent_url,
            profile=registration.profile,
            current_load=current_load,
            running_jobs=self.get_running_jobs(node_id)
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


    # Running jobs
    def increment_running_jobs(self, node_id: str):
        with self.lock:
            self.running_jobs[node_id] = self.running_jobs.get(node_id, 0) + 1

    def decrement_running_jobs(self, node_id: str):
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