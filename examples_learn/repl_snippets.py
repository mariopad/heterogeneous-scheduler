##################################################################
# 1. Prueba de scheduler/state y shared/schemas
##################################################################
from scheduler.state import cluster_state
from shared.schemas import *

hb = NodeHeartbeat(
    node_id="node-1",
    hostname="test",
    capabilities=NodeCapabilities(
        cpus=4,
        memory_mb=8192,
        gpu=False,
        architecture="x86_64"
    ),
    current_load=0.3
)

cluster_state.register_heartbeat(hb)

print(cluster_state.get_nodes())
print(cluster_state.get_next_node_round_robin())

"""
Print 1:

[NodeHeartbeat(
    node_id='node-1', hostname='test', 
    capabilities=NodeCapabilities(cpus=4, 
                                  memory_mb=8192, 
                                  gpu=False, 
                                  architecture='x86_64'
                                  ), 
    current_load=0.3
    )
]
"""

"""
Print 2:

node_id='node-1' 
hostname='test' 
capabilities=NodeCapabilities(cpus=4,
                              memory_mb=8192, 
                              gpu=False, 
                              architecture='x86_64') 
current_load=0.3
"""
##################################################################



##################################################################
# 2.
##################################################################