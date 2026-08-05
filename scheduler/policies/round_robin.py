from typing import List, Optional

from scheduler.policies.base import SchedulingPolicy
from shared.schemas import JobRequest, NodeView


class RoundRobinPolicy(SchedulingPolicy):
    """
    Cycle through the available nodes, one job each.

    The counter advances only when a job is actually placed, so a run is
    reproducible: the Nth job of a trace always lands on the same node
    regardless of how long the scheduler sat idle between submissions.
    """

    name = "round_robin"

    def __init__(self):
        self.index = 0

    def select_node(
        self,
        nodes: List[NodeView],
        job: JobRequest,
    ) -> Optional[NodeView]:

        if not nodes:
            return None

        node = nodes[self.index % len(nodes)]

        self.index += 1

        return node
