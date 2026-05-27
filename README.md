# heterogeneous-scheduler

## To-dos
### Verify and complete the local MVP
- [ ] Add different node selection policies
- [ ] Benchmark metrics locally
- [ ] Add example: think of a task and implement it

### Jobs
- [ ] Implement different kinds of workloads

### Scheduler
- [ ] Add more execution metrics:
    - Throughput ...

### Long-term
- [ ] Test on the distributed cluster
- [ ] ML based node selection
- [ ] Fallen nodes strategies
- [ ] Power consumption estimation
- [ ] Node selection based on power consumption
- [ ] Decide if PS4 is viable:
      - High power consumption
      - Weak CPU
      - No drivers for squeezing the GPU

## Hardware Cluster

| Device               | Role                       |
| -------------------- | -------------------------- |
| Old i3 desktop       | Low-end CPU node           |
| Jailbroken PS4 **!?** | Experimental node          |
| Jetson Nano 2GB      | ARM + CUDA edge node       |
| Raspberry Pi 4 4GB   | ARM low-power node         |
| Ryzen 2700U laptop   | Mid-tier mobile node       |
| Ryzen 5600X + RX6600 | Main high-performance node |

## Basic structure and functionality

1. Scheduler
- Receive node heartbeats
- Store node metrics
- Receive jobs
- Select best node
    - Round Robin
    - Least Loaded
    - another one like a weighted one idk
    - ML based one (e.g. via inference of execution time)
- Dispatch workloads
- Collect execution statistics

2. Agents
- Collect metrics
- Execute jobs
- Benchmark node
- Report node capabilities and status
- Report execution results

3. Jobs
- CPU bound
- I/O bound
- Memory bound
- GPU bound /?
