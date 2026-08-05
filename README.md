# heterogeneous-scheduler

## To-dos
### Immediate: Local MVP
- [x] Primitive scheduler
- [x] Queue jobs
- [x] Async Dispatch
- [x] Cope with oversubscription 
- [x] Heartbeat expiration
- [x] Add different node selection policies
- [ ] Benchmark metrics locally
    - [ ] Add a policy based on benchmark score
- [ ] Add example: think of a task and implement it

### Jobs
- [ ] Implement different kinds of workloads

### Scheduler
- [x] Run-scoped persistence (jobs tagged with the experiment that produced them)
- [x] Experiment harness and metrics export
- [ ] Reschedule jobs from nodes that die mid-run

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

## Running an experiment

Start the scheduler and one agent per node, then drive a trace through them.
The harness talks to the scheduler over HTTP only, so the same command works
locally and against the real cluster.

```bash
# 1. scheduler (any node; the policy can also be swapped per run)
uvicorn scheduler.main:app --host 0.0.0.0 --port 8000

# 2. one agent per worker
SCHEDULER_URL=http://<scheduler-host>:8000 python -m agent.main

# 3. compare two policies on the same trace and cluster
python -m experiments.run_experiment \
    --trace experiments/traces/burst.json \
    --policy round_robin --policy least_loaded \
    --expect-nodes 6 --out results/
```

Each run gets a `run_id`; jobs are tagged with it, so results from different
policies never mix. A run refuses to start unless the cluster is drained, and
the policy is re-instantiated per run so state like the round-robin counter
always starts from zero.

Re-export an old run at any time, without a cluster running:

```bash
python -m experiments.export --list
python -m experiments.export <run_id> --out results/
```

This writes `<policy>_<run_id>_jobs.csv` (per-job queue wait, runtime,
turnaround), `_nodes.csv` (per-node counts and utilisation) and
`_summary.json` (makespan, throughput, distributions, fairness).

### Metrics

| Metric | Meaning |
| ------ | ------- |
| `queue_wait_s` | submission to dispatch: the scheduler's own delay |
| `runtime_s` | container execution, measured on the agent |
| `turnaround_s` | submission to completion |
| `overhead_s` | turnaround minus wait minus runtime: dispatch and callback cost |
| `makespan_s` | first submission to last completion |
| `fairness_jobs` | Jain's index over raw per-node job counts |
| `fairness_jobs_per_cpu` | Jain's index over jobs per core |

The two fairness figures answer different questions. Equal job counts are not
fair on heterogeneous hardware -- a Raspberry Pi should not receive as much
work as a 12-thread desktop -- so `fairness_jobs_per_cpu` is the one that
measures allocation proportional to capacity. Both are reported.

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
