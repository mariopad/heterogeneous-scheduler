from shared.schemas import NodeHeartbeat
#from scheduler.state import cluster_state

class LeastLoadedPolicy:

    # Iterate through the nodes and rearrange indexes
    def select_node(self, nodes):

        if not nodes:
            return None

        return min(
            nodes,
            key=lambda n: n.current_load
        ) 