"""
scheduler/policies/base.py

Contract every scheduling policy must implement.

A policy is a pure placement decision: given the nodes that currently have
free capacity and the job about to be placed, return the node to run it on.
Policies must not perform I/O, touch the database or talk to agents; the
dispatcher owns all of that. This keeps policies cheap to unit-test and
comparable across experiments.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from shared.schemas import JobRequest, NodeView


class SchedulingPolicy(ABC):
    """Base class for node selection policies."""

    #: Name used by the CLI/env registry and recorded alongside experiment runs.
    name: str = "base"

    @abstractmethod
    def select_node(
        self,
        nodes: List[NodeView],
        job: JobRequest,
    ) -> Optional[NodeView]:
        """
        Choose a node for `job`.

        Args:
            nodes: Nodes with free capacity right now. May be empty.
            job:   The job being placed. Policies that ignore job properties
                   still accept it so that hardware-aware and ML policies can
                   be added without changing the dispatcher.

        Returns:
            The selected node, or None if the policy declines to place the job
            with the currently available nodes. Returning None makes the
            dispatcher wait and retry, so it is the correct answer for a job
            whose requirements no available node satisfies (for example a GPU
            job while every GPU node is busy).
        """
        raise NotImplementedError
