from shared.schemas import (
    NodeCapabilities,
    GPUBenchmarkProfile,
)

def benchmark_gpu() -> GPUBenchmarkProfile:
    result = GPUBenchmarkProfile()
    return result