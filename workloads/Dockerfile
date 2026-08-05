# Workload image for the CPU, memory and I/O benchmarks.
#
# python:3.11-slim publishes amd64, arm64 and arm/v7 variants and numpy ships
# wheels for all three, so the same tag works on the desktops, the laptop, the
# Raspberry Pi and the Jetson without per-node changes.
#
# The GPU workload is not in this image; see Dockerfile.gpu.

FROM python:3.11-slim

# numpy is the only dependency: the CPU and memory workloads use it, and the
# I/O workload is stdlib only.
RUN pip install --no-cache-dir "numpy>=1.24" \
    && rm -rf /root/.cache

WORKDIR /app

COPY __init__.py registry.py run.py cpu.py memory.py io.py gpu.py /app/workloads/

# Keep one job to one core. The scheduler accounts for a job as a single slot,
# so a multi-threaded BLAS would oversubscribe every node it landed on.
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "workloads.run"]
CMD ["--type", "cpu", "--size", "100"]
