"""
scheduler/db.py

SQLite database layer for cluster state persistence.

Tables:
- nodes: registered nodes and their metadata
- node_profiles: hardware benchmark results
- jobs: job submissions with timestamps
- job_results: job execution results with timestamps
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

DATABASE_PATH = os.getenv("SCHEDULER_DB", "scheduler.db")


def get_db_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Nodes table: registration info and heartbeat tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                agent_url TEXT NOT NULL,
                registered_at TIMESTAMP NOT NULL,
                last_heartbeat TIMESTAMP,
                current_load REAL DEFAULT 0.0
            )
        """)

        # Node profiles table: capabilities and benchmark results as JSON
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_profiles (
                node_id TEXT PRIMARY KEY,
                capabilities TEXT NOT NULL,
                cpu_profile TEXT,
                io_profile TEXT,
                memory_profile TEXT,
                gpu_profile TEXT,
                network_profile TEXT,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
            )
        """)

        # Jobs table: job submissions with lifecycle timestamps
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                image TEXT NOT NULL,
                command TEXT,
                status TEXT DEFAULT 'queued',
                submitted_at TIMESTAMP NOT NULL,
                dispatched_at TIMESTAMP,
                dispatched_to_node TEXT,
                FOREIGN KEY (dispatched_to_node) REFERENCES nodes(node_id)
            )
        """)

        # Job results table: execution outcomes with completion timestamp
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_results (
                job_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                runtime_seconds REAL NOT NULL,
                exit_code INTEGER NOT NULL,
                completed_at TIMESTAMP NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id)
            )
        """)

        # Indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_submitted
            ON jobs(submitted_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_results_completed
            ON job_results(completed_at)
        """)

        conn.commit()


# ============================================================================
# Node Operations
# ============================================================================

def register_node(node_id: str, hostname: str, agent_url: str) -> None:
    """Register a new node in the database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO nodes
            (node_id, hostname, agent_url, registered_at)
            VALUES (?, ?, ?, ?)
        """, (node_id, hostname, agent_url, datetime.utcnow()))


def save_node_profile(
    node_id: str,
    capabilities: Dict[str, Any],
    cpu_profile: Optional[Dict] = None,
    io_profile: Optional[Dict] = None,
    memory_profile: Optional[Dict] = None,
    gpu_profile: Optional[Dict] = None,
) -> None:
    """Save node profile with capabilities and benchmarks."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO node_profiles
            (node_id, capabilities, cpu_profile, io_profile, memory_profile, gpu_profile)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            json.dumps(capabilities),
            json.dumps(cpu_profile) if cpu_profile else None,
            json.dumps(io_profile) if io_profile else None,
            json.dumps(memory_profile) if memory_profile else None,
            json.dumps(gpu_profile) if gpu_profile else None,
        ))


def update_heartbeat(node_id: str, current_load: float) -> None:
    """Update node heartbeat and load."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE nodes
            SET last_heartbeat = ?, current_load = ?
            WHERE node_id = ?
        """, (datetime.utcnow(), current_load, node_id))


def get_node(node_id: str) -> Optional[Dict]:
    """Retrieve node metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_nodes() -> List[Dict]:
    """Retrieve all registered nodes."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes")
        return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# Job Operations
# ============================================================================

def submit_job(job_id: str, image: str, command: Optional[str] = None) -> None:
    """Record a job submission."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs
            (job_id, image, command, status, submitted_at)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, image, command, "queued", datetime.utcnow()))


def dispatch_job(job_id: str, node_id: str, dispatched_at: Optional[datetime] = None) -> None:
    """Record job dispatch to a node."""
    if dispatched_at is None:
        dispatched_at = datetime.utcnow()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET status = ?, dispatched_at = ?, dispatched_to_node = ?
            WHERE job_id = ?
        """, ("dispatched", dispatched_at, node_id, job_id))


def record_job_result(
    job_id: str,
    node_id: str,
    success: bool,
    runtime_seconds: float,
    exit_code: int,
    completed_at: Optional[datetime] = None,
) -> None:
    """Record job execution result."""
    if completed_at is None:
        completed_at = datetime.utcnow()

    with get_db() as conn:
        cursor = conn.cursor()

        # Insert result
        cursor.execute("""
            INSERT INTO job_results
            (job_id, node_id, success, runtime_seconds, exit_code, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job_id, node_id, success, runtime_seconds, exit_code, completed_at))

        # Update job status
        status = "completed" if success else "failed"
        cursor.execute("""
            UPDATE jobs
            SET status = ?
            WHERE job_id = ?
        """, (status, job_id))


def mark_job_failed(job_id: str) -> None:
    """
    Mark a job as failed without an execution result.

    Used when the dispatcher gives up before the job ever ran, so there is no
    runtime or exit code to record in job_results.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET status = ?
            WHERE job_id = ?
        """, ("failed", job_id))


def get_job(job_id: str) -> Optional[Dict]:
    """Retrieve job metadata."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_job_result(job_id: str) -> Optional[Dict]:
    """Retrieve job execution result."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM job_results WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_jobs() -> List[Dict]:
    """Retrieve all jobs."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs ORDER BY submitted_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_jobs_by_status(status: str) -> List[Dict]:
    """Retrieve jobs by status (queued, dispatched, completed, failed)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY submitted_at DESC",
            (status,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_jobs_for_node(node_id: str) -> List[Dict]:
    """Retrieve jobs dispatched to a specific node."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE dispatched_to_node = ? ORDER BY dispatched_at DESC",
            (node_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# Analytics / Metrics
# ============================================================================

def get_job_statistics() -> Dict[str, Any]:
    """Get overall job execution statistics."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Total jobs and status breakdown
        cursor.execute("""
            SELECT
                COUNT(*) as total_jobs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'dispatched' THEN 1 ELSE 0 END) as dispatched,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued
            FROM jobs
        """)
        row = cursor.fetchone()
        job_stats = dict(row) if row else {}

        # Execution time statistics for completed jobs
        cursor.execute("""
            SELECT
                COUNT(*) as successful_jobs,
                AVG(runtime_seconds) as avg_runtime_seconds,
                MIN(runtime_seconds) as min_runtime_seconds,
                MAX(runtime_seconds) as max_runtime_seconds
            FROM job_results
            WHERE success = 1
        """)
        row = cursor.fetchone()
        exec_stats = dict(row) if row else {}

        return {**job_stats, **exec_stats}


def get_node_job_summary(node_id: str) -> Dict[str, Any]:
    """Get job execution summary for a specific node."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_jobs_on_node,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                AVG(runtime_seconds) as avg_runtime_seconds
            FROM job_results
            WHERE node_id = ?
        """, (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}
