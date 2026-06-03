#from shared.schemas import NodeHeartbeat

class RoundRobinPolicy:
    def __init__(self):
        self.index = 0

    # Iterate through the nodes and rearrange indexes
    def select_node(self, nodes):

        if not nodes:
            return None

        node = nodes[self.index % len(nodes)]

        self.index += 1

        return node