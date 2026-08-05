# Workloads

Four containerised workloads, each stressing one subsystem, so that
heterogeneous hardware actually separates. A trace of identical trivial jobs
makes every policy score the same and demonstrates nothing.

| Workload | Stresses | `--size` means | Reports |
| -------- | -------- | -------------- | ------- |
| `cpu` | Floating point throughput | Matrix multiplications (512x512, float64) | GFLOPS |
| `memory` | RAM bandwidth | Working set in MiB | MB/s |
| `io` | Disk | MiB written, then random reads | MB/s, IOPS |
| `gpu` | Accelerator | Matrix multiplications (2048x2048, float32) | GFLOPS, backend |

Every workload prints one JSON object on stdout and exits non-zero on failure,
so the container log is enough to check that a run was sane and the agent's
exit code reflects what happened.

## Running

Identical on the host and in a container:

```bash
python -m workloads.run --type cpu --size 120
docker run heterosched/workload:latest --type cpu --size 120
```

`--size` scales the work roughly linearly. Calibrate it per cluster: aim for
jobs of a few seconds on your fastest node, so the weakest nodes stay within a
practical run time.

## Building

```bash
# CPU, memory and I/O. python:3.11-slim is multi-arch, so the same tag works
# on x86_64 desktops, the Pi and the Jetson.
docker build -t heterosched/workload:latest workloads/

# GPU: the base image must match the node's vendor and driver, see Dockerfile.gpu
docker build -f workloads/Dockerfile.gpu \
    --build-arg BASE=nvidia/cuda:12.2.0-runtime-ubuntu22.04 \
    -t heterosched/workload-gpu:latest workloads/
```

Every node needs the image present. Either build on each node, push to a
registry, or `docker save | ssh ... docker load`.

## Design notes

**One job means one core.** The BLAS thread count is pinned to 1 before numpy
is imported. Unpinned, a single job spreads over every core, and the
scheduler's slot accounting stops describing the node: placing four jobs on a
four-core machine would oversubscribe it fourfold rather than fill it.

**The CPU kernel matches the agent's benchmark.** Both do dense matrix
multiplication, so a benchmark-driven policy can use a node's measured GFLOPS
to predict how long this workload will take there. A workload stressing
something else would make the benchmark worthless as a predictor.

**Feedback is renormalised.** Each iteration feeds its output back in so the
loop cannot be optimised away. Without renormalising, entries grow about two
orders of magnitude per iteration and overflow to infinity within a few
hundred, after which the kernel measures arithmetic on infinities. The
checksum is a fixed point, so an unchanged value across sizes confirms the
computation stayed valid.

**fsync is mandatory in the I/O workload.** Without it the write phase
measures the page cache and every node looks equally fast, hiding exactly the
SSD-versus-SD-card difference the workload exists to expose.

**GPU jobs fail rather than fall back.** `gpu.run` raises when no device is
usable instead of quietly running on the CPU. A silent fallback would make
`requires_gpu` unfalsifiable: a misplaced GPU job has to be visible as a
failure, not hidden as a slow success.

## Declared requirements

`registry.requirements_for()` gives each workload type its default
requirements, which the trace generator attaches to every job it creates:

| Workload | `cpu_request` | `memory_mb` | `requires_gpu` |
| -------- | ------------- | ----------- | -------------- |
| `cpu` | 1 | 256 | no |
| `memory` | 1 | `size * 1.5 + 256` | no |
| `io` | 1 | 256 | no |
| `gpu` | 1 | 1024 | yes |

These are not advisory. The scheduler refuses to place a job on a node that
cannot fit it, and the agent applies `memory_mb` as a hard container limit and
`cpu_request` as a CPU quota. If a job that declared 512 MB could quietly use
4 GB, the scheduler's accounting would stop describing the node and any
placement based on it would be measuring nothing.

A trace can override any of them:

```json
{"workload": "cpu", "size": 200, "count": 4,
 "requirements": {"cpu_request": 2, "expected_duration_class": "long"}}
```
