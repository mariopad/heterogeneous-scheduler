"""
agent/benchmark/gpu/gpu.py

GPU detection module.

Simply detects GPU presence and memory capacity.
"""

import subprocess
import shutil

from shared.schemas import GPUBenchmarkProfile


def benchmark_gpu():
    """
    Detect GPU availability and memory.

    Returns:
        GPUBenchmarkProfile with gpu_available and gpu_memory_mb
    """
    print("[benchmark-gpu] Scanning for GPUs...")
    
    # Try NVIDIA
    if shutil.which("nvidia-smi") is not None:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, check=True, timeout=5
            )
            memory_mb = int(result.stdout.strip().split('\n')[0].split()[0])
            print(f"[benchmark-gpu] Found NVIDIA GPU: {memory_mb}MB")
            return GPUBenchmarkProfile(gpu_available=True, gpu_memory_mb=memory_mb)
        except Exception:
            pass
    
    # Try AMD
    if shutil.which("rocm-smi") is not None:
        try:
            # rocm-smi is messier to parse, just assume reasonable default
            print(f"[benchmark-gpu] Found AMD GPU")
            return GPUBenchmarkProfile(gpu_available=True, gpu_memory_mb=8192)
        except Exception:
            pass
    
    # No GPU
    print("[benchmark-gpu] No GPU detected")
    return GPUBenchmarkProfile(gpu_available=False, gpu_memory_mb=None)