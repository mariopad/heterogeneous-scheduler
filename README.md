# heterogeneous-scheduler
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
