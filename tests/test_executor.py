from agent.executor import execute_job
from shared.schemas import JobAssignment

result = execute_job(
    node_id="test-node",
    assignment=JobAssignment(
        job_id="job-1",
        image="ubuntu",
        command="echo hello"
    )
)

print(result)

# Todo perfecto:
# [executor] running image=ubuntu job=job-1
# job_id='job-1' node_id='test-node' success=True runtime_seconds=0.21371912956237793 exit_code=0