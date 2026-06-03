"""
Objetivo del script: hacer que funcione esto
    cluster_state.register_node(...)
    cluster_state.get_nodes()
    cluster_state.get_next_node_rr()
"""

from typing import Dict, List, Optional
from shared.schemas import (
    NodeHeartbeat,
    JobRequest
)
from queue import Queue
import time

class ClusterState:
    def __init__(self):
        self.nodes: Dict[str, NodeHeartbeat] = {}
        self.round_robin_index = 0
        self.job_queue = Queue()
        self.running_jobs: Dict[str, int] = {}
        self.last_heartbeat: Dict[str, float] = {}

    def register_heartbeat(self, heartbeat: NodeHeartbeat):
        """
        Add or update node heartbeat info.
        """
        self.nodes[heartbeat.node_id] = heartbeat

        self.last_heartbeat[heartbeat.node_id] = time.time()

        if heartbeat.node_id not in self.running_jobs:
            self.running_jobs[heartbeat.node_id] = 0

    # Get nodes
    def get_nodes(self) -> List[NodeHeartbeat]:
        return list(self.nodes.values())

    def get_node(self, node_id: str) -> Optional[NodeHeartbeat]:
        return self.nodes.get(node_id)

    # Remove expired nodes
    def remove_expired_nodes(self, timeout_seconds: int=15):

        now = time.time()

        expired_nodes = []

        for node_id, last_seen in self.last_heartbeat.items():

            if now - last_seen > timeout_seconds:

                expired_nodes.append(node_id)

        for node in expired_nodes:

            print(f"[expiration] removing node={node_id}")

            self.nodes.pop(node_id, None)

            self.last_heartbeat.pop(node_id, None)

            self.running_jobs.pop(node_id, None)


    # Queues
    def enqueue_job(self, job: JobRequest):
        self.job_queue.put(job)

    def dequeue_job(self):
        return self.job_queue.get()

    def queue_size(self) -> int:
        return self.job_queue.qsize()


    # Running jobs
    def increment_running_jobs(self, node_id: str):
        self.running_jobs[node_id] += 1

    def decrement_running_jobs(self, node_id: str):
        self.running_jobs[node_id] -= 1

    def get_running_jobs(self, node_id: str):
        return self.running_jobs.get(node_id, 0)

    # Is the node able to accept more jobs?
    def node_has_capacity(self, node: NodeHeartbeat) -> bool:

        running_jobs = self.get_running_jobs(node.node_id)

        max_parallel_jobs = node.capabilities.cpus

        # Debug!!
        return running_jobs < 1 # max_parallel_jobs

    
    
    # Iterate through the nodes and rearrange indexes
    def get_next_node_round_robin(self) -> Optional[NodeHeartbeat]:

        nodes = self.get_nodes()

        if not nodes:
            return None

        total_nodes = len(nodes)

        for _ in range(total_nodes):

            node = nodes[self.round_robin_index % total_nodes]

            self.round_robin_index += 1

            if self.node_has_capacity(node):
                return node

        return None


# Global singleton cluster state
cluster_state = ClusterState()