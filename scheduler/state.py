"""
Objetivo del script: hacer que funcione esto
    cluster_state.register_node(...)
    cluster_state.get_nodes()
    cluster_state.get_next_node_rr()
"""

from typing import Dict, List, Optional
from shared.schemas import NodeHeartbeat


class ClusterState:
    def __init__(self):
        self.nodes: Dict[str, NodeHeartbeat] = {}
        self.round_robin_index = 0

    def register_heartbeat(self, heartbeat: NodeHeartbeat):
        """
        Add or update node heartbeat info.
        """
        self.nodes[heartbeat.node_id] = heartbeat

    def get_nodes(self) -> List[NodeHeartbeat]:
        return list(self.nodes.values())

    def get_node(self, node_id: str) -> Optional[NodeHeartbeat]:
        return self.nodes.get(node_id)

    def get_next_node_round_robin(self) -> Optional[NodeHeartbeat]:
        """
        Select next node using Round Robin scheduling.
        """
        nodes = self.get_nodes()

        if not nodes:
            return None

        node = nodes[self.round_robin_index % len(nodes)]

        self.round_robin_index += 1

        return node


# Global singleton cluster state
cluster_state = ClusterState()