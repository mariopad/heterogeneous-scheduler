from typing import List, Optional

from scheduler.policies.base import SchedulingPolicy
from shared.schemas import JobRequest, NodeView


class LeastLoadedPolicy(SchedulingPolicy):
    """
    Send the job to the least busy node.

    Busyness is ranked by slot occupancy first (running jobs divided by the
    node's core count) and by the heartbeat CPU load only as a tie-breaker.

    Occupancy leads because it is exact and updates the instant a job is
    dispatched, whereas `current_load` is measured on the agent and only
    reaches the scheduler on the next heartbeat. Ranking by `current_load`
    alone made every job of a burst land on the same node, since the load
    figure could not move until the heartbeat interval had elapsed.

    Dividing by core count is what makes the policy heterogeneity-aware: a
    12-thread desktop absorbs proportionally more jobs than a 4-core board
    before it is considered equally loaded. The measured load still decides
    between equally occupied nodes, which is where it carries the real
    information -- background work the scheduler did not put there.
    """

    name = "least_loaded"

    def select_node(
        self,
        nodes: List[NodeView],
        job: JobRequest,
    ) -> Optional[NodeView]:

        if not nodes:
            return None

        return min(
            nodes,
            key=lambda n: (n.slot_occupancy, n.current_load)
        )
